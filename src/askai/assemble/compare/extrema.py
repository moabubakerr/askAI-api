"""Superlatives, ranks and spreads -- **one** composer over one bound scope.

Purity: pure. Reads its polarity table and its rank switch from ``rules/``.

Stories 4.6, 4.7 and 4.8 are one module because they are one computation seen three
ways: order a bound scope, and then say the top of it, a named member's place in it, or
the distance across it. Three modules would be three orderings, and F-015 and finding 43
are both the same shape -- a superlative composed once and then quietly recomputed by a
later rebuild that disagreed with it.

**A superlative names what carries it** (FR-25, FR-58). *"Highest"* is not an answer. The
answer is a country or a period, and the figure follows it -- which is why ``Candidate``
pairs a label with a figure and there is no path through this module that returns a value
without one. F-027 is the recorded failure: asked which country had the lowest inflation,
the predecessor answered with one country's historical low, engaging no country dimension
at all. So ``Scope`` is a required argument, it is stated in the answer, and R-166's
clause -- *"a ranking over periods is never presented as a ranking over countries"* -- is
carried by having two different sentences rather than one sentence with a hole in it.

**Polarity decides "best", and an unpublished polarity is stated** (FR-25). ``best`` and
``worst`` are not synonyms for ``highest`` and ``lowest``: on an indicator whose published
polarity is ``Decrease``, the best figure is the lowest one. Where the published layer
declares neither spelling there is no direction to read, so the answer says which
direction it used. It does not assume higher is better, which is wrong on every rank in
the catalogue.

**A rank is returned, never computed** (FR-26, R-COMPARE-RANK-IS-NEVER-COMPUTED). Ranking
reaches 12 of 189 indicators. On the other 177 the answer states that the indicator does
not publish a ranking; it does not order whatever rows it happens to hold and present the
result as one. What *is* composed here is the ordinal position of a named member within a
scope of published ranks -- which is a different claim, and reads as one.

**A spread is `Derived`, in the unit the distance is actually in** (FR-19, FR-21, FR-27,
AD-4). Both endpoints are named with their figures, so the subtraction is checkable rather
than asserted, and the two input rows travel back on ``row_ids``. Over an indicator
published in percent the result is in **percentage points**, and it is points because
``domain.difference.spread`` performed an actual ``Percent - Percent`` -- not because a
unit string was swapped on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.compare.composed import Composed
from askai.assemble.compare.ordinals import ordinal
from askai.assemble.compare.selection import CompareClause, CompareRule, SelectionRuleError
from askai.assemble.elements import derived, measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.difference import spread as difference
from askai.domain.normalise import normalise
from askai.execute.value import Figure
from askai.messages import Catalogue, Lang, compose_counted, render, render_period
from askai.ports.presentation import PublishedDetail
from askai.rules import RuleSet

__all__ = [
    "Candidate",
    "Direction",
    "ExtremumMessage",
    "Scope",
    "best_direction",
    "extremum",
    "ordered",
    "ranking",
    "spread",
]


class ExtremumMessage:
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    HIGHEST_COUNTRY = "extremum.highest_country"
    LOWEST_COUNTRY = "extremum.lowest_country"
    HIGHEST_PERIOD = "extremum.highest_period"
    LOWEST_PERIOD = "extremum.lowest_period"
    DIRECTION_UNPUBLISHED = "extremum.direction_unpublished"
    HIGHER = "direction.higher"
    LOWER = "direction.lower"

    RANK_POSITION = "sentence.rank_position"
    RANK_NOT_PUBLISHED = "rank.not_published"

    SPREAD_BETWEEN = "spread.between"
    SPREAD_NEEDS_TWO = "spread.needs_two"

    COUNTED_COUNTRY = "count.country"


class Direction(StrEnum):
    """Which end of the ordering the answer is about. Closed, and never defaulted."""

    HIGHEST = "highest"
    LOWEST = "lowest"


class Scope(StrEnum):
    """What the superlative ranges over -- and it is stated, never inferred.

    R-166's clause, as a type. A ranking over periods presented as a ranking over
    countries is the F-027 answer, and the only reliable way to stop a composer sliding
    between them is to make the caller say which it has and to render a different
    sentence for each.
    """

    COUNTRIES = "countries"
    PERIODS = "periods"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One thing that could carry the superlative, and the published figure that decides.

    ``label`` is already reader-facing and already in the reader's language -- a country
    name from the published layer, the catalogue's phrase for national scope, or a period
    written in the language's own period form. It is composed by the caller because the
    caller is the one that knows which of those three it has, and composing it here would
    need a country name in this module.
    """

    label: str
    figure: Figure

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError(
                "a superlative names what carries it, so a candidate carries the name; "
                "an unnamed candidate would produce a figure with nothing attached to it"
            )


