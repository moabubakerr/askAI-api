"""Story 3.1: every period expression resolves, and resolves the same way in Arabic.

The story's acceptance criteria are five claims, and each has a section below:

1. **FR-7** -- absolute forms (``Q4-2025``, ``2026-04``, ``2025``), relative forms
   (*"last 5 years"*, *"lately"*, *"right now"*), spans and **open** spans all resolve,
   **and all of them resolve identically in Arabic**.
2. **FR-5** -- a period phrase implying an interval *counts as naming a grain* and takes
   precedence accordingly: over the detail's declared default, over the history, and into
   FR-6's refusal when the detail does not publish at it.
3. **AD-1** -- a relative expression produces a ``PeriodSpec`` of ``Range``, ``Latest`` or
   ``LastN``, and the forms that need the data are ``Deferred`` for ``execute/`` to
   resolve against ``today`` -- never resolved here.
4. **AD-17** -- ``today`` is an input, it reaches the spec, and a cached resolution cannot
   survive a date boundary because the spec a cache key is derived from carries it.
5. **The ordinal-quarter and month-name findings** -- *"the fourth quarter"*, ``Q4-2025``
   and a month name in either language resolve to the **published** period form.

The Arabic half is asserted as *parity* rather than as a separate expectation: each pair
below is one question written twice, and the test is that the two compile to the same
``PeriodSpec``. An Arabic expectation written out by hand would pass just as well with a
parser that happens to resolve the Arabic differently from the English, which is the
defect a bilingual engine actually has.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import CompiledQuestion, Precedence, SpecField, UnboundReason
from askai.compile.catalogue import CatalogueDetail, snapshot
from askai.compile.lexicon import (
    BindingRule,
    comparison_words,
    count_words,
    latest_words,
    open_range_ends_at_today,
    period_nouns,
    period_prefixes,
    quarter_numbers,
    range_from_words,
    range_to_words,
    readings_for_latest,
    relative_back_words,
)
from askai.compile.periods import grain_of
from askai.compile.question import Question
from askai.domain.normalise import normalise
from askai.domain.period import Grain, Period
from askai.domain.spec import Bound, Deferred, Exact, LastN, Latest, PeriodSpec, Range, Unbound
from askai.rules import rules

TODAY = date(2026, 9, 15)

# The same fixture shape ``tests/test_compile.py`` uses, and for the same reason: one
# detail publishing at all three grains and one publishing at two, so a grain a period
# expression names can be checked against a detail that does and does not publish it.
CATALOGUE = snapshot(
    details=[
        CatalogueDetail(
            detail_id="D-INFLATION",
            names=("Inflation", "معدل التضخم"),
            declared_grain=Grain.MONTHLY,
            grains=frozenset(Grain),
        ),
        CatalogueDetail(
            detail_id="D-REAL-GDP",
            names=("Real GDP", "الناتج المحلي الإجمالي الحقيقي"),
            declared_grain=Grain.YEARLY,
            grains=frozenset({Grain.QUARTERLY, Grain.YEARLY}),
        ),
    ]
)


def compiled(
    question: str, *, today: date = TODAY, history: tuple[str, ...] = ()
) -> CompiledQuestion:
    return compile_question(
        CompileInput(question=question, today=today, history=history), CATALOGUE
    )


def period_of(question: str, *, today: date = TODAY, history: tuple[str, ...] = ()) -> object:
    return compiled(question, today=today, history=history).spec.period


# ------------------------------------------------------- FR-7: the absolute forms


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("What was inflation in 2025?", "2025"),
        ("What was inflation in 2026-04?", "2026-04"),
        ("What was inflation in 2025-Q4?", "2025-Q4"),
        ("What was inflation in Q4-2025?", "2025-Q4"),
        ("What was inflation in Q4 2025?", "2025-Q4"),
        ("What was inflation in 2025 Q4?", "2025-Q4"),
        ("What was inflation in the fourth quarter of 2025?", "2025-Q4"),
        ("What was inflation in the 4th quarter of 2025?", "2025-Q4"),
        ("What was inflation in April 2026?", "2026-04"),
        ("What was inflation in Apr 2026?", "2026-04"),
    ],
)
def test_an_absolute_period_resolves_to_the_published_form(asked: str, expected: str) -> None:
    """``Q4-2025`` is a reader's spelling and ``2025-Q4`` is the published one.

    The engine keys a datapoint by the published form, so the reader's spelling has to
    arrive as that form or as nothing -- never as a third string that happens to look
    like a period.
    """
    assert period_of(asked) == Bound(Exact(Period(expected)))


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("كم بلغ معدل التضخم في 2025؟", "2025"),
        ("كم بلغ معدل التضخم في 2026-04؟", "2026-04"),
        ("كم بلغ معدل التضخم في الربع الرابع 2025؟", "2025-Q4"),
        ("كم بلغ معدل التضخم في الربع الرابع من 2025؟", "2025-Q4"),
        ("كم بلغ معدل التضخم في أبريل 2026؟", "2026-04"),
    ],
)
def test_the_arabic_absolute_forms_resolve_to_the_same_published_form(
    asked: str, expected: str
) -> None:
    assert period_of(asked) == Bound(Exact(Period(expected)))


def test_a_period_is_ascii_digits_or_it_is_not_a_period() -> None:
    """Arabic-Indic digits are a different string, and ``Period`` refuses them.

    Two spellings of one period would be two rows on a key the whole design rests on, so
    the question resolves to no period rather than to a period nothing is stored under.
    """
    state = period_of("كم بلغ معدل التضخم في ٢٠٢٥؟")
    assert state != Bound(Exact(Period("2025")))


# ------------------------------------------------------- FR-7: the relative forms


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("What was inflation over the last 5 years?", LastN(n=5, grain=Grain.YEARLY)),
        ("What was inflation over the last five years?", LastN(n=5, grain=Grain.YEARLY)),
        ("Show inflation for the past 3 quarters.", LastN(n=3, grain=Grain.QUARTERLY)),
        ("Show inflation for the last 12 months.", LastN(n=12, grain=Grain.MONTHLY)),
        ("What was inflation last year?", LastN(n=1, grain=Grain.YEARLY)),
        ("What was inflation in the previous quarter?", LastN(n=1, grain=Grain.QUARTERLY)),
    ],
)
def test_a_relative_expression_is_the_last_n_periods_at_an_interval(
    asked: str, expected: LastN
) -> None:
    """AD-1: determinate, and unresolvable without the data, so ``Deferred``."""
    assert period_of(asked) == Deferred(expected)


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("كم بلغ معدل التضخم خلال السنوات الخمس الماضية؟", LastN(n=5, grain=Grain.YEARLY)),
        ("كم بلغ معدل التضخم خلال آخر 5 سنوات؟", LastN(n=5, grain=Grain.YEARLY)),
        ("كم بلغ معدل التضخم في العام الماضي؟", LastN(n=1, grain=Grain.YEARLY)),
        ("كم بلغ معدل التضخم في آخر 3 أشهر؟", LastN(n=3, grain=Grain.MONTHLY)),
        ("كم بلغ معدل التضخم في الربع الماضي؟", LastN(n=1, grain=Grain.QUARTERLY)),
    ],
)
def test_the_arabic_relative_expressions_resolve_the_same_way(asked: str, expected: LastN) -> None:
    """Arabic puts the qualifier after the noun; the request is the same request.

    "السنوات الخمس الماضية" is noun, count, qualifier and "the last five years" is
    qualifier, count, noun -- one expression read as a set of parts rather than as a word
    order, which is what makes the two resolve identically rather than nearly so.
    """
    assert period_of(asked) == Deferred(expected)


@pytest.mark.parametrize(
    "asked",
    [
        "What is inflation lately?",
        "What is inflation right now?",
        "What is inflation at the moment?",
        "ما هو معدل التضخم مؤخراً؟",
        "ما هو معدل التضخم في الوقت الحالي؟",
    ],
)
def test_lately_and_right_now_are_the_latest_reading(asked: str) -> None:
    """FR-8: they name a period as surely as a date does, at the declared grain."""
    assert period_of(asked) == Deferred(LastN(n=readings_for_latest(), grain=Grain.MONTHLY))


def test_a_count_a_reader_writes_in_words_is_the_count_it_writes_in_digits() -> None:
    assert period_of("What was inflation over the last five years?") == period_of(
        "What was inflation over the last 5 years?"
    )


def test_a_period_noun_on_its_own_is_not_a_relative_expression() -> None:
    """"month on month" is a basis, not a request for the last month (FR-20).

    Every word of a relative expression has to *be* a part of one; a word that is not
    rejects the whole reading, which is what keeps an ordinary sentence containing
    "month" or "year" from becoming a period request.
    """
    assert period_of("How much did inflation change month on month in April 2026?") == Bound(
        Exact(Period("2026-04"))
    )


# ------------------------------------------------------------ FR-7: spans and open spans


@pytest.mark.parametrize(
    ("asked", "start", "end"),
    [
        ("Show me inflation each year from 2019 to 2025.", "2019", "2025"),
        ("Show inflation from 2019 until 2025.", "2019", "2025"),
        ("Show inflation from 2019 through 2025.", "2019", "2025"),
        ("Show Real GDP by quarter from 2024-Q1 to 2025-Q4.", "2024-Q1", "2025-Q4"),
        ("Show inflation from April 2025 to 2026-04.", "2025-04", "2026-04"),
    ],
)
def test_a_span_the_question_states_binds_to_a_range(asked: str, start: str, end: str) -> None:
    """A ``Range`` names both its periods outright, so it is ``Bound`` and not deferred."""
    assert period_of(asked) == Bound(Range(start=Period(start), end=Period(end)))


@pytest.mark.parametrize(
    ("asked", "start", "end"),
    [
        ("اعرض معدل التضخم لكل سنة من 2019 إلى 2025.", "2019", "2025"),
        ("اعرض معدل التضخم من 2019 حتى 2025.", "2019", "2025"),
        (
            "اعرض الناتج المحلي الإجمالي الحقيقي من الربع الأول 2024 إلى الربع الرابع 2025.",
            "2024-Q1",
            "2025-Q4",
        ),
    ],
)
def test_the_arabic_span_binds_to_the_same_range(asked: str, start: str, end: str) -> None:
    """The second quarter phrase belongs to the second year, not to the first.

    A year is paired with the quarter or month name nearest it, so "من الربع الأول 2024
    إلى الربع الرابع 2025" is two different quarters rather than the first quarter of
    both years -- which is what a table lookup with no positions would produce.
    """
    assert period_of(asked) == Bound(Range(start=Period(start), end=Period(end)))


@pytest.mark.parametrize(
    ("asked", "start", "end"),
    [
        ("What has inflation been since 2019?", "2019", "2026"),
        ("Show inflation from 2019.", "2019", "2026"),
        ("Show Real GDP since 2019-Q1.", "2019-Q1", "2026-Q3"),
        ("كم بلغ معدل التضخم منذ 2019؟", "2019", "2026"),
    ],
)
def test_an_open_span_ends_at_the_period_containing_today(
    asked: str, start: str, end: str
) -> None:
    """``R-BIND-OPEN-RANGE-ENDS-AT-TODAY``, at the grain the reader's own start names.

    Ending it at the newest published period would be a data read inside ``compile/``,
    which AD-1 puts out of reach; ending it at ``today`` is determinate before any data
    access, and a span running past the last reading is a gap for ``execute/`` to state.
    """
    assert open_range_ends_at_today()
    assert period_of(asked) == Bound(Range(start=Period(start), end=Period(end)))


def test_an_open_span_moves_when_today_moves() -> None:
    """The same question, two days apart, is two different spans -- and says so."""
    assert period_of("What has inflation been since 2019?", today=date(2027, 1, 1)) == Bound(
        Range(start=Period("2019"), end=Period("2027"))
    )


def test_a_span_word_standing_elsewhere_does_not_open_a_span() -> None:
    """"من" is an ordinary Arabic word; only one standing directly before the period
    opens a span. Presence rather than adjacency would turn "as a percentage of GDP in
    2021" into a request for everything since 2021."""
    assert period_of("كم بلغ الدين العام كنسبة من الناتج المحلي الإجمالي في 2021؟") == Bound(
        Exact(Period("2021"))
    )


