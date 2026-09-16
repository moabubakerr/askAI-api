"""A series over a span, and the gaps stated rather than closed up.

Purity: pure. Every word comes from ``messages/``; every figure through the single
``Formatter``; the contiguity rules from ``rules/``.

Stories 3.2 and 3.3 are one composer because a gap is content, not an omission: a series
that says *"2019, 2020, 2022"* and a series that says *"2019, 2020, no value published
for 2021, 2022"* are different answers, and only the second is true. Splitting them would
make the first the default and the second an enhancement.

**The expected run comes from the span, never from the rows.** ``domain/calendar.py``
builds every period the span covers at its grain, and the readings are matched against
it. A run assembled from the rows that exist is contiguous by construction, so the
missing quarter does not go missing loudly -- it goes missing silently, which is exactly
the defect FR-17 names.

**No point is a headline.** Every element takes ``Role.SERIES``; nothing here names a
``FormatMode``, so the role tables write the whole run at evidence precision and place it
in the explore lens, and ``R-SERIES-HAS-NO-HEADLINE`` is enforced by there being no route
to a headline role rather than by nobody taking one.

**A gap has no row, and that is the point.** ``ComposedSeries`` therefore keeps the
row-backed points and the stated gaps apart: a reading resolves against the published
layer and is admitted through ``assemble.provenance.admit`` like every other element,
while a gap's reference names a period the detail publishes nothing for and by definition
cannot resolve. Running it through the closed-world check would refuse it and leave a
shorter series that reads exactly like a complete one -- AD-7's own failure mode arriving
through AD-7. So the two are carried separately and both are returned; a caller cannot
take the readings without stepping over the gaps.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.elements import absent, measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.calendar import periods_between
from askai.domain.period import Period
from askai.domain.spec import Range
from askai.execute.value import Figure, Reading
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.presentation import PublishedDetail
from askai.rules import RuleSet

__all__ = [
    "ComposedSeries",
    "NotASeries",
    "PlacedPoint",
    "Series",
    "SeriesClause",
    "SeriesComposition",
    "SeriesError",
    "SeriesMessage",
    "SeriesPoint",
    "SeriesRefusal",
    "SeriesRule",
    "SeriesTables",
    "series_composition",
    "series_over",
]


class SeriesRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    A_GAP_IS_STATED = "R-SERIES-A-GAP-IS-STATED"
    IS_ONE_GRAIN = "R-SERIES-IS-ONE-GRAIN"
    HAS_NO_HEADLINE = "R-SERIES-HAS-NO-HEADLINE"


class SeriesClause(StrEnum):
    """The clause names read off those rules."""

    SKIPPING_A_PERIOD_IS_ALLOWED = "skipping_a_period_is_allowed"
    GAPS_APPEAR_IN_EVERY_LENS = "gaps_appear_in_every_lens"
    MIXED_GRAIN_IS_ALLOWED = "mixed_grain_is_allowed"
    COLLAPSES_TO_A_HEADLINE = "collapses_to_a_headline"


class SeriesMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    POINT = "series.point"
    GAP = "series.gap"
    GAPS_NOTE = "series.gaps_note"
    NOT_A_SERIES = "series.not_a_series"
    LIST_SEPARATOR = "scope.list_separator"
    """The same separator the scope element uses. Deliberately the same id: which mark
    separates a list, and whether a space follows it, is one per-language editorial
    decision and having two of them is how the two halves of an answer come to disagree."""


class SeriesRefusal(StrEnum):
    """Why a span cannot be answered as a series at all. A closed set, never a sentence."""

    DETAIL_PUBLISHES_TEXT = "detail-publishes-text-not-figures"
    """One of the 21 details publishing a rating, a tier or a band across 126 rows. A run
    of those is not a series -- there is no movement to show -- so it is refused clearly
    rather than answered as a span of gaps, which would say the data is missing when it
    is present and is simply not a number."""


class SeriesError(ValueError):
    """A series was asked for over readings that cannot form one.

    Raised rather than repaired. A reading at the wrong grain and a reading outside the
    span are both callers handing over rows the span did not ask for, and quietly
    dropping either is how a series stops matching the question it answers.
    """


# ------------------------------------------------------------------------- the series


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """One period of the span, and the reading at it -- or ``None`` where there is none."""

    period: Period
    figure: Figure | None

    @property
    def is_a_gap(self) -> bool:
        return self.figure is None


@dataclass(frozen=True, slots=True)
class Series:
    """A span, and one point per period it covers, oldest first.

    Oldest first because a series is read forwards: ``execute/`` returns its readings
    newest first, which is the right order for *"what is the latest"* and the wrong one
    for *"show me the shape"*.
    """

    span: Range
    points: tuple[SeriesPoint, ...]

    def __post_init__(self) -> None:
        expected = periods_between(self.span.start, self.span.end)
        covered = tuple(point.period for point in self.points)
        if covered != expected:
            raise SeriesError(
                f"a series covers every period of its span at its grain: {self.span.start} "
                f"to {self.span.end} expects {len(expected)} points and this one covers "
                f"{len(covered)}; a run built from the rows that exist is contiguous by "
                "construction, which is how a missing period closes up (FR-17)"
            )

    @property
    def gaps(self) -> tuple[Period, ...]:
        """Every period of the span the detail publishes no reading for."""
        return tuple(point.period for point in self.points if point.is_a_gap)

    @property
    def readings(self) -> tuple[Figure, ...]:
        return tuple(point.figure for point in self.points if point.figure is not None)

    @property
    def is_contiguous(self) -> bool:
        return not self.gaps


def series_over(span: Range, readings: Iterable[Reading]) -> Series:
    """The series *span* asks for, with *readings* placed into it and the rest as gaps.

    *readings* is whatever ``execute/`` fetched, in whatever order. Every one of them must
    sit at the span's grain and inside the span: a reading at another grain is FR-6's
    forbidden substitution arriving as a data shape, and a reading outside the span is a
    point the question did not ask for.
    """
    expected = periods_between(span.start, span.end)
    placed: dict[Period, Figure] = {}
    for reading in readings:
        if reading.period.grain is not span.start.grain:
            raise SeriesError(
                f"{reading.period} is {reading.period.grain.value} and the span runs at "
                f"{span.start.grain.value}; a series runs at one grain and no adjacent "
                "grain is ever substituted (FR-6, R-SERIES-IS-ONE-GRAIN)"
            )
        if reading.period not in set(expected):
            raise SeriesError(
                f"{reading.period} is outside the span {span.start} to {span.end}; a "
                "reading the question did not ask for is not silently dropped here"
            )
        placed[reading.period] = reading.figure
    return Series(
        span=span,
        points=tuple(
            SeriesPoint(period=period, figure=placed.get(period)) for period in expected
        ),
    )


# ------------------------------------------------------------------------- the tables


@dataclass(frozen=True, slots=True)
class SeriesTables:
    """The series rules, read through the rule set they live in."""

    rule_set: RuleSet

    def may_skip_a_period(self) -> bool:
        """FR-17's prohibition, read rather than assumed. Expected to be ``False``."""
        return self._switch(SeriesRule.A_GAP_IS_STATED, SeriesClause.SKIPPING_A_PERIOD_IS_ALLOWED)

    def gaps_appear_in_every_lens(self) -> bool:
        """FR-59d: brevity removes depth, never the statement that something is missing."""
        return self._switch(SeriesRule.A_GAP_IS_STATED, SeriesClause.GAPS_APPEAR_IN_EVERY_LENS)

    def may_mix_grains(self) -> bool:
        return self._switch(SeriesRule.IS_ONE_GRAIN, SeriesClause.MIXED_GRAIN_IS_ALLOWED)

    def collapses_to_a_headline(self) -> bool:
        """FR-16: a series has no single headline, so this is expected to be ``False``."""
        return self._switch(SeriesRule.HAS_NO_HEADLINE, SeriesClause.COLLAPSES_TO_A_HEADLINE)

    def _switch(self, rule: SeriesRule, clause: SeriesClause) -> bool:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, bool):
            raise SeriesError(
                f"{rule.value} value `{clause.value}` must be a yes or a no, not "
                f"{type(value).__name__}; the series composition reads its rules from the "
                "rule files and has none of its own to fall back to"
            )
        return value