def best_direction(polarity: str | None, rule_set: RuleSet) -> Direction | None:
    """Which end of the ordering is *better* for an indicator published with *polarity*.

    ``None`` -- the honest answer -- when the published layer declares no polarity, or
    declares one the table does not know. The caller states the direction it used rather
    than picking one, because on a rank or an unemployment rate "higher is better" is
    simply false and a silent default would be wrong more often than right.
    """
    if polarity is None or not polarity.strip():
        return None
    higher = _spellings(rule_set, CompareRule.POLARITY_DECIDES_BEST, CompareClause.HIGHER_IS_BETTER)
    lower = _spellings(rule_set, CompareRule.POLARITY_DECIDES_BEST, CompareClause.LOWER_IS_BETTER)
    folded = normalise(polarity)
    if any(folded == normalise(spelling) for spelling in higher):
        return Direction.HIGHEST
    if any(folded == normalise(spelling) for spelling in lower):
        return Direction.LOWEST
    return None


def ordered(candidates: tuple[Candidate, ...], direction: Direction) -> tuple[Candidate, ...]:
    """*candidates*, best-first for *direction*.

    The one ordering in this module. Every answer it composes reads off this tuple, so a
    superlative and the rank beside it cannot disagree about which member is first -- the
    F-015 shape, where a figure is composed once and then recomputed by a later rebuild.

    Ties are broken by label so the same scope orders the same way on every run (AD-17);
    the alternative is two equal figures swapping places between processes and an answer
    a QC tester cannot diff against yesterday's.
    """
    return tuple(
        sorted(
            candidates,
            key=lambda one: (one.figure.value, one.label),
            reverse=direction is Direction.HIGHEST,
        )
    )


def extremum(
    candidates: tuple[Candidate, ...],
    direction: Direction,
    scope: Scope,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
    direction_was_published: bool = True,
) -> Composed:
    """The member of *candidates* at the *direction* end, named, with its figure after it.

    *direction_was_published* is false when the reader asked for *best* or *worst* and
    the indicator publishes no polarity. The direction is then stated in its own note --
    FR-25's *"asks or states which direction it used"*, taking the second branch, because
    an engine that has a figure and a scope can say what it did rather than stopping.
    """
    if not candidates:
        raise ValueError(
            "a superlative is taken over a bound scope, and this scope is empty; an "
            "empty scope is refused where the rows are, not named here"
        )
    role = Role.HEADLINE
    winner = ordered(candidates, direction)[0]
    written = formatter.format(
        winner.figure.value,
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        lang,
    )
    provenance = _provenance(winner.figure, published)
    # The name leads and the figure follows (FR-58); which of the two comes first in the
    # sentence is the catalogue's decision per language, and the id it is authored under
    # is what carries that decision.
    carried: dict[str, object] = {
        "carrier": winner.label,
        "detail": published.name,
        "value": written.value,
        "unit": written.unit,
    }
    if scope is Scope.COUNTRIES:
        # The period is stated for a comparison *across countries*, because a reader has
        # to know which moment the countries were lined up at. For a superlative across
        # periods the carrier already is the period, and naming it twice would read as
        # two facts where there is one.
        carried["period"] = render_period(catalogue, lang, winner.figure.period)
    headline = Placed(
        element=measured(
            render(catalogue, lang, _extremum_message(direction, scope), **carried),
            provenance,
        ),
        role=role,
    )
    if direction_was_published:
        return Composed(elements=(headline,), row_ids=(winner.figure.source_datapoint_id,))
    return Composed(
        elements=(
            headline,
            Placed(
                element=derived(
                    render(
                        catalogue,
                        lang,
                        ExtremumMessage.DIRECTION_UNPUBLISHED,
                        detail=published.name,
                        direction=render(catalogue, lang, _direction_word(direction)),
                    ),
                    provenance,
                ),
                role=Role.NOTE,
            ),
        ),
        row_ids=(winner.figure.source_datapoint_id,),
    )