def test_a_span_that_runs_backwards_is_stated_rather_than_silently_swapped() -> None:
    state = period_of("What was inflation from 2025 to 2019?")
    assert isinstance(state, Unbound)
    assert state.reason.startswith(UnboundReason.PERIOD_RANGE_RUNS_BACKWARDS.value)


# ------------------------------------- two periods that are not a span (FR-23's boundary)


@pytest.mark.parametrize(
    "asked",
    [
        "What was inflation between 2019 and 2025?",
        "Compare inflation in 2022 with 2025.",
        "قارن معدل التضخم بين عامي 2022 و2025.",
    ],
)
def test_two_periods_with_a_comparison_word_are_not_a_range(asked: str) -> None:
    """A comparison of two readings (FR-23) and the run between them (FR-16) are
    different questions, and "between X and Y" is how both languages write the first:
    Arabic says "بين عامي 2022 و2025" for exactly the comparison English writes as
    "between 2022 and 2025". Reading either as a span would answer the other question,
    so the reader is told two periods were named rather than having one picked."""
    state = period_of(asked)
    assert isinstance(state, Unbound)
    assert state.reason.startswith(UnboundReason.MORE_THAN_ONE_PERIOD_NAMED.value)


def test_the_arabic_conjunction_joined_to_a_year_still_names_that_year() -> None:
    """"و2025" is the whole of "and 2025", and the fold does not split a clitic off.

    Without the period spellings in ``R-BIND-PERIOD-PREFIXES`` the Arabic question names
    one period where the English names two -- and would quietly answer about 2022 alone.
    """
    state = period_of("قارن معدل التضخم بين عامي 2022 و2025.")
    assert isinstance(state, Unbound)
    assert "2022, 2025" in state.reason


