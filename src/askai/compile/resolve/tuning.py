"""The resolution ladder's reviewed constants, read from ``rules/`` and never written here.

Purity: pure once the rule files have loaded.

The same door :mod:`askai.compile.lexicon` is for binding, and for the same reason: AD-11
puts a reader-affecting constant in versioned data, and ``tests/test_rules.py`` scans
``compile/`` for the literal that would make that decorative. Every number and every list
this package uses arrives through a function here.

Two things this module does deliberately.

**The period vocabulary is assembled from the binder's own lists, not copied.** R-158
requires stripping *"from the same list the follow-up test uses"* and R-162 requires the
reviewed vocabulary to be consulted on every resolution. Both are satisfied by reading
:mod:`askai.compile.lexicon` rather than by maintaining a second set of period words here,
which would be a second opinion about what a period word is -- and the first time the two
disagreed, a question would bind a period the resolver had already scored against.

**Nothing widens a clause's type.** A clause of the wrong shape stops the process naming
the rule and the clause, because the alternative is a threshold nobody chose deciding
whether a reader is answered or asked a question.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from functools import cache
from typing import Final

from askai.compile.lexicon import (
    comparison_words,
    count_words,
    grain_words,
    latest_words,
    month_numbers,
    period_nouns,
    quarter_numbers,
    range_from_words,
    range_to_words,
    relative_back_words,
)
from askai.ports.resolution import UnitShape
from askai.rules import PER_CENT, RuleValue, rules

__all__ = [
    "Clause",
    "ResolveRule",
    "ambiguity_margin",
    "content_overlap_weight",
    "country_weight",
    "entity_weight",
    "fold_unit",
    "gate_stopwords",
    "grain_is_a_veto",
    "maximum_offered",
    "minimum_ngram",
    "period_coverage_is_a_veto",
    "period_vocabulary",
    "request_vocabulary",
    "shape_words",
    "strip_bare_numbers",
    "unit_shape_weight",
    "unit_shapes",
]


class ResolveRule(StrEnum):
    """The rules this package reads. Ids, so a typo fails at load rather than at a reader."""

    REQUEST_VOCABULARY = "R-RESOLVE-REQUEST-VOCABULARY"
    PERIOD_VOCABULARY = "R-RESOLVE-PERIOD-VOCABULARY-IS-STRIPPED"
    NGRAM_GATE = "R-RESOLVE-CONTENT-NGRAM-GATE"
    SIGNALS = "R-RESOLVE-SIGNALS"
    AMBIGUITY_MARGIN = "R-RESOLVE-AMBIGUITY-MARGIN"
    UNIT_SHAPES = "R-RESOLVE-UNIT-SHAPES"


class Clause(StrEnum):
    """The clause names those rules carry."""

    WORDS = "words"
    STRIP_PERIOD = "strip_period_vocabulary"
    STRIP_NUMBERS = "strip_bare_numbers"
    MINIMUM_NGRAM = "minimum_ngram"
    GATE_STOPWORDS = "gate_stopwords"
    GRAIN_VETO = "grain_is_a_veto"
    PERIOD_VETO = "period_coverage_is_a_veto"
    ENTITY_WEIGHT = "entity_weight_percent"
    COUNTRY_WEIGHT = "country_weight_percent"
    UNIT_WEIGHT = "unit_shape_weight_percent"
    OVERLAP_WEIGHT = "content_overlap_weight_percent"
    MARGIN = "margin_percent"
    MAXIMUM_OFFERED = "maximum_offered"
    LABELLED_SET = "labelled_set"


#: Which clause of ``R-RESOLVE-UNIT-SHAPES`` lists the units of each shape, and which
#: lists the words a reader names it by. Derived from ``UnitShape`` rather than written
#: out, so a shape added to the port fails here -- naming the clause the file is missing --
#: instead of silently having no units and no vocabulary.
#:
#: A tuple of pairs rather than a dict, because a module-level dict is the shape an
#: ambient collector takes and ``tests/test_domain_invariants.py`` scans the tree for one.
#: Nothing here is collected, but the scan is right to refuse the shape rather than judge
#: the intent.
_SHAPE_CLAUSES: Final[tuple[tuple[UnitShape, str, str | None], ...]] = (
    (UnitShape.SHARE, "share_units", "share_words"),
    (UnitShape.RANK, "rank_units", "rank_words"),
    (UnitShape.AMOUNT, "amount_units", "amount_words"),
    (UnitShape.INDEX, "index_units", None),
    (UnitShape.DURATION, "duration_units", None),
)


class ResolveTuningError(RuntimeError):
    """A rule clause the resolution ladder needs is missing or is not the type it must be."""


def _wrong_shape(rule: ResolveRule, clause: str, value: RuleValue, wanted: str) -> str:
    return (
        f"{rule.value} clause `{clause}` is {type(value).__name__}, and the resolution "
        f"ladder needs {wanted}; the clause is read here and nowhere else, so the file "
        "is what changes"
    )


def _phrases(rule: ResolveRule, clause: str) -> frozenset[str]:
    value = rules().value(rule, clause)
    if not isinstance(value, tuple):
        raise ResolveTuningError(_wrong_shape(rule, clause, value, "a list of words"))
    return frozenset(value)


def _flag(rule: ResolveRule, clause: Clause) -> bool:
    value = rules().value(rule, clause)
    if not isinstance(value, bool):
        raise ResolveTuningError(_wrong_shape(rule, clause, value, "true or false"))
    return value


def _count(rule: ResolveRule, clause: Clause) -> int:
    value = rules().value(rule, clause)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResolveTuningError(_wrong_shape(rule, clause, value, "a whole number"))
    if value < 1:
        raise ResolveTuningError(
            f"{rule.value} clause `{clause.value}` is {value}; it is at least 1"
        )
    return value


def _fraction(rule: ResolveRule, clause: Clause) -> float:
    value = rules().value(rule, clause)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResolveTuningError(_wrong_shape(rule, clause, value, "a whole percentage"))
    if not 0 <= value <= PER_CENT:
        raise ResolveTuningError(
            f"{rule.value} clause `{clause.value}` is {value}; a weight is a percentage "
            f"between 0 and {PER_CENT}, and a score built from one outside that range "
            "is not comparable with another"
        )
    return value / PER_CENT


# ------------------------------------------------------------------------- vocabulary


@cache
def request_vocabulary() -> frozenset[str]:
    """The interrogative and politeness words removed before scoring (R-159)."""
    return _phrases(ResolveRule.REQUEST_VOCABULARY, Clause.WORDS)


@cache
def strip_period_vocabulary() -> bool:
    """Whether period vocabulary is removed before subject salience (R-158)."""
    return _flag(ResolveRule.PERIOD_VOCABULARY, Clause.STRIP_PERIOD)


@cache
def strip_bare_numbers() -> bool:
    """Whether an all-digit token is removed before scoring."""
    return _flag(ResolveRule.PERIOD_VOCABULARY, Clause.STRIP_NUMBERS)


@cache
def period_vocabulary() -> frozenset[str]:
    """Every phrase the reviewed period vocabulary knows, in both languages.

    Assembled from :mod:`askai.compile.lexicon` -- the binder's own lists -- rather than
    restated. R-158 says the stripping list *is* the follow-up test's list, and R-162 says
    the reviewed vocabulary is consulted on every resolution; reading it through the one
    door is what makes both structural instead of remembered.

    Multi-word phrases are kept whole. The stripper matches spans as well as single words,
    so *"most recent"* and *"في الوقت الحالي"* are removed as the phrases they are rather
    than leaving *"most"* behind to compete for subject salience.
    """
    phrases: set[str] = set()
    phrases |= set(latest_words())
    phrases |= set(relative_back_words())
    phrases |= set(range_from_words())
    phrases |= set(range_to_words())
    phrases |= set(comparison_words())
    phrases |= set(count_words())
    phrases |= set(month_numbers())
    phrases |= set(quarter_numbers())
    for nouns in period_nouns().values():
        phrases |= set(nouns)
    for words in grain_words().values():
        phrases |= set(words)
    return frozenset(phrases)


# ------------------------------------------------------------------------- the gate


@cache
def minimum_ngram() -> int:
    """The shortest content run a candidate must share with the subject to be admitted."""
    return _count(ResolveRule.NGRAM_GATE, Clause.MINIMUM_NGRAM)


@cache
def gate_stopwords() -> frozenset[str]:
    """The generic measure nouns that do not count as content for the gate.

    A *separate* list from :func:`request_vocabulary`, and separate on purpose. These
    words stay in the text that gets scored -- the export publishes *Number of Jobs in the
    Sector* and *Occupancy Rate of Hotels*, and stripping their nouns would remove the
    reader's own name for the thing -- and are set aside only when asking whether the
    candidate and the question are about the same subject.

    Without them the gate does not do what Story 2.3 says it does: `rate` is exactly four
    characters, so *"Obesity Rate"* and *"what is the unemployment rate"* share a run of
    the reviewed length and the epic's own counter-example would be admitted.
    """
    return _phrases(ResolveRule.NGRAM_GATE, Clause.GATE_STOPWORDS)


# ------------------------------------------------------------------------- the signals


@cache
def grain_is_a_veto() -> bool:
    """Is a detail that does not publish the named grain *out*, rather than ranked lower?"""
    return _flag(ResolveRule.SIGNALS, Clause.GRAIN_VETO)


@cache
def period_coverage_is_a_veto() -> bool:
    """Is a detail that does not publish the asked span *out*, rather than ranked lower?"""
    return _flag(ResolveRule.SIGNALS, Clause.PERIOD_VETO)


@cache
def entity_weight() -> float:
    """What a named group or sector contributes to a candidate's discrimination score."""
    return _fraction(ResolveRule.SIGNALS, Clause.ENTITY_WEIGHT)


