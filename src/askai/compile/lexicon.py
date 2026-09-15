"""The defaults and words binding reads -- every one of them loaded from ``rules/``.

Purity: pure once the rule files have loaded.

AD-11 says a reader-affecting constant is versioned data, and ``tests/test_rules.py``
scans this package for the literal that would make that decorative. This module is the
one door: it turns a rule clause into the typed thing a binder wants -- a ``Measure``, a
``Grain``, a ``CountryScope``, a set of phrases -- and every binder reaches a default
through it rather than writing one down.

Two things are deliberate here.

**The rule ids and clause names are enums, not scattered strings.** They are addresses,
not decisions, and an address that is mistyped should fail at the one place that knows
what the rule carries -- ``RuleSet.value`` names the clauses a rule does have.

**Nothing widens a clause's type.** A clause that is not the shape the caller needs
raises, naming the rule, the clause and both shapes. The alternative -- coercing, or
falling back -- is a reader-affecting constant living in code again, arriving through
the door built to keep it out.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from functools import cache

from askai.domain.period import Grain
from askai.domain.scope import CountryScope, DeclaredBenchmarks, National
from askai.domain.spec import Measure, Operation
from askai.rules import RuleValue, rules

__all__ = [
    "BindingRule",
    "Clause",
    "benchmark_words",
    "comparison_words",
    "count_words",
    "default_country_scope",
    "default_measure",
    "default_operation",
    "default_period_is_latest",
    "grain_words",
    "latest_words",
    "measure_words",
    "month_numbers",
    "open_range_ends_at_today",
    "period_nouns",
    "period_prefixes",
    "precedence_order",
    "quarter_numbers",
    "range_from_words",
    "range_to_words",
    "readings_for_latest",
    "relative_back_words",
]


class BindingRule(StrEnum):
    """The rules binding reads. Ids, so a typo fails at load rather than at a reader."""

    PRECEDENCE = "R-BIND-PRECEDENCE"
    DEFAULT_COUNTRY_SCOPE = "R-BIND-DEFAULT-COUNTRY-SCOPE"
    DEFAULT_MEASURE = "R-BIND-DEFAULT-MEASURE"
    DEFAULT_OPERATION = "R-BIND-DEFAULT-OPERATION"
    PERIODLESS_IS_LATEST = "R-BIND-PERIODLESS-IS-LATEST"
    GRAIN_FROM_DECLARED_DEFAULT = "R-BIND-GRAIN-FROM-DECLARED-DEFAULT"
    LATEST_WORDS = "R-BIND-LATEST-WORDS"
    GRAIN_WORDS = "R-BIND-GRAIN-WORDS"
    MEASURE_WORDS = "R-BIND-MEASURE-WORDS"
    BENCHMARK_WORDS = "R-BIND-BENCHMARK-WORDS"
    MONTH_NAMES = "R-BIND-MONTH-NAMES"
    QUARTER_WORDS = "R-BIND-QUARTER-WORDS"
    PERIOD_NOUNS = "R-BIND-PERIOD-NOUNS"
    RELATIVE_PERIOD_WORDS = "R-BIND-RELATIVE-PERIOD-WORDS"
    COUNT_WORDS = "R-BIND-COUNT-WORDS"
    PERIOD_RANGE_WORDS = "R-BIND-PERIOD-RANGE-WORDS"
    OPEN_RANGE_END = "R-BIND-OPEN-RANGE-ENDS-AT-TODAY"
    PERIOD_PREFIXES = "R-BIND-PERIOD-PREFIXES"


class Clause(StrEnum):
    """The clause names those rules carry."""

    BACK_WORDS = "back_words"
    COMPARISON_WORDS = "comparison_words"
    COUNTS = "counts"
    END = "end"
    FROM_WORDS = "from_words"
    MEASURE = "measure"
    MONTHS = "months"
    OPERATION = "operation"
    ORDER = "order"
    PERIOD = "period"
    PREFIXES = "prefixes"
    QUARTERS = "quarters"
    READINGS = "readings"
    SCOPE = "scope"
    TO_WORDS = "to_words"
    WORDS = "words"


class ScopeName(StrEnum):
    """The scope shapes a rule may name. Closed, because ``CountryScope`` is (AD-5).

    ``Named`` is absent on purpose: a named country set comes from the reader naming
    countries, and a *default* naming countries would be a country filter arriving from
    configuration -- the one thing AD-5 exists to make unrepresentable.
    """

    NATIONAL = "national"
    DECLARED_BENCHMARKS = "declared-benchmarks"


class PeriodDefault(StrEnum):
    """The period a rule may default to. One member today, and it is deferred, not bound."""

    LATEST = "latest"


class OpenRangeEnd(StrEnum):
    """What closes a range whose end the reader left open. Closed, and closed for a reason.

    ``TODAY`` is the only member a pure layer can honour: ``today`` is an input to
    compiling, so an open range compiles to the same span on every run. The obvious
    alternative -- the newest published period -- is a data read, which AD-1 puts out of
    ``compile/``'s reach entirely, so it is not a member that could be selected here.
    """

    TODAY = "today"


def _phrase(rule: BindingRule, clause: Clause) -> str:
    value = rules().value(rule, clause)
    if not isinstance(value, str):
        raise TypeError(_wrong_shape(rule, clause, value, "a word"))
    return value


def _phrases(rule: BindingRule, clause: str) -> frozenset[str]:
    value = rules().value(rule, clause)
    if not isinstance(value, tuple):
        raise TypeError(_wrong_shape(rule, clause, value, "a list of words"))
    return frozenset(value)


def _numbers(rule: BindingRule, clause: Clause) -> Mapping[str, int]:
    value = rules().value(rule, clause)
    if not isinstance(value, Mapping):
        raise TypeError(_wrong_shape(rule, clause, value, "a table of words to numbers"))
    return value


def _count(rule: BindingRule, clause: Clause) -> int:
    value = rules().value(rule, clause)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(_wrong_shape(rule, clause, value, "a count"))
    return value


def _wrong_shape(rule: BindingRule, clause: str, value: RuleValue, wanted: str) -> str:
    return (
        f"{rule.value} clause `{clause}` is {type(value).__name__}, and binding needs "
        f"{wanted}; the clause is read here and nowhere else, so the file is what changes"
    )


@cache
def precedence_order() -> tuple[str, ...]:
    """AD-19's four steps, in order, as the catalogue states them."""
    value = rules().value(BindingRule.PRECEDENCE, Clause.ORDER)
    if not isinstance(value, tuple):
        raise TypeError(_wrong_shape(BindingRule.PRECEDENCE, Clause.ORDER, value, "an order"))
    return value