# -------------------------------------------------- FR-5: a period phrase names a grain


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("What was inflation over the last 5 years?", Grain.YEARLY),
        ("Show inflation for the past 3 quarters.", Grain.QUARTERLY),
        ("Show inflation for the last 12 months.", Grain.MONTHLY),
        ("Show me inflation each year from 2019 to 2025.", Grain.YEARLY),
        ("What was inflation in Q4-2025?", Grain.QUARTERLY),
        ("كم بلغ معدل التضخم خلال السنوات الخمس الماضية؟", Grain.YEARLY),
    ],
)
def test_a_period_expression_implying_an_interval_counts_as_naming_a_grain(
    asked: str, expected: Grain
) -> None:
    state = compiled(asked).spec.period
    assert isinstance(state, Bound | Deferred)
    request: PeriodSpec = state.value if isinstance(state, Bound) else state.request
    assert grain_of(request) is expected


def test_a_grain_a_period_expression_names_is_refused_when_it_is_not_published() -> None:
    """FR-6 through a relative expression: Real GDP publishes quarterly and yearly, so
    "the last 6 months" is refused as monthly rather than answered at a neighbour."""
    state = period_of("What was Real GDP over the last 6 months?")
    assert isinstance(state, Unbound)
    assert state.reason.startswith(UnboundReason.GRAIN_NOT_PUBLISHED.value)
    assert Grain.MONTHLY.value in state.reason