@cache
def country_weight() -> float:
    """What a named country the candidate benchmarks against contributes."""
    return _fraction(ResolveRule.SIGNALS, Clause.COUNTRY_WEIGHT)


@cache
def unit_shape_weight() -> float:
    """What agreement between the asked shape and the published unit's shape contributes."""
    return _fraction(ResolveRule.SIGNALS, Clause.UNIT_WEIGHT)


@cache
def content_overlap_weight() -> float:
    """What shared content between the subject and the candidate's surfaces contributes."""
    return _fraction(ResolveRule.SIGNALS, Clause.OVERLAP_WEIGHT)


# ------------------------------------------------------------------------- the decision


@cache
def ambiguity_margin() -> float:
    """How far ahead the leader must be to bind alone rather than be disambiguated (FR-2)."""
    return _fraction(ResolveRule.AMBIGUITY_MARGIN, Clause.MARGIN)


@cache
def maximum_offered() -> int:
    """How many candidates a disambiguation may name before it stops being a question."""
    return _count(ResolveRule.AMBIGUITY_MARGIN, Clause.MAXIMUM_OFFERED)


@cache
def margin_labelled_set() -> str:
    """The labelled-set identity the margin records, which FR-2 requires it to carry."""
    value = rules().value(ResolveRule.AMBIGUITY_MARGIN, Clause.LABELLED_SET)
    if not isinstance(value, str):
        raise ResolveTuningError(
            _wrong_shape(ResolveRule.AMBIGUITY_MARGIN, Clause.LABELLED_SET, value, "an identity")
        )
    return value


