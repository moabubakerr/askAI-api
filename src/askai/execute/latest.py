"""Resolving the deferred period forms against the published calendar (FR-8).

Purity: pure; reads ``rules/`` and is handed the periods that exist.

AD-1 leaves ``Latest`` and ``LastN`` ``Deferred`` because they are determinate requests
whose answer needs the data. This module is where they stop being deferred. It is handed
the periods a detail publishes -- never a value, never a row -- and returns the periods
to try, in the order to try them, so that the figure itself is still fetched by exact key
somewhere else (AD-3).

FR-8's rule is *the most recent actual at or before today, with a non-placeholder value*,
and the export is why each clause is there rather than being obvious: 322 rows are
future-dated, **42 of them carry an `Actual`**, and most of those are zero. "The most
recent row" and "the most recent actual at or before today" are different answers on this
data, and the first one is a placeholder zero in 2029.

Two decisions are deliberately not made here.

**The grain is not chosen.** A period-less question is bound to a grain in ``compile/``
from the detail's *declared* default (FR-5, AD-19), and arrives as ``LastN(n, grain)``.
This module filters the calendar by the grain the request already carries; when the
request carries none -- because the catalogue declares no default -- the tie between two
grains ending on the same day is settled by ``R-GRAIN-TIE-GOES-COARSER``, which is a
published rule, and never by which row happens to be newest. Deriving a default grain
from the datapoints here would be FR-5's defect and AD-19's second binder at once.

**The placeholder test is not applied here.** Whether a row carries a published reading
is a fact about the row, and reading the row is an exact-key fetch. So this module ranks
the candidates and the fetch walks them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from enum import StrEnum
from functools import cache

from askai.domain.period import Grain, Period
from askai.domain.spec import Exact, LastN, Latest, Measure, PeriodSpec, Range
from askai.rules import RuleValue, rules

__all__ = [
    "Boundary",
    "Clause",
    "FetchRule",
    "TieBreak",
    "candidate_periods",
    "future_rows_are_eligible",
    "has_happened",
    "latest_measure",
    "newest_first",
    "placeholder_rows_are_eligible",
    "readings_wanted",
    "tie_goes_coarser",
]


class FetchRule(StrEnum):
    """The rules the fetch reads. Ids, so a typo fails where the rule's clauses are known."""

    MOST_RECENT_ACTUAL = "R-LATEST-MOST-RECENT-ACTUAL"
    COMPLETED_PERIOD = "R-FETCH-LATEST-IS-A-COMPLETED-PERIOD"
    PLACEHOLDER = "R-FETCH-PLACEHOLDER-IS-NEVER-THE-LATEST"
    GRAIN_IS_BOUND_EARLIER = "R-FETCH-GRAIN-IS-BOUND-BEFORE-THE-FETCH"
    EXACT_KEY = "R-FETCH-KEY-IS-DETAIL-PERIOD-COUNTRY"
    TIE = "R-GRAIN-TIE-GOES-COARSER"


class Clause(StrEnum):
    """The clause names those rules carry."""

    BOUNDARY = "boundary"
    FUTURE_DATED_ELIGIBLE = "future_dated_eligible"
    FUTURE_ROWS_ELIGIBLE = "future_rows_eligible"
    MEASURE = "measure"
    PLACEHOLDER_ROWS_ELIGIBLE = "placeholder_rows_eligible"
    TIE_GOES_TO = "tie_goes_to"


class Boundary(StrEnum):
    """Where the line against ``today`` falls on a period, which is not a day."""

    PERIOD_END = "period-end"
    PERIOD_START = "period-start"


class TieBreak(StrEnum):
    """Which grain wins when two readings end on the same day."""

    COARSER = "coarser"
    FINER = "finer"


def _wrong_shape(rule: FetchRule, clause: Clause, value: RuleValue, wanted: str) -> str:
    return (
        f"{rule.value} clause `{clause.value}` is {type(value).__name__}, and the fetch "
        f"needs {wanted}; the clause is read here and nowhere else, so the file is what "
        "changes"
    )


def _phrase(rule: FetchRule, clause: Clause) -> str:
    value = rules().value(rule, clause)
    if not isinstance(value, str):
        raise TypeError(_wrong_shape(rule, clause, value, "a word"))
    return value


def _switch(rule: FetchRule, clause: Clause) -> bool:
    value = rules().value(rule, clause)
    if not isinstance(value, bool):
        raise TypeError(_wrong_shape(rule, clause, value, "a yes or a no"))
    return value


@cache
def latest_measure() -> Measure:
    """The measure "the latest reading" is defined on -- never a target, never a baseline.

    289 of the 322 future-dated rows are targets, and a target dated 2030 is a perfectly
    legitimate published row. It is only "the latest value" that it must never be.
    """
    return Measure(_phrase(FetchRule.MOST_RECENT_ACTUAL, Clause.MEASURE))