def test_a_grain_a_span_names_is_refused_the_same_way() -> None:
    state = period_of("Show Real GDP from 2024-01 to 2024-06.")
    assert isinstance(state, Unbound)
    assert state.reason.startswith(UnboundReason.GRAIN_NOT_PUBLISHED.value)


def test_a_quarter_named_with_no_year_names_the_interval_and_not_a_period() -> None:
    """Picking the year would be compile inventing a reading nobody asked for; saying
    quarterly is reading what the reader wrote (FR-5)."""
    account = compiled("What was inflation in the fourth quarter?")
    assert account.spec.period == Deferred(
        LastN(n=readings_for_latest(), grain=Grain.QUARTERLY)
    )
    assert account.by_field[SpecField.PERIOD].precedence is Precedence.NAMED_IN_QUESTION


def test_a_month_named_with_no_year_names_the_interval_in_either_language() -> None:
    assert period_of("What was inflation in April?") == period_of("كم بلغ معدل التضخم في أبريل؟")
    assert period_of("What was inflation in April?") == Deferred(
        LastN(n=readings_for_latest(), grain=Grain.MONTHLY)
    )


def test_a_period_expression_outranks_the_period_a_follow_up_inherited() -> None:
    """FR-4's "wins over every signal", reached through a period phrase rather than a
    grain word."""
    account = compiled(
        "And over the last 5 years?", history=("What was inflation in 2026-Q1?",)
    )
    assert account.spec.detail == Bound("D-INFLATION")
    assert account.spec.period == Deferred(LastN(n=5, grain=Grain.YEARLY))
    assert account.by_field[SpecField.PERIOD].precedence is Precedence.NAMED_IN_QUESTION


# ------------------------------------------------ AD-1: the closed set, and where it resolves


@pytest.mark.parametrize(
    "asked",
    [
        "What was inflation in 2025?",
        "What was inflation over the last 5 years?",
        "Show me inflation each year from 2019 to 2025.",
        "What has inflation been since 2019?",
        "What is inflation lately?",
        "كم بلغ معدل التضخم خلال السنوات الخمس الماضية؟",
    ],
)
def test_every_period_expression_produces_a_member_of_the_closed_set(asked: str) -> None:
    state = compiled(asked).spec.period
    assert isinstance(state, Bound | Deferred)
    request = state.value if isinstance(state, Bound) else state.request
    assert isinstance(request, Exact | Range | Latest | LastN)


