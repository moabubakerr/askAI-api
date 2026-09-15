"""``Period`` and ``Grain`` -- a period owns its grain, and nothing else may carry one.

Purity: pure, imports nothing in-project.

Measured on the published export: a datapoint is unique on ``(detail, period,
country)`` across all 8,127 rows, and the period string carries the grain with no
exceptions -- ``2025`` is yearly, ``2025-Q1`` quarterly, ``2025-01`` monthly. That is a
stronger property than a separate grain column would give, because *grain and period
cannot disagree when there is only one of them*.

So ``grain`` is a derived property here, never a field and never a constructor
argument, and a function taking both a period and a grain is a design error
(spine conventions, and the ERD note at ``docs/ARCHITECTURE-SPINE.md:484-486``).
``tests/test_domain_invariants.py`` asserts no public callable takes both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

__all__ = ["ACCEPTED_PERIOD_FORMS", "Grain", "Period", "PeriodFormatError"]


class Grain(StrEnum):
    """The publication frequency of a datapoint. Read off a ``Period``, never stored."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


#: The only period spellings the published layer uses. Named in every rejection so a
#: caller is told what would have worked, not merely that it failed.
ACCEPTED_PERIOD_FORMS: Final = ("YYYY", "YYYY-Qn", "YYYY-MM")

# `[0-9]` rather than `\d`, and `fullmatch` rather than `match`, on purpose.
#
# `\d` is Unicode-aware, so `\d{4}` accepts Arabic-Indic digits: "٢٠٢٥" would parse as
# yearly 2025 while comparing unequal to "2025". In a bilingual system that silently
# breaks the `(detail, period, country)` uniqueness the whole design rests on -- two
# spellings of one period, two rows, no error. `$` likewise matches before a trailing
# newline, so "2025\n" would be accepted while "2025 " was rejected.
_YEARLY: Final = re.compile(r"(?P<year>[0-9]{4})")
_QUARTERLY: Final = re.compile(r"(?P<year>[0-9]{4})-Q(?P<quarter>[1-4])")
_MONTHLY: Final = re.compile(r"(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])")

_LAST_DAY_OF_MONTH: Final = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class PeriodFormatError(ValueError):
    """A value was offered as a period and is not one of the published forms.

    Typed, and raised rather than defaulted: a period the engine cannot read is
    never quietly replaced with one it can.
    """

    def __init__(self, value: object) -> None:
        forms = ", ".join(ACCEPTED_PERIOD_FORMS)
        super().__init__(f"{value!r} is not a published period; accepted forms are {forms}")
        self.value = value


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    if month == 2:
        return 28
    return _LAST_DAY_OF_MONTH[month - 1]


@dataclass(frozen=True, slots=True)
class Period:
    """One published period, parsed to ``(grain, start, end)``.

    The stored state is the published string and nothing else. ``grain``, ``start``
    and ``end`` are derived, so there is no representable state in which they
    disagree with each other.
    """

    value: str

    def __post_init__(self) -> None:
        # `date` and friends are rejected here as well as by mypy: the convention is
        # "never a bare string, never a `date`", and a runtime bypass would make the
        # type-level guarantee only as good as the caller's type checking.
        if not isinstance(self.value, str):
            raise PeriodFormatError(self.value)
        if _classify(self.value) is None:
            raise PeriodFormatError(self.value)
        # Year 0000 matches the shape but has no calendar bounds, and `date(0, ...)`
        # raises. Computing the bounds here means an unconstructible period is refused
        # at construction as a `PeriodFormatError`, rather than a bare `ValueError`
        # escaping later from a property that is documented never to fail.
        try:
            _bounds(self.value)
        except ValueError as exc:
            raise PeriodFormatError(self.value) from exc

    @property
    def grain(self) -> Grain:
        """The grain, computed from the string. There is no grain field to disagree."""
        grain = _classify(self.value)
        assert grain is not None  # guaranteed by __post_init__
        return grain

    @property
    def start(self) -> date:
        """The first calendar day the period covers."""
        return _bounds(self.value)[0]

    @property
    def end(self) -> date:
        """The last calendar day the period covers, inclusive."""
        return _bounds(self.value)[1]

    def __str__(self) -> str:
        return self.value


def _classify(value: str) -> Grain | None:
    if _YEARLY.fullmatch(value):
        return Grain.YEARLY
    if _QUARTERLY.fullmatch(value):
        return Grain.QUARTERLY
    if _MONTHLY.fullmatch(value):
        return Grain.MONTHLY
    return None


def _bounds(value: str) -> tuple[date, date]:
    yearly = _YEARLY.fullmatch(value)
    if yearly:
        year = int(yearly["year"])
        return date(year, 1, 1), date(year, 12, 31)

    quarterly = _QUARTERLY.fullmatch(value)
    if quarterly:
        year = int(quarterly["year"])
        first_month = (int(quarterly["quarter"]) - 1) * 3 + 1
        last_month = first_month + 2
        return date(year, first_month, 1), date(year, last_month, _last_day(year, last_month))

    monthly = _MONTHLY.fullmatch(value)
    assert monthly is not None  # guaranteed by __post_init__
    year, month = int(monthly["year"]), int(monthly["month"])
    return date(year, month, 1), date(year, month, _last_day(year, month))
