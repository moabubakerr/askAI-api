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
    "OperationClause",
    "OperationRule",
    "bare_subject_frames",
    "bare_subject_is_the_whole_question",
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
    "multi_reading_is_a_series",
    "open_range_ends_at_today",
    "operation_order",
    "operation_words",
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


class OperationRule(StrEnum):
    """The rules the operation classifier reads. Ids, so a typo fails at load.

    Separate from ``BindingRule`` because they are a separate file and a separate
    decision: ``BIND`` says how a field reaches its value once something has named one,
    and ``OP`` says what the question's *verb* named. Keeping them apart is what let the
    operation tables be added without editing a rule file the rest of binding depends on.
    """

    WORDS = "R-OP-WORDS"
    PRECEDENCE = "R-OP-PRECEDENCE"
    BARE_SUBJECT = "R-OP-BARE-SUBJECT-IS-A-DEFINITION"
    BARE_SUBJECT_IS_THE_WHOLE_QUESTION = "R-OP-A-BARE-SUBJECT-IS-THE-WHOLE-QUESTION"
    MULTI_READING_IS_A_SERIES = "R-OP-SERIES-FROM-A-MULTI-READING-REQUEST"


class OperationClause(StrEnum):
    """The clause names those rules carry."""

    ENABLED = "enabled"
    FRAMES = "frames"
    ORDER = "order"


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


type _Rule = BindingRule | OperationRule


def _phrase(rule: _Rule, clause: Clause) -> str:
    value = rules().value(rule, clause)
    if not isinstance(value, str):
        raise TypeError(_wrong_shape(rule, clause, value, "a word"))
    return value


def _flag(rule: _Rule, clause: OperationClause) -> bool:
    """A switch clause, read as the toggle it is and never as a truthy value.

    ``bool`` before ``int`` in the check because ``bool`` *is* an ``int`` in Python, and a
    clause written as ``0`` would otherwise arrive here as a switch that is off -- a
    reader-affecting decision made by a coincidence of the type system.
    """
    value = rules().value(rule, clause)
    if not isinstance(value, bool):
        raise TypeError(_wrong_shape(rule, clause, value, "a switch"))
    return value


def _phrases(rule: _Rule, clause: str) -> frozenset[str]:
    value = rules().value(rule, clause)
    if not isinstance(value, tuple):
        raise TypeError(_wrong_shape(rule, clause, value, "a list of words"))
    return frozenset(value)


def _numbers(rule: _Rule, clause: Clause) -> Mapping[str, int]:
    value = rules().value(rule, clause)
    if not isinstance(value, Mapping):
        raise TypeError(_wrong_shape(rule, clause, value, "a table of words to numbers"))
    return value


def _count(rule: _Rule, clause: Clause) -> int:
    value = rules().value(rule, clause)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(_wrong_shape(rule, clause, value, "a count"))
    return value


def _wrong_shape(rule: _Rule, clause: str, value: RuleValue, wanted: str) -> str:
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


# ------------------------------------------------------------------ the operation tables


@cache
def operation_order() -> tuple[Operation, ...]:
    """The operations, in the order their phrase tables are consulted (AD-17).

    Checked against ``Operation`` rather than merely read, and checked in both
    directions: an operation missing from the order would silently never be classified,
    and a name in the order that is not an operation is a typo the file should fail on.
    """
    value = rules().value(OperationRule.PRECEDENCE, OperationClause.ORDER)
    if not isinstance(value, tuple):
        raise TypeError(
            _wrong_shape(OperationRule.PRECEDENCE, OperationClause.ORDER, value, "an order")
        )
    order = tuple(Operation(name) for name in value)
    if sorted(order) != sorted(Operation):
        missing = ", ".join(sorted(absent.value for absent in set(Operation) - set(order)))
        raise ValueError(
            f"{OperationRule.PRECEDENCE.value} clause `{OperationClause.ORDER.value}` "
            f"does not name every operation exactly once; missing: {missing or 'nothing'}"
            " -- an operation absent from the order is one nothing can ever classify"
        )
    return order


@cache
def operation_words() -> Mapping[Operation, frozenset[str]]:
    """Each operation and the phrases that name it, in the order they are consulted.

    Keyed by ``Operation`` and built from ``operation_order``, so an operation added to
    the domain fails here -- naming the clause the file is missing -- rather than quietly
    having no words and never being classified. The insertion order *is* the precedence a
    caller walking the mapping gets, which is why the order is data and not a sort.
    """
    return {
        value: _phrases(OperationRule.WORDS, f"{value.value}_words")
        for value in operation_order()
    }


@cache
def bare_subject_frames() -> frozenset[str]:
    """The frames that ask what the subject *is* -- "what is", "ما هو".

    A definition only when the question names no period; ``R-OP-BARE-SUBJECT-IS-A-
    DEFINITION`` says so and ``compile.operations`` is where the period is consulted.
    """
    return _phrases(OperationRule.BARE_SUBJECT, OperationClause.FRAMES)


@cache
def bare_subject_is_the_whole_question() -> bool:
    """Must a bare-subject frame lead straight into the subject, and the subject end it?

    ``R-OP-A-BARE-SUBJECT-IS-THE-WHOLE-QUESTION``. The frames rule says *which* frames
    ask what a subject is; this says what makes the subject **bare**, which until it
    existed was asserted by nothing and let *"what is the target for inflation"* compile
    to a definition.
    """
    return _flag(OperationRule.BARE_SUBJECT_IS_THE_WHOLE_QUESTION, OperationClause.ENABLED)


@cache
def multi_reading_is_a_series() -> bool:
    """Is a request for more than one reading, by itself, a request for a series?"""
    return _flag(OperationRule.MULTI_READING_IS_A_SERIES, OperationClause.ENABLED)