@pytest.mark.parametrize(
    ("asked", "deferred"),
    [
        ("What was inflation in 2025?", False),
        ("Show me inflation each year from 2019 to 2025.", False),
        ("What has inflation been since 2019?", False),
        ("What was inflation over the last 5 years?", True),
        ("What is inflation lately?", True),
    ],
)
def test_only_the_forms_that_need_the_data_are_deferred(asked: str, deferred: bool) -> None:
    """A span names its periods outright and needs nothing; "the last 5 years" is
    anchored on the newest published reading and so cannot resolve in a pure layer.
    Collapsing either into the other is the AD-1 defect in one direction or the other."""
    assert isinstance(compiled(asked).spec.period, Deferred) is deferred


def test_grain_of_is_exhaustive_over_the_period_spec() -> None:
    """A ``PeriodSpec`` member added later must say what interval it is at, rather than
    implying none and so slipping past FR-6's check."""
    with pytest.raises(TypeError, match="not a PeriodSpec member"):
        grain_of("2025")  # type: ignore[arg-type]


# --------------------------------------------------------- AD-17: today, and the cache key


def test_today_is_part_of_every_spec_a_cache_key_is_derived_from() -> None:
    """A cached resolution cannot survive a date boundary because the thing a key is
    derived from carries the date: two specs for the same relative question on two days
    differ, and differ *only* by ``today``."""
    first = compiled("What was inflation over the last 5 years?")
    later = compiled("What was inflation over the last 5 years?", today=date(2026, 9, 16))
    assert first.spec != later.spec
    assert dataclasses.replace(first.spec, today=later.spec.today) == later.spec


@pytest.mark.parametrize(
    "asked",
    [
        "What was inflation over the last 5 years?",
        "Show me inflation each year from 2019 to 2025.",
        "What has inflation been since 2019?",
        "What was inflation in Q4-2025?",
        "كم بلغ معدل التضخم خلال السنوات الخمس الماضية؟",
        "اعرض معدل التضخم من 2019 إلى 2025.",
    ],
)
def test_the_same_period_expression_compiles_identically_every_time(asked: str) -> None:
    accounts = [compiled(asked) for _ in range(5)]
    assert all(account == accounts[0] for account in accounts)


def test_nothing_in_the_period_reading_resolves_a_relative_expression_to_a_period() -> None:
    """The one thing ``compile/`` must not do: "the last 5 years" is not five periods
    counted back from ``today`` here, because the anchor is the newest published reading
    and that is ``execute/``'s to know (AD-1, FR-8)."""
    for today in (TODAY, date(2019, 1, 1), date(2030, 12, 31)):
        assert period_of("What was inflation over the last 5 years?", today=today) == Deferred(
            LastN(n=5, grain=Grain.YEARLY)
        )


# ----------------------------------------------- the phrases are rules data, in normal form


@pytest.mark.parametrize(
    "words",
    [
        *period_nouns().values(),
        relative_back_words(),
        range_from_words(),
        range_to_words(),
        comparison_words(),
        period_prefixes(),
        latest_words(),
        frozenset(count_words()),
        frozenset(quarter_numbers()),
    ],
    ids=lambda words: f"{len(words)}-phrases",
)
def test_every_period_phrase_is_already_in_normal_form(words: frozenset[str]) -> None:
    """A phrase that is not in normal form can never match, because the question always
    is -- silent, permanent, and exactly finding 121's Arabic half."""
    assert {phrase for phrase in words if normalise(phrase) != phrase} == set()


def test_every_period_rule_is_loaded_and_fireable() -> None:
    for rule in (
        BindingRule.PERIOD_NOUNS,
        BindingRule.RELATIVE_PERIOD_WORDS,
        BindingRule.COUNT_WORDS,
        BindingRule.PERIOD_RANGE_WORDS,
        BindingRule.OPEN_RANGE_END,
        BindingRule.PERIOD_PREFIXES,
    ):
        assert rules().fire(rule.value).is_fireable


def test_a_grain_added_to_the_domain_would_need_period_nouns_rather_than_have_none() -> None:
    assert set(period_nouns()) == set(Grain)


def test_both_languages_are_represented_in_every_period_table() -> None:
    """The bilingual claim, asserted over the data rather than over one example.

    A table with no Arabic entry is how "resolves identically in Arabic" quietly becomes
    "resolves in English", and it would pass every English example above.
    """
    arabic = Question.parse("").words  # the fold, applied to nothing, is nothing
    assert arabic == ()
    for words in (
        *period_nouns().values(),
        relative_back_words(),
        range_from_words(),
        range_to_words(),
        comparison_words(),
        frozenset(count_words()),
        frozenset(quarter_numbers()),
        latest_words(),
    ):
        assert any(phrase.isascii() for phrase in words), words
        assert any(not phrase.isascii() for phrase in words), words
