"""Contiguity at a grain -- the run of periods a span is expected to publish.

Purity: pure, imports nothing in-project outside ``domain/``.

FR-17 asks a series to be contiguous at its grain *or to state where it is not*, and
both halves of that need the same thing: the periods a span **ought** to contain, derived
from the span rather than from the rows. A run built from the rows can only ever be
contiguous -- 2022, 2024 and 2025 with nothing between them reads as three consecutive
readings, which is exactly how a missing year closes up silently. So the expected run is
computed here, from the two endpoints alone, and the rows are matched against it.

It lives in ``domain/`` rather than beside the composer for one structural reason: a
period's successor is month, quarter and year arithmetic, and ``assemble/`` may hold no
numeric literal at all (AD-11, scanned by ``tests/test_rules.py``). Putting 12 and 4
there would either fail the build or push them into a rule file, where they would be
pretending to be reviewable decisions. They are not decisions; they are the calendar.

``Period`` owns its grain, so nothing here takes a grain argument -- ``following`` reads
it off the period it is handed, and ``periods_between`` refuses two endpoints that
disagree rather than picking one of them.
"""

from __future__ import annotations

from typing import Final

from askai.domain.period import Grain, Period

__all__ = ["MixedGrainSpan", "a_year_earlier", "following", "periods_between", "preceding"]

#: The calendar, not a rule. A year has four quarters and twelve months in every
#: jurisdiction this engine will ever answer for, and a rule file offering to change
#: that would be offering something nobody may take.
_QUARTERS_IN_A_YEAR: Final = 4
_MONTHS_IN_A_YEAR: Final = 12

#: The published spelling of a year and of a two-digit month, as ``domain/period.py``
#: parses them. Kept as format specifications rather than as reconstructed strings so
#: that "0001" and "01" cannot be produced a second way.
_YEAR_DIGITS: Final = "04d"
_MONTH_DIGITS: Final = "02d"


class MixedGrainSpan(ValueError):
    """Two endpoints at different grains were offered as one span.

    Raised rather than resolved. A span that changes grain part-way has no single
    expected run -- "2024 to 2025-Q4" could mean two years or eight quarters -- and
    choosing one of them here would be ``assemble/`` deciding a grain, which is the one
    thing FR-5 and AD-19 between them put in ``compile/``.
    """


def following(period: Period) -> Period:
    """The period immediately after *period*, at *period*'s own grain.

    Exhaustive over ``Grain`` with no fallback: a grain the engine reads is a grain it
    must be able to step through, and a default here would step a quarter as though it
    were a month on the one series nobody checked.
    """
    match period.grain:
        case Grain.YEARLY:
            return Period(_year(int(period.value) + 1))
        case Grain.QUARTERLY:
            year, quarter = period.value.split("-Q")
            index = int(quarter)
            if index < _QUARTERS_IN_A_YEAR:
                return Period(f"{year}-Q{index + 1}")
            return Period(f"{_year(int(year) + 1)}-Q1")
        case Grain.MONTHLY:
            year, month = period.value.split("-")
            index = int(month)
            if index < _MONTHS_IN_A_YEAR:
                return Period(f"{year}-{index + 1:{_MONTH_DIGITS}}")
            return Period(f"{_year(int(year) + 1)}-01")
        case _:
            raise MixedGrainSpan(
                f"{period.grain!r} has no successor here; a grain the engine reads is a "
                "grain a series has to be able to step through"
            )


def preceding(period: Period) -> Period:
    """The period immediately before *period*, at *period*'s own grain.

    The pairing a month-on-month or quarter-on-quarter change is measured against. It
    steps at the period's own grain and nowhere else, which is why a basis never has to
    carry a grain beside it: a monthly period's predecessor is the previous month, and
    that *is* what month on month means.
    """
    match period.grain:
        case Grain.YEARLY:
            return Period(_year(int(period.value) - 1))
        case Grain.QUARTERLY:
            year, quarter = period.value.split("-Q")
            index = int(quarter)
            if index > 1:
                return Period(f"{year}-Q{index - 1}")
            return Period(f"{_year(int(year) - 1)}-Q{_QUARTERS_IN_A_YEAR}")
        case Grain.MONTHLY:
            year, month = period.value.split("-")
            index = int(month)
            if index > 1:
                return Period(f"{year}-{index - 1:{_MONTH_DIGITS}}")
            return Period(f"{_year(int(year) - 1)}-{_MONTHS_IN_A_YEAR:{_MONTH_DIGITS}}")
        case _:
            raise MixedGrainSpan(
                f"{period.grain!r} has no predecessor here; a grain the engine reads is a "
                "grain a change has to be able to step back through"
            )


def a_year_earlier(period: Period) -> Period:
    """The same period one year earlier -- the pairing a year-on-year change is measured
    against, at every grain.

    A separate function from ``preceding`` because year on year is not *n* steps back: on
    a yearly series the two coincide, and on a monthly one they are eleven periods apart.
    Deriving one from the other by counting would make the coincidence look like the rule.
    """
    match period.grain:
        case Grain.YEARLY:
            return Period(_year(int(period.value) - 1))
        case Grain.QUARTERLY:
            year, quarter = period.value.split("-Q")
            return Period(f"{_year(int(year) - 1)}-Q{quarter}")
        case Grain.MONTHLY:
            year, month = period.value.split("-")
            return Period(f"{_year(int(year) - 1)}-{month}")
        case _:
            raise MixedGrainSpan(
                f"{period.grain!r} has no year-earlier pairing here; a grain the engine "
                "publishes a year-on-year column at is a grain it has to be able to pair"
            )


def periods_between(start: Period, end: Period) -> tuple[Period, ...]:
    """Every period from *start* to *end* inclusive, contiguous at their shared grain.

    The expected run, not the published one. Nothing here consults the data, so a period
    the detail never published still appears -- which is the whole point: it is what a
    gap is measured against.
    """
    if start.grain is not end.grain:
        raise MixedGrainSpan(
            f"a span runs at one grain, and {start} to {end} names {start.grain.value} "
            f"and {end.grain.value}; a series that changes grain part-way is not one"
        )
    if start.start > end.start:
        raise MixedGrainSpan(f"a span runs forwards, and {start} to {end} runs backwards")

    run = [start]
    while run[-1].start < end.start:
        run.append(following(run[-1]))
    return tuple(run)


def _year(year: int) -> str:
    """A year in the published four-digit spelling, which ``Period`` is the judge of."""
    return f"{year:{_YEAR_DIGITS}}"