# ------------------------------------------------------------------------- unit shapes


def fold_unit(unit: str) -> str:
    """A published unit name as the shape table keys it: case and spacing only.

    Deliberately **not** ``normalise()``. The engine's one fold is for *reader prose* and
    collapses punctuation to spaces, which is right for a question and destroys a unit:
    ``%`` folds to the empty string, and ``%`` is the unit of 63 published details --
    the single commonest in the export. ``MT/ha`` and ``M3/MT`` would likewise become
    indistinguishable from their spaced forms.

    A unit is a published token rather than something a reader wrote, so it is folded as a
    token: case and surrounding space, nothing else. AD-26 is not weakened by this, because
    nothing here is compared against a folded question -- the unit table is keyed on what
    the export publishes and looked up with what the export publishes.
    """
    return " ".join(unit.casefold().split())


@cache
def unit_shapes() -> Mapping[str, UnitShape]:
    """Each published unit name to the shape it expresses, keyed by :func:`fold_unit`."""
    found: dict[str, UnitShape] = {}
    for shape, units_clause, _words_clause in _SHAPE_CLAUSES:
        for unit in _phrases(ResolveRule.UNIT_SHAPES, units_clause):
            folded = fold_unit(unit)
            if folded:
                found[folded] = shape
    return found


@cache
def shape_words() -> Mapping[UnitShape, frozenset[str]]:
    """Each shape a reader can ask for, and the bilingual words that name it.

    Only three shapes have a question vocabulary. ``INDEX`` and ``DURATION`` are published
    shapes that readers do not ask for by shape -- nobody asks *"give me a duration"* --
    so they are classifiable on the unit side and silent on the question side, and giving
    them an invented vocabulary would make the signal fire on words nobody reviewed.
    """
    return {
        shape: _phrases(ResolveRule.UNIT_SHAPES, words_clause)
        for shape, _units_clause, words_clause in _SHAPE_CLAUSES
        if words_clause is not None
    }