@cache
def default_country_scope() -> CountryScope:
    """The scope a question naming no country is about (FR-10, FR-11b)."""
    match ScopeName(_phrase(BindingRule.DEFAULT_COUNTRY_SCOPE, Clause.SCOPE)):
        case ScopeName.NATIONAL:
            return National()
        case ScopeName.DECLARED_BENCHMARKS:
            return DeclaredBenchmarks()


@cache
def default_measure() -> Measure:
    """The measure a question naming none is asking for."""
    return Measure(_phrase(BindingRule.DEFAULT_MEASURE, Clause.MEASURE))


@cache
def default_operation() -> Operation:
    """The operation a question nothing has classified carries (AD-22: no model here)."""
    return Operation(_phrase(BindingRule.DEFAULT_OPERATION, Clause.OPERATION))


@cache
def default_period_is_latest() -> bool:
    """Does a question naming no period ask for the latest reading?"""
    return PeriodDefault(_phrase(BindingRule.PERIODLESS_IS_LATEST, Clause.PERIOD)) is (
        PeriodDefault.LATEST
    )


@cache
def readings_for_latest() -> int:
    """How many readings "the latest, at this grain" asks for."""
    return _count(BindingRule.GRAIN_FROM_DECLARED_DEFAULT, Clause.READINGS)


@cache
def latest_words() -> frozenset[str]:
    """The phrases that name the latest reading rather than a period."""
    return _phrases(BindingRule.LATEST_WORDS, Clause.WORDS)


@cache
def benchmark_words() -> frozenset[str]:
    """The phrases that ask for the detail's own declared benchmark set."""
    return _phrases(BindingRule.BENCHMARK_WORDS, Clause.WORDS)


@cache
def grain_words() -> Mapping[Grain, frozenset[str]]:
    """Each grain and the phrases that name it, keyed by the clause the grain names.

    Derived from ``Grain`` rather than listed, so a grain added to the domain fails here
    -- naming the clause the file is missing -- instead of silently having no words.
    """
    return {value: _phrases(BindingRule.GRAIN_WORDS, f"{value.value}_words") for value in Grain}


@cache
def measure_words() -> Mapping[Measure, frozenset[str]]:
    """Each measure and the phrases that name it, keyed the same way and for the same reason."""
    return {
        value: _phrases(BindingRule.MEASURE_WORDS, f"{value.value}_words") for value in Measure
    }


@cache
def month_numbers() -> Mapping[str, int]:
    """Month names, in both languages, to the month they name."""
    return _numbers(BindingRule.MONTH_NAMES, Clause.MONTHS)


@cache
def quarter_numbers() -> Mapping[str, int]:
    """Quarter phrases, in both languages, to the quarter they name."""
    return _numbers(BindingRule.QUARTER_WORDS, Clause.QUARTERS)


@cache
def period_nouns() -> Mapping[Grain, frozenset[str]]:
    """Each interval and the nouns a reader counts periods in, keyed by the grain.

    Derived from ``Grain`` for the same reason ``grain_words`` is: a grain added to the
    domain fails here, naming the clause the file is missing, rather than silently
    having no nouns and so no relative expression.
    """
    return {value: _phrases(BindingRule.PERIOD_NOUNS, f"{value.value}_nouns") for value in Grain}


@cache
def relative_back_words() -> frozenset[str]:
    """The words that point a period noun backwards from now -- "last", "past", "الماضية"."""
    return _phrases(BindingRule.RELATIVE_PERIOD_WORDS, Clause.BACK_WORDS)


@cache
def count_words() -> Mapping[str, int]:
    """Counts written in words, in both languages, to the number they name."""
    return _numbers(BindingRule.COUNT_WORDS, Clause.COUNTS)


@cache
def range_from_words() -> frozenset[str]:
    """The words that open a span -- "from", "since", "منذ"."""
    return _phrases(BindingRule.PERIOD_RANGE_WORDS, Clause.FROM_WORDS)


@cache
def range_to_words() -> frozenset[str]:
    """The words that close a span -- "to", "until", "إلى"."""
    return _phrases(BindingRule.PERIOD_RANGE_WORDS, Clause.TO_WORDS)


@cache
def comparison_words() -> frozenset[str]:
    """The words that make two named periods a comparison rather than a span (FR-23)."""
    return _phrases(BindingRule.PERIOD_RANGE_WORDS, Clause.COMPARISON_WORDS)


@cache
def period_prefixes() -> frozenset[str]:
    """The one-letter conjunctions a reader writes joined to a period -- "و2025"."""
    return _phrases(BindingRule.PERIOD_PREFIXES, Clause.PREFIXES)


@cache
def open_range_ends_at_today() -> bool:
    """Does a range whose end the reader left open end at the period containing ``today``?"""
    return OpenRangeEnd(_phrase(BindingRule.OPEN_RANGE_END, Clause.END)) is OpenRangeEnd.TODAY