def ranking(
    candidates: tuple[Candidate, ...],
    subject: str,
    direction: Direction,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
    lang: Lang,
) -> Composed:
    """Where *subject* sits in the bound scope, as an ordinal in the reader's language.

    *subject* is one of the candidates' labels. Matched on the engine's single fold, so a
    casing or spacing difference between the label the caller composed and the label it
    is asking about does not silently produce "not in the scope".

    Refuses outright where the indicator publishes no ranking
    (``R-COMPARE-RANK-IS-NEVER-COMPUTED``): the refusal states that this indicator does
    not publish a ranking, which is a fact about the catalogue, rather than ordering the
    rows that happen to be in hand and presenting the result as a rank.
    """
    if _ranks_are_computed(rule_set):
        raise SelectionRuleError(
            f"{CompareRule.RANK_IS_NEVER_COMPUTED.value} says a rank may be computed, "
            "and this composition returns only published ones; ranking reaches 12 of 189 "
            "indicators, so the disagreement is raised rather than resolved in favour of "
            "either side"
        )
    if not formatter.is_rank(PublishedFormat(unit=published.unit, spec=published.value_format)):
        return Composed(
            reason=render(
                catalogue, lang, ExtremumMessage.RANK_NOT_PUBLISHED, detail=published.name
            )
        )

    placed = ordered(candidates, direction)
    position = _position_of(subject, placed)
    if position is None:
        raise ValueError(
            f"{subject!r} is not one of the candidates in this scope, so it has no place "
            "in it; a rank is a position within a bound scope and not a claim about one"
        )
    carrier = placed[position - 1]
    role = Role.HEADLINE
    return Composed(
        elements=(
            Placed(
                element=derived(
                    compose_counted(
                        catalogue,
                        lang,
                        ExtremumMessage.RANK_POSITION,
                        ExtremumMessage.COUNTED_COUNTRY,
                        len(placed),
                        carrier=carrier.label,
                        detail=published.name,
                        ordinal=ordinal(
                            position, role, catalogue, formatter, placement, rule_set, lang
                        ),
                        period=render_period(catalogue, lang, carrier.figure.period),
                    ),
                    _provenance(carrier.figure, published),
                ),
                role=role,
            ),
        ),
        row_ids=tuple(one.figure.source_datapoint_id for one in placed),
    )


def spread(
    candidates: tuple[Candidate, ...],
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
    lang: Lang,
) -> Composed:
    """The distance between the extrema of a bound scope, with both endpoints named.

    Class ``derived``, because it is: the number is computed here and the two rows it was
    computed from are stated in the content and carried on ``row_ids`` (FR-19, AD-4). A
    spread that named only its own figure would be the one number in an answer a reader
    could not check.

    On an indicator published in percent the result carries the points unit, and it
    carries it because ``domain.difference.spread`` subtracted two ``Percent`` values and
    got points back. The unit spelling comes from the same rule that decided the
    subtraction was a percentage one, so the arithmetic and the label cannot disagree.
    """
    if len(candidates) < _pair():
        return Composed(
            reason=render(
                catalogue, lang, ExtremumMessage.SPREAD_NEEDS_TWO, detail=published.name
            )
        )
    role = Role.DELTA
    placed = ordered(candidates, Direction.HIGHEST)
    high, low = placed[0], placed[-1]

    in_percent = _is_percent(published.unit, rule_set)
    gap = difference(high.figure.value, low.figure.value, measured_in_percent=in_percent)
    shown = PublishedFormat(
        unit=_points_unit(rule_set) if in_percent else published.unit,
        spec=published.value_format,
    )
    figures = PublishedFormat(unit=published.unit, spec=published.value_format)
    written = formatter.format(gap, shown, placement.mode_for(role), lang)
    endpoints = tuple(
        formatter.format(one.figure.value, figures, placement.mode_for(role), lang)
        for one in (high, low)
    )
    return Composed(
        elements=(
            Placed(
                element=derived(
                    render(
                        catalogue,
                        lang,
                        ExtremumMessage.SPREAD_BETWEEN,
                        detail=published.name,
                        value=written.value,
                        unit=written.unit,
                        high_carrier=high.label,
                        high=endpoints[0].value,
                        low_carrier=low.label,
                        low=endpoints[1].value,
                        figure_unit=endpoints[0].unit,
                        period=render_period(catalogue, lang, high.figure.period),
                    ),
                    _provenance(high.figure, published),
                ),
                role=role,
            ),
        ),
        row_ids=(high.figure.source_datapoint_id, low.figure.source_datapoint_id),
    )


# ------------------------------------------------------------------ the small decisions