# --------------------------------------------------------------------- the composition


@dataclass(frozen=True, slots=True)
class PlacedPoint:
    """One composed point of the series, and whether it states a reading or a gap."""

    placed: Placed
    period: Period
    is_a_gap: bool


@dataclass(frozen=True, slots=True)
class ComposedSeries:
    """The whole run, composed, with the readings and the stated gaps kept apart.

    ``elements`` is the run in reading order and is what a reader sees. ``row_backed`` and
    ``gaps`` are the same elements split by whether a published row stands behind them,
    because only the first kind can be resolved against the published layer -- see the
    module docstring. Both are returned, always, so a caller that wants only the readings
    has to step over the gaps in a line a reviewer can see.

    ``gap_note`` is FR-59d's clause. The points all take the ``series`` role, which the
    lens mapping shows in explore alone -- so in the executive lens a series answer would
    carry no statement that anything was missing at all. The note says it once, in the
    ``note`` role, which both lenses show. It is not a second copy of the gaps for the
    same reader: the two never appear together, because no lens shows both roles.
    """

    points: tuple[PlacedPoint, ...]
    gap_note: Placed | None = None

    @property
    def elements(self) -> tuple[Placed, ...]:
        return tuple(point.placed for point in self.points)

    @property
    def row_backed(self) -> tuple[Placed, ...]:
        """The points a published row stands behind -- admitted like any other element."""
        return tuple(point.placed for point in self.points if not point.is_a_gap)

    @property
    def gaps(self) -> tuple[Placed, ...]:
        """The stated absences, the note included. Content (FR-45), never dropped (FR-17)."""
        stated = [point.placed for point in self.points if point.is_a_gap]
        if self.gap_note is not None:
            stated.append(self.gap_note)
        return tuple(stated)

    @property
    def gap_periods(self) -> tuple[Period, ...]:
        return tuple(point.period for point in self.points if point.is_a_gap)