@cache
def future_rows_are_eligible() -> bool:
    """May a row whose period has not finished be the latest reading? (FR-8: no.)

    Both rules that state it are read, and they must agree: the definition lives with
    the latest-value rule and the boundary lives with the fetch, and a build where those
    two disagree is one where a reviewer changed one of them believing it was the only
    one.
    """
    stated = _switch(FetchRule.MOST_RECENT_ACTUAL, Clause.FUTURE_DATED_ELIGIBLE)
    at_the_boundary = _switch(FetchRule.COMPLETED_PERIOD, Clause.FUTURE_ROWS_ELIGIBLE)
    if stated is not at_the_boundary:
        raise ValueError(
            f"{FetchRule.MOST_RECENT_ACTUAL.value} says future-dated rows eligible="
            f"{stated} and {FetchRule.COMPLETED_PERIOD.value} says {at_the_boundary}; "
            "they state one decision and must state it once"
        )
    return stated


@cache
def placeholder_rows_are_eligible() -> bool:
    """May a row publishing no text be served as the latest reading? (FR-8: no.)"""
    return _switch(FetchRule.PLACEHOLDER, Clause.PLACEHOLDER_ROWS_ELIGIBLE)


@cache
def _boundary() -> Boundary:
    return Boundary(_phrase(FetchRule.COMPLETED_PERIOD, Clause.BOUNDARY))


@cache
def tie_goes_coarser() -> bool:
    """When two readings end on the same day, does the coarser grain win?

    Read from ``R-GRAIN-TIE-GOES-COARSER`` rather than restated, because the same tie is
    decided in the selection rules and deciding it twice is how a year and its own
    fourth quarter end up disagreeing about which is "the latest".
    """
    value = rules().value(FetchRule.TIE, Clause.TIE_GOES_TO)
    if not isinstance(value, str):
        raise TypeError(_wrong_shape(FetchRule.TIE, Clause.TIE_GOES_TO, value, "a word"))
    return TieBreak(value) is TieBreak.COARSER


def has_happened(period: Period, today: date) -> bool:
    """Has *period* finished at or before *today*? The whole of FR-8's date clause.

    A period is not a day, so "at or before today" has to say *which* end of it is
    compared, and the two answers differ on real rows: measured against 2026-09-30, the
    period's end excludes 322 future-dated rows and the period's start would admit 60 of
    them, 33 carrying a placeholder ``Actual``. The choice is published as data.
    """
    if future_rows_are_eligible():
        return True
    match _boundary():
        case Boundary.PERIOD_END:
            return period.end <= today
        case Boundary.PERIOD_START:
            return period.start <= today


def _coarseness(period: Period) -> int:
    """How coarse *period*'s grain is, as the published tie-break orders it.

    ``Grain`` is declared finest-first, so its own member order is the ranking; reading
    it off the enum means a grain added to the published vocabulary is ranked by where
    it is declared rather than by a table here that someone has to remember to extend.
    """
    rank = tuple(Grain).index(period.grain)
    return rank if tie_goes_coarser() else -rank


def newest_first(periods: Iterable[Period]) -> tuple[Period, ...]:
    """*periods*, most recent first, with the published tie-break applied.

    Ordered by the day the reading ends, so a year and a month are compared by what they
    actually cover rather than by their spelling. A tie -- "2025" and "2025-12" both end
    on the last day of the year -- goes the way ``R-GRAIN-TIE-GOES-COARSER`` says.
    """
    return tuple(sorted(periods, key=lambda found: (found.end, _coarseness(found)), reverse=True))


def candidate_periods(
    request: PeriodSpec, published: Sequence[Period], today: date
) -> tuple[Period, ...]:
    """The periods to try for *request*, in the order to try them.

    *published* is the calendar the detail actually publishes in the scope being asked
    about; nothing here invents a period that is not in it, so a resolved period is
    always a period that exists.

    Exhaustive over ``PeriodSpec``. A member added later fails here rather than falling
    through to an empty tuple, which would be "no data" wearing an omission's clothes.
    """
    match request:
        case Exact(period=named):
            return (named,) if named in set(published) else ()
        case Range(start=start, end=end):
            return newest_first(
                found
                for found in published
                if found.grain is start.grain
                and start.start <= found.start
                and found.end <= end.end
            )
        case Latest():
            return newest_first(found for found in published if has_happened(found, today))
        case LastN(grain=wanted):
            return newest_first(
                found
                for found in published
                if found.grain is wanted and has_happened(found, today)
            )
        case _:
            raise TypeError(
                f"{type(request).__name__} is not a PeriodSpec member, or is one that "
                "candidate_periods has not been told about; say which periods it asks "
                "for before it can be resolved against the data"
            )


def readings_wanted(request: PeriodSpec) -> int | None:
    """How many readings *request* asks for, or ``None`` for "every candidate".

    ``LastN`` carries its own count -- "the last five years" -- and the other forms ask
    for one reading or for a whole named span.
    """
    match request:
        case LastN(n=count):
            return count
        case Exact() | Latest():
            return 1
        case _:
            return None