def _extremum_message(direction: Direction, scope: Scope) -> str:
    """The id for this end of this kind of scope -- four sentences, never one with a hole.

    Exhaustive over both closed sets. The pairing is what R-166 is: a ranking over
    periods has its own wording and cannot be reached by a composer holding a country
    sentence and a period label.
    """
    match (direction, scope):
        case (Direction.HIGHEST, Scope.COUNTRIES):
            return ExtremumMessage.HIGHEST_COUNTRY
        case (Direction.LOWEST, Scope.COUNTRIES):
            return ExtremumMessage.LOWEST_COUNTRY
        case (Direction.HIGHEST, Scope.PERIODS):
            return ExtremumMessage.HIGHEST_PERIOD
        case (Direction.LOWEST, Scope.PERIODS):
            return ExtremumMessage.LOWEST_PERIOD
        case _:
            raise ValueError(
                f"{direction!r} over {scope!r} has no wording; a superlative the engine "
                "can compose is one the catalogue has to be able to say"
            )


def _direction_word(direction: Direction) -> str:
    """The message id for the direction a note has to name, in the reader's language."""
    match direction:
        case Direction.HIGHEST:
            return ExtremumMessage.HIGHER
        case Direction.LOWEST:
            return ExtremumMessage.LOWER


def _position_of(subject: str, placed: tuple[Candidate, ...]) -> int | None:
    """*subject*'s place in *placed*, counted from one, or ``None`` if it is not there.

    Compared through ``domain.normalise``, the engine's single fold (AD-26): a second
    comparison written here is the defect the one fold exists to prevent, and a trailing
    space between a label and the name being asked about would read as a country that is
    not in its own comparison.
    """
    folded = normalise(subject)
    for position, candidate in enumerate(placed, start=1):
        if normalise(candidate.label) == folded:
            return position
    return None


def _provenance(figure: Figure, published: PublishedDetail) -> Provenance:
    return Provenance(
        detail_id=figure.detail_id,
        period=figure.period,
        country=figure.country_id,
        source_id=published.source_id,
    )


def _pair() -> int:
    """How many candidates a spread needs: one per end of the ordering.

    Derived from ``Direction`` rather than written as a number, and not to dodge the
    scan that keeps the rule files honest. It is what the quantity actually is -- a
    spread has an endpoint at each end -- so the two cannot drift apart, and a reviewer
    reading a bare literal here would have to take on trust that it was not a threshold
    somebody chose.
    """
    return len(Direction)


def _ranks_are_computed(rule_set: RuleSet) -> bool:
    value = rule_set.value(
        CompareRule.RANK_IS_NEVER_COMPUTED.value, CompareClause.RANKS_ARE_COMPUTED.value
    )
    if not isinstance(value, bool):
        raise SelectionRuleError(
            f"{CompareRule.RANK_IS_NEVER_COMPUTED.value} value "
            f"`{CompareClause.RANKS_ARE_COMPUTED.value}` must be a yes or a no, and is "
            f"{value!r}"
        )
    return value


def _is_percent(unit: str, rule_set: RuleSet) -> bool:
    """Is *unit* one of the published spellings a percentage arrives under?

    Through the single fold, for ``format.py``'s reason: ``"% "`` failing to match ``"%"``
    would be a spread rendered in percent because of a trailing space in an export.
    """
    folded = normalise(unit)
    return any(
        folded == normalise(spelling)
        for spelling in _spellings(
            rule_set, CompareRule.SPREAD_IN_POINTS, CompareClause.PERCENT_UNITS
        )
    )


def _points_unit(rule_set: RuleSet) -> str:
    value = rule_set.value(
        CompareRule.SPREAD_IN_POINTS.value, CompareClause.POINTS_UNIT.value
    )
    if not isinstance(value, str) or not value.strip():
        raise SelectionRuleError(
            f"{CompareRule.SPREAD_IN_POINTS.value} value "
            f"`{CompareClause.POINTS_UNIT.value}` must be the published spelling of the "
            f"points unit, and is {value!r}"
        )
    return value.strip()


def _spellings(
    rule_set: RuleSet, rule: CompareRule, clause: CompareClause
) -> tuple[str, ...]:
    value = rule_set.value(rule.value, clause.value)
    if not isinstance(value, tuple):
        raise SelectionRuleError(
            f"{rule.value} value `{clause.value}` must be a list of published spellings, "
            f"not {type(value).__name__}; this composition reads its spellings from the "
            "rule files and has none of its own to fall back to"
        )
    return value
