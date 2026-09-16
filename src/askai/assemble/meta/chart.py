"""Whether an answer can be charted, and under which views -- read, never inferred.

Purity: pure.

FR-37d asks the answer to carry a ``chartable`` block stating availability, the default
view and the named alternate views. ``narrate/package.py`` has carried the block since
Story 1.15, stubbed unavailable; this is the module that fills it.

Recorded failure F-035 is the whole reason the direction of the check matters. The client
renders whatever the block offers, so a view offered and not supported is a broken chart in
front of a Council member. Every rule here therefore **narrows** what the published
configuration declares and none can widen it:

* ``R-CHART-VIEWS-COME-FROM-THE-PUBLISHED-CONFIGURATION`` -- the views offered are the ones
  the configuration names, and no others, even where the engine could compute more.
* ``R-CHART-KNOWN-VIEW-CODES`` -- a declared code this build does not know how to produce a
  series for is dropped rather than passed through. An unrecognised code reaching a client
  is a view nobody has checked the engine can fill.
* ``R-CHART-A-SINGLE-FIGURE-IS-NOT-A-CHART`` -- one value has no series, and a chart of it
  is an empty canvas the client has already committed to showing.

The mapping lives in ``rules/`` rather than here, which is AD-11 as Story 5.10 quotes it:
*"when chart behaviour needs tuning, the configuration mapping lives in rules/, not in
composer code."*

**What is missing, and it is the input.** ``INDICATOR ||--|| CHART_CONFIG`` is one per
indicator, 189/189, and the export carries it in ``P07`` with the alternate views split out
into ``P07b``. The read model has **no table for either**: the ingest of Story 1.8
materialises five tables and none of them is a chart. So ``PublishedChart`` is declared
here as the value the configuration would arrive as, ``chartable_for`` takes it, and
``None`` -- which is what every caller can supply today -- produces an unavailable block.
That is the honest answer while the table is missing: the engine says it cannot chart this,
which is exactly what it must say when it holds no configuration, and it offers nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from askai.rules import RuleSet

__all__ = [
    "ChartClause",
    "ChartOffer",
    "ChartRule",
    "PublishedChart",
    "chartable_for",
    "known_view_codes",
]


class ChartRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    FROM_CONFIGURATION = "R-CHART-VIEWS-COME-FROM-THE-PUBLISHED-CONFIGURATION"
    KNOWN_CODES = "R-CHART-KNOWN-VIEW-CODES"
    SINGLE_FIGURE = "R-CHART-A-SINGLE-FIGURE-IS-NOT-A-CHART"


class ChartClause(StrEnum):
    """The clause names read off those rules."""

    ONLY_DECLARED = "offer_only_declared_views"
    VIEW_CODES = "view_codes"
    CHART_A_SINGLE_FIGURE = "chart_a_single_figure"


class ChartError(LookupError):
    """The chart rules cannot be acted on.

    Raised rather than defaulted to "everything is chartable". Every default available
    here offers the client something, and the one thing F-035 says must never happen is a
    view offered that the configuration does not support.
    """


@dataclass(frozen=True, slots=True)
class ChartOffer:
    """What this composer decided, in the three fields ``narrate/`` builds its block from.

    A type of its own rather than ``narrate.package.Chartable``, and the reason is
    structural: ``assemble/`` sits **below** ``narrate/`` in the layer contract and may not
    import it. That is not an inconvenience to route around -- the composer decides what
    may be offered and the package layer decides how an answer carries it, and a composer
    that could construct the package's own type would be a composer that could build half a
    package.

    The invariant is restated here rather than left to the layer above, because a caller
    that mapped this onto a package field would carry the offer across the boundary and the
    check with it: a block that is not available names no views, or a client is offered a
    chart it cannot draw (F-035).
    """

    available: bool = False
    default_view: str | None = None
    alternate_views: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.available and (self.default_view or self.alternate_views):
            raise ValueError(
                "an answer that cannot be charted names no views; offering one for a "
                "chart that cannot be drawn is a client-side failure with a server-side "
                "cause"
            )


@dataclass(frozen=True, slots=True)
class PublishedChart:
    """One indicator's published chart configuration, as the export carries it.

    Declared in ``assemble/`` and not in ``ports/`` on purpose: there is no adapter that
    returns one, because the read model has no chart table. A port with no implementation
    would read as a wiring oversight; a value type read as a plain input says what it is --
    the shape this composer will take when the table exists, and the shape the tests supply
    today.

    ``default_view`` may be empty, and that is a published state rather than a missing
    field: a configuration that declares a chart type and no default view has said the
    indicator is drawn and not said under which view, and the composer treats that as no
    chart rather than picking one of the alternates.
    """

    indicator_id: str
    chart_type: str
    default_view: str
    alternate_views: tuple[str, ...] = ()


def known_view_codes(rule_set: RuleSet) -> frozenset[str]:
    """The published alternate-view codes this build can produce a series for."""
    value = rule_set.value(ChartRule.KNOWN_CODES.value, ChartClause.VIEW_CODES.value)
    if not isinstance(value, tuple):
        raise ChartError(
            f"{ChartRule.KNOWN_CODES.value} value `{ChartClause.VIEW_CODES.value}` must "
            f"be a list of view codes, not {type(value).__name__}; without it the engine "
            "would pass every declared code through unchecked"
        )
    return frozenset(code.casefold() for code in value)


def chartable_for(
    rule_set: RuleSet, configuration: PublishedChart | None, *, has_a_series: bool
) -> ChartOffer:
    """The chart offer for an answer, from *configuration*.

    ``None`` -- which is what every caller can supply while the read model holds no chart
    table -- produces an unavailable block naming no views. That is the correct answer and
    not a placeholder: the engine has no published configuration for this indicator, so it
    states that it cannot chart the answer, which is precisely what FR-37d requires when the
    configuration does not support one.

    *has_a_series* is keyword-only because it is the argument a caller is most likely to
    pass by accident in the wrong position, and passing it wrongly offers a chart of a
    single figure -- the one outcome ``R-CHART-A-SINGLE-FIGURE-IS-NOT-A-CHART`` exists to
    prevent.
    """
    _require(rule_set, ChartRule.FROM_CONFIGURATION, ChartClause.ONLY_DECLARED, True)
    _require(rule_set, ChartRule.SINGLE_FIGURE, ChartClause.CHART_A_SINGLE_FIGURE, False)
    if configuration is None or not has_a_series:
        return ChartOffer()
    default = configuration.default_view.strip()
    if not default:
        return ChartOffer()
    known = known_view_codes(rule_set)
    return ChartOffer(
        available=True,
        default_view=default,
        # Filtered against the known codes and de-duplicated in the order the
        # configuration declares them, so the same published chart yields the same block on
        # every run (AD-17). A code the configuration declares twice is one view.
        alternate_views=_offered(configuration.alternate_views, known, default),
    )


def _offered(declared: Sequence[str], known: frozenset[str], default: str) -> tuple[str, ...]:
    """The declared alternates this build knows, minus the default, in declared order.

    The default is removed because it is already stated in its own field, and a client
    reading both would offer the same view twice. Dropping an unknown code rather than
    raising: a configuration naming a view this build cannot fill is a real state during a
    rollout, and refusing the whole block would take a working chart down over an extra
    view nobody asked for.
    """
    offered: list[str] = []
    for code in declared:
        cleaned = code.strip()
        if not cleaned or cleaned.casefold() not in known:
            continue
        if cleaned.casefold() == default.casefold() or cleaned in offered:
            continue
        offered.append(cleaned)
    return tuple(offered)


def _require(rule_set: RuleSet, rule: ChartRule, clause: ChartClause, position: bool) -> None:
    value = rule_set.value(rule.value, clause.value)
    if value is not position:
        raise ChartError(
            f"{rule.value} value `{clause.value}` is {value!r}; this composer implements "
            f"it as {position!r} and has no other form, so composing anyway would offer a "
            "view the published configuration does not support (F-035)"
        )