@dataclass(frozen=True, slots=True)
class NotASeries:
    """The span cannot be answered as a series, and this is what the reader is told."""

    reason: SeriesRefusal
    statement: str


#: What composing a series reaches. Closed, so a caller that handles the run and forgets
#: the refusal does not type-check.
type SeriesComposition = ComposedSeries | NotASeries


def series_composition(
    series: Series,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: SeriesTables,
    lang: Lang,
    country_id: str | None,
    publishes_a_figure: bool,
) -> SeriesComposition:
    """Compose *series* into placed elements, one per period, gaps included.

    *publishes_a_figure* has no default and never will. 21 details publish a rating or a
    band rather than a number across 126 rows, and a run of those is not a series; the
    caller knows which kind of detail it holds and has to say so, because the alternative
    -- inferring it from an empty run -- would report a present-but-textual indicator as
    a span of missing data.

    *country_id* is ``None`` for national scope, which is the *absence* of a country
    (AD-5) and not a blank to be compared against.
    """
    if not publishes_a_figure:
        return NotASeries(
            reason=SeriesRefusal.DETAIL_PUBLISHES_TEXT,
            statement=render(
                catalogue, lang, SeriesMessage.NOT_A_SERIES.value, detail=published.name
            ),
        )
    _check_the_rules_still_say_what_this_composer_does(series, tables)

    role = Role.SERIES
    mode = placement.mode_for(role)
    shown = PublishedFormat(unit=published.unit, spec=published.value_format)
    composed: list[PlacedPoint] = []
    for point in series.points:
        provenance = Provenance(
            detail_id=published.detail_id,
            period=point.period,
            country=country_id if point.figure is None else point.figure.country_id,
            source_id=published.source_id,
        )
        period = render_period(catalogue, lang, point.period)
        if point.figure is None:
            content = render(catalogue, lang, SeriesMessage.GAP.value, period=period)
            element = absent(content, provenance)
        else:
            written = formatter.format(point.figure.value, shown, mode, lang)
            content = render(
                catalogue,
                lang,
                SeriesMessage.POINT.value,
                period=period,
                value=written.value,
                unit=written.unit,
            )
            element = measured(content, provenance)
        composed.append(
            PlacedPoint(
                placed=Placed(element=element, role=role),
                period=point.period,
                is_a_gap=point.is_a_gap,
            )
        )
    return ComposedSeries(
        points=tuple(composed),
        gap_note=_gap_note(series, published, catalogue, tables, lang, country_id),
    )


def _gap_note(
    series: Series,
    published: PublishedDetail,
    catalogue: Catalogue,
    tables: SeriesTables,
    lang: Lang,
    country_id: str | None,
) -> Placed | None:
    """One ``note`` naming every missing period, so the gaps survive the shortest lens.

    ``None`` when the run is contiguous: a note saying nothing is missing is noise on the
    common case, and FR-59d asks for the gaps to appear in both lenses, not for a clean
    bill of health to.
    """
    if not series.gaps or not tables.gaps_appear_in_every_lens():
        return None
    separator = render(catalogue, lang, SeriesMessage.LIST_SEPARATOR.value)
    content = render(
        catalogue,
        lang,
        SeriesMessage.GAPS_NOTE.value,
        periods=separator.join(
            render_period(catalogue, lang, period) for period in series.gaps
        ),
    )
    return Placed(
        element=absent(
            content,
            Provenance(
                detail_id=published.detail_id,
                # The first missing period: the note is about the span's absences, and a
                # reference has to name one period, so it names the first thing absent
                # rather than a period that is present and would misdescribe it.
                period=series.gaps[0],
                country=country_id,
                source_id=published.source_id,
            ),
        ),
        role=Role.NOTE,
    )


def _check_the_rules_still_say_what_this_composer_does(
    series: Series, tables: SeriesTables
) -> None:
    """Refuse to compose where the published rules contradict what is about to happen.

    Not decoration. Each of the three switches states something this function then does
    unconditionally -- every period placed, one grain, no headline -- and a build where
    the file says otherwise is a build where someone edited the rule believing the code
    would follow it. Failing here is how they find out it does not.
    """
    if tables.may_skip_a_period() and series.gaps:
        raise SeriesError(
            f"{SeriesRule.A_GAP_IS_STATED.value} now allows a period to be skipped, and "
            "this composer states every gap; a series that may skip is a different "
            "composition, not a flag on this one"
        )
    if tables.may_mix_grains():
        raise SeriesError(
            f"{SeriesRule.IS_ONE_GRAIN.value} now allows a mixed-grain series, which this "
            "composer cannot build: its expected run is derived from one grain"
        )
    if tables.collapses_to_a_headline():
        raise SeriesError(
            f"{SeriesRule.HAS_NO_HEADLINE.value} now allows a series to collapse to a "
            "headline; every element here takes the series role, so the file and the "
            "composer disagree about what a series is"
        )
