"""Measuring retrieval against the labelled set, and deriving a floor from what it says.

Purity: pure arithmetic over a search it is handed; the searching itself is the index's IO.

This is AD-30's instrument. It takes any :class:`~askai.ports.vectors.VectorSourcePort`
-- through the ``NamesIndex`` built on it -- and reports what that source can actually
find, so that *"the embedding model is better"* is a measurement rather than a belief.
Nothing here knows whether it is scoring hashed character trigrams or a hosted model, and
that is the point: the comparison is only worth making if both sides are put through the
same instrument.

**What is measured.** Recall at 1, 5 and 10 over candidate generation -- 10 because that
is the reviewed candidate limit, so recall@10 is the ceiling on everything the
discrimination stage downstream could possibly get right. Then the two score
distributions AD-30 asks for: the scores of *relevant* candidates and the scores of
*irrelevant* ones, and the separation between them.

**Where the irrelevant distribution comes from.** Not from the low-ranked tail of a
successful search, which would be a distribution of near-misses and would flatter any
floor. It comes from the cases whose correct answer is nothing at all: the best score the
index could produce for a question about rainfall is, by construction, a score a floor
must refuse. This is why the labelled set carries negatives, and why a set without them
can only ever derive a floor of zero.

**Why the floor is a maximum and not a percentile.** The threshold chosen is the one
maximising the separation between the rate at which relevant candidates survive it and
the rate at which irrelevant ones do -- Youden's J, computed over the observed scores.
A percentile of either distribution alone would be a choice about which error to prefer,
dressed up as a measurement; this is the value at which the two distributions are as far
apart as the data allows them to be, and the residual error rates are reported with it
so that a reader can see what the floor still costs.

**And when it should not be trusted.** AD-30: *"if the distributions overlap materially,
a floor is not sufficient and a structural discriminator is required"* -- finding 126's
lesson, that a flat score cannot carry a distinction the index never encoded. The
derivation therefore reports ``sufficient`` alongside the value, measured against a
declared error budget in ``rules/``, and a derivation that fails it is evidence for Story
2.4's discriminator rather than a number to ship.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from askai.adapters.index.labelled import LabelKind, LabelledCase, LabelledSet
from askai.adapters.index.namesearch import NameCandidate, NamesIndex
from askai.compile.resolve import (
    Disambiguation,
    QuestionSignals,
    Resolution,
    Resolved,
    decide,
    discriminate,
    generate,
    subject_of,
)
from askai.messages.lang import Lang
from askai.ports.index import IndexScope
from askai.ports.resolution import CandidatePort

__all__ = [
    "CaseMeasurement",
    "Derivation",
    "LadderMeasurement",
    "LadderReport",
    "QualityReport",
    "as_percent",
    "derive_floor",
    "derive_relative_cut",
    "derive_threshold",
    "evaluate",
    "evaluate_ladder",
    "percentile",
]

_FULL = 100.0


@dataclass(frozen=True, slots=True)
class CaseMeasurement:
    """One labelled case, put through the index, with the numbers the report needs.

    The candidates themselves are not kept: a report over two hundred cases holding ten
    candidate objects each is a value nothing reads and a memory profile that discourages
    running the thing. What is kept is every quantity a floor or a cut is derived from.
    """

    case: LabelledCase

    #: Where the first expected detail came back, one-based, or ``None`` if it did not.
    rank: int | None

    #: The best candidate's score, whatever it was. Zero when nothing came back at all.
    top_score: float

    #: The score of the best expected candidate, or ``None`` when none was returned.
    expected_score: float | None

    #: The scores of every returned candidate the label says is not an answer, best first.
    wrong_scores: tuple[float, ...]

    #: The score of each *expected* candidate below rank one, as a fraction of the top
    #: score -- the evidence a relative cut must not throw away.
    kept_ratios: tuple[float, ...]

    #: The same fraction for each wrong candidate below rank one -- the evidence a
    #: relative cut exists to throw away.
    cut_ratios: tuple[float, ...]

    @property
    def found(self) -> bool:
        return self.rank is not None


@dataclass(frozen=True, slots=True)
class QualityReport:
    """What one vector source scored over one labelled set. The comparable artefact.

    Carries both identities, because a report is only meaningful as a pair: a number from
    a labelled set of one version and a vector source of one identity, and comparing two
    reports that disagree about either is comparing nothing.
    """

    labelled_identity: str
    source_identity: str
    limit: int
    measurements: tuple[CaseMeasurement, ...]

    def recall_at(self, rank: int) -> float:
        """The share of positive cases whose expected detail came back in the top *rank*."""
        positives = [entry for entry in self.measurements if not entry.case.is_negative]
        if not positives:
            return 0.0
        found = sum(1 for entry in positives if entry.rank is not None and entry.rank <= rank)
        return found / len(positives)

    def recall_at_for(self, rank: int, kind: LabelKind) -> float:
        """Recall at *rank* over one kind of case only -- the breakdown that carries the news."""
        positives = [
            entry
            for entry in self.measurements
            if not entry.case.is_negative and entry.case.kind is kind
        ]
        if not positives:
            return 0.0
        found = sum(1 for entry in positives if entry.rank is not None and entry.rank <= rank)
        return found / len(positives)

    def recall_at_in(self, rank: int, lang: Lang) -> float:
        """Recall at *rank* over one language only.

        Reported separately because Arabic is a first-class path and not a translation:
        an aggregate that is carried by the English half would hide finding 121's failure
        rather than measure it.
        """
        positives = [
            entry
            for entry in self.measurements
            if not entry.case.is_negative and entry.case.lang is lang
        ]
        if not positives:
            return 0.0
        found = sum(1 for entry in positives if entry.rank is not None and entry.rank <= rank)
        return found / len(positives)

    def counted(self, kind: LabelKind) -> int:
        return sum(1 for entry in self.measurements if entry.case.kind is kind)

    def counted_in(self, lang: Lang) -> int:
        return sum(
            1
            for entry in self.measurements
            if entry.case.lang is lang and not entry.case.is_negative
        )

    @property
    def relevant_scores(self) -> tuple[float, ...]:
        """The score of the correct candidate, over the positive cases that found one.

        A case whose expected detail never came back contributes nothing here rather than
        a zero: it is a recall failure, already counted as one, and feeding it in as a
        zero-scoring relevant candidate would drag the floor down to compensate for a
        miss no floor could have prevented.
        """
        return tuple(
            sorted(
                entry.expected_score
                for entry in self.measurements
                if not entry.case.is_negative and entry.expected_score is not None
            )
        )

    @property
    def irrelevant_scores(self) -> tuple[float, ...]:
        """The best score each negative case produced -- what a floor has to refuse.

        A negative case that returned nothing contributes a zero, because it is a case the
        index refused on its own and a floor of anything at all also refuses it.
        """
        return tuple(
            sorted(entry.top_score for entry in self.measurements if entry.case.is_negative)
        )

    @property
    def displacing_scores(self) -> tuple[float, ...]:
        """The score of the *wrong* candidate that outranked the answer, where one did.

        Reported and deliberately **not** used in the derivation. These are irrelevant
        candidates by the label and they sit at the very top of the score range, so
        folding them into the irrelevant distribution would derive a floor of zero and
        call it a measurement. They are what AD-30 means by distributions overlapping
        materially: a candidate the label calls wrong, scoring above the typical right
        one, is a distinction the index never encoded and no threshold can recover.
        """
        return tuple(
            sorted(
                entry.top_score
                for entry in self.measurements
                if not entry.case.is_negative and entry.rank is not None and entry.rank > 1
            )
        )

    @property
    def empty_negatives(self) -> float:
        """The share of negative cases the index already returns nothing for, before a floor."""
        negatives = [entry for entry in self.measurements if entry.case.is_negative]
        if not negatives:
            return 0.0
        return sum(1 for entry in negatives if entry.top_score <= 0.0) / len(negatives)


def evaluate(
    index: NamesIndex,
    labelled: LabelledSet,
    *,
    limit: int,
) -> QualityReport:
    """Run every case in *labelled* through *index* and report what came back.

    *limit* is the candidate depth measured to, and is an argument rather than a default
    because recall@10 against a search that only ever returned five would be a number
    about the harness rather than about the index.

    The scope is unrestricted: this stage measures candidate *generation*, and AD-14's
    pre-filter is a property of the question that reaches it, not of the vectoriser being
    compared. A narrower scope can only raise these numbers.
    """
    scope = IndexScope()
    measurements = tuple(
        _measure(case, index.candidates(case.question, scope=scope, limit=limit))
        for case in labelled
    )
    return QualityReport(
        labelled_identity=labelled.identity,
        source_identity=index.generation.source_identity,
        limit=limit,
        measurements=measurements,
    )


def _measure(case: LabelledCase, candidates: Sequence[NameCandidate]) -> CaseMeasurement:
    top = candidates[0].score if candidates else 0.0
    rank: int | None = None
    expected_score: float | None = None
    wrong: list[float] = []
    kept: list[float] = []
    cut: list[float] = []
    for position, candidate in enumerate(candidates, start=1):
        if candidate.detail_id in case.expected:
            if rank is None:
                rank = position
                expected_score = candidate.score
            if position > 1 and top > 0.0:
                kept.append(candidate.score / top)
            continue
        wrong.append(candidate.score)
        if position > 1 and top > 0.0:
            cut.append(candidate.score / top)
    return CaseMeasurement(
        case=case,
        rank=rank,
        top_score=top,
        expected_score=expected_score,
        wrong_scores=tuple(wrong),
        kept_ratios=tuple(kept),
        cut_ratios=tuple(cut),
    )


@dataclass(frozen=True, slots=True)
class Derivation:
    """A threshold, and everything a reviewer needs to argue with it.

    AD-30 requires the derivation to be recorded *with* the value, so this is the value a
    rule file is written from rather than a number the caller reads and paraphrases.
    """

    #: The derived threshold.
    value: float

    #: How far apart the two distributions are: the median of the relevant scores less the
    #: 95th percentile of the irrelevant ones. Negative means the irrelevant tail reaches
    #: above the typical relevant score, which is overlap in the plainest possible form.
    separation: float

    #: The share of relevant candidates this threshold would discard.
    false_negative_rate: float

    #: The share of irrelevant candidates this threshold would admit.
    false_positive_rate: float

    relevant: int
    irrelevant: int

    #: Whether both error rates come in under the declared budget. ``False`` is AD-30's
    #: *"a floor is not sufficient and a structural discriminator is required"*, and is a
    #: finding about the index rather than a failure of this module.
    sufficient: bool


def percentile(values: Sequence[float], share: float) -> float:
    """The value at *share* of the way through sorted *values*, by nearest rank.

    Nearest rank rather than interpolation: every value here is an observed score, and a
    threshold that no candidate actually scored is harder to argue about than one that at
    least one of them did.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round(share * (len(ordered) - 1))))
    return ordered[position]


def derive_threshold(
    relevant: Sequence[float],
    irrelevant: Sequence[float],
    *,
    high_share: float,
    false_negative_budget: float,
    false_positive_budget: float,
) -> Derivation:
    """The threshold maximising the gap between the two survival rates, and its cost.

    The estimator itself, over two distributions and nothing else -- which is what makes
    it testable on distributions whose right answer is known by construction, rather than
    only on the corpus it was written for. A threshold cannot be derived from one
    distribution: with no irrelevant observations every value costs recall and buys
    nothing measurable, so that case returns zero and declares itself insufficient rather
    than returning the lowest relevant score and calling it a floor.
    """
    if not relevant or not irrelevant:
        return Derivation(
            value=0.0,
            separation=0.0,
            false_negative_rate=0.0 if relevant else 1.0,
            false_positive_rate=1.0 if irrelevant else 0.0,
            relevant=len(relevant),
            irrelevant=len(irrelevant),
            sufficient=False,
        )
    def _gap(threshold: float) -> tuple[float, float]:
        # The survival-rate gap, with the threshold itself as the tie-break: where two
        # values separate the distributions equally well the stricter one is taken, so
        # the derivation cannot drift downwards on a tie nobody measured.
        return (_rate(relevant, threshold) - _rate(irrelevant, threshold), threshold)

    best = max(sorted({*relevant, *irrelevant}), key=_gap)
    false_negative = 1.0 - _rate(relevant, best)
    false_positive = _rate(irrelevant, best)
    return Derivation(
        value=best,
        separation=percentile(relevant, 0.5) - percentile(irrelevant, high_share),
        false_negative_rate=false_negative,
        false_positive_rate=false_positive,
        relevant=len(relevant),
        irrelevant=len(irrelevant),
        sufficient=(
            false_negative <= false_negative_budget and false_positive <= false_positive_budget
        ),
    )


def _rate(values: Sequence[float], threshold: float) -> float:
    return sum(1 for value in values if value >= threshold) / len(values)


def derive_floor(
    report: QualityReport,
    *,
    high_share: float,
    false_negative_budget: float,
    false_positive_budget: float,
) -> Derivation:
    """The absolute score floor this report supports, and whether it is sufficient.

    The budgets are arguments rather than literals so that the criterion a floor was
    judged against is itself reviewable data (``rules/``) rather than a number inside the
    function that decided it.
    """
    return derive_threshold(
        report.relevant_scores,
        report.irrelevant_scores,
        high_share=high_share,
        false_negative_budget=false_negative_budget,
        false_positive_budget=false_positive_budget,
    )


def derive_relative_cut(
    report: QualityReport,
    *,
    high_share: float,
    false_negative_budget: float,
    false_positive_budget: float,
) -> Derivation:
    """The relative cut against the best hit, derived the same way as the floor.

    Story 2.13's last criterion: *"a relative cut against the best hit is applied, so a
    good first suggestion is not followed by two bad ones."* The two distributions here
    are the ratio-to-best of correct candidates that ranked below first -- which a cut must
    keep -- and the ratio-to-best of wrong ones, which is what it exists to drop.
    """
    keep = [ratio for entry in report.measurements for ratio in entry.kept_ratios]
    drop = [ratio for entry in report.measurements for ratio in entry.cut_ratios]
    return derive_threshold(
        keep,
        drop,
        high_share=high_share,
        false_negative_budget=false_negative_budget,
        false_positive_budget=false_positive_budget,
    )


def as_percent(value: float) -> int:
    """*value* as the whole-number percentage a rule clause can carry.

    Rounded down, deliberately: a floor is a *minimum* a candidate must reach, and
    rounding it up would refuse a candidate the measurement admitted.
    """
    return int(value * _FULL)


# ------------------------------------------------------------------ the resolution ladder


@dataclass(frozen=True, slots=True)
class LadderMeasurement:
    """One labelled case put through AD-25's three stages, and what came back.

    Separate from :class:`CaseMeasurement` because it measures a different thing.
    ``CaseMeasurement`` measures *generation* against the question as asked; this measures
    what the answer path actually does -- subject extraction, the structural gate,
    deterministic discrimination, and the decision. A harness that reported only the first
    would understate or overstate the shipped behaviour and give the next reader a number
    that describes a path nothing takes.
    """

    case: LabelledCase

    #: Where the first expected detail came back from *generation*, one-based, or ``None``.
    generated_rank: int | None

    #: Where it stood after discrimination. The pair is the point: discrimination earning
    #: its place means converting recall@10 into recall@1, and only both numbers show it.
    discriminated_rank: int | None

    #: ``bound`` | ``asked`` | ``refused`` -- which of AD-25 stage 3's three outcomes.
    outcome: str

    #: Whether the reader reached the right detail at all: bound to it, or offered it among
    #: the named candidates. A disambiguation naming the right answer is a good outcome and
    #: counting it as a failure would make the honest path look worse than a silent guess.
    reached: bool


@dataclass(frozen=True, slots=True)
class LadderReport:
    """What the whole ladder scored over one labelled set."""

    measurements: tuple[LadderMeasurement, ...]

    def _positives(self, kind: LabelKind | None = None) -> tuple[LadderMeasurement, ...]:
        return tuple(
            entry
            for entry in self.measurements
            if not entry.case.is_negative and (kind is None or entry.case.kind is kind)
        )

    def generated_at(self, rank: int, kind: LabelKind | None = None) -> float:
        found = self._positives(kind)
        if not found:
            return 0.0
        hit = sum(
            1 for e in found if e.generated_rank is not None and e.generated_rank <= rank
        )
        return hit / len(found)

    def discriminated_at(self, rank: int, kind: LabelKind | None = None) -> float:
        found = self._positives(kind)
        if not found:
            return 0.0
        hit = sum(
            1
            for e in found
            if e.discriminated_rank is not None and e.discriminated_rank <= rank
        )
        return hit / len(found)

    def counted(self, kind: LabelKind | None = None) -> int:
        return len(self._positives(kind))

    def reached(self) -> float:
        """The share of positive cases where the reader reaches the right detail."""
        found = self._positives()
        if not found:
            return 0.0
        return sum(1 for entry in found if entry.reached) / len(found)

    def outcomes(self) -> tuple[tuple[str, int], ...]:
        """How many positive cases ended in each of stage 3's three outcomes."""
        found = self._positives()
        counted = {name: sum(1 for e in found if e.outcome == name) for name in _OUTCOMES}
        return tuple((name, counted[name]) for name in _OUTCOMES)

    def negative_outcomes(self) -> tuple[tuple[str, int], ...]:
        """The same for the cases whose correct answer is nothing.

        The one to read first is ``bound``: a question this corpus cannot answer, answered
        confidently, is the failure AD-30 and Story 2.7 exist to prevent, and it is worse
        than either of the other two.
        """
        negatives = [entry for entry in self.measurements if entry.case.is_negative]
        if not negatives:
            return ()
        counted = {name: sum(1 for e in negatives if e.outcome == name) for name in _OUTCOMES}
        return tuple((name, counted[name]) for name in _OUTCOMES)

    @property
    def negatives(self) -> int:
        return sum(1 for entry in self.measurements if entry.case.is_negative)


#: Stage 3's three outcomes, in the order a report reads them: answered, asked, refused.
_OUTCOMES: Final = ("bound", "asked", "refused")


def evaluate_ladder(
    candidates: CandidatePort, labelled: LabelledSet, *, limit: int | None = None
) -> LadderReport:
    """Run every case in *labelled* through AD-25's three stages and report what came back.

    The signals handed to stage 2 are deliberately **empty**: this measures what the ladder
    achieves from the question's subject alone, with no named grain, period or country to
    discriminate on. That is the floor rather than the ceiling -- a real question carrying
    a period or a sector gives stage 2 more to work with -- and it is the honest number to
    compare two vector sources on, because the structural signals do not depend on which
    vector source produced the candidates.
    """
    measurements: list[LadderMeasurement] = []
    for case in labelled:
        subject = subject_of(case.question)
        generated = generate(subject, candidates, limit=limit)
        result = discriminate(generated, QuestionSignals(subject=subject))
        outcome = decide(result)
        measurements.append(
            LadderMeasurement(
                case=case,
                generated_rank=_rank_of(
                    [found.detail_id for found in generated], case.expected
                ),
                discriminated_rank=_rank_of(
                    [scored.candidate.detail_id for scored in result.survivors], case.expected
                ),
                outcome=_outcome_of(outcome),
                reached=_reached(outcome, case.expected),
            )
        )
    return LadderReport(measurements=tuple(measurements))


def _rank_of(detail_ids: Sequence[str], expected: frozenset[str]) -> int | None:
    """Where the first expected detail appears, one-based, or ``None`` if it does not."""
    for position, detail_id in enumerate(detail_ids, start=1):
        if detail_id in expected:
            return position
    return None


def _outcome_of(outcome: Resolution) -> str:
    match outcome:
        case Resolved():
            return "bound"
        case Disambiguation():
            return "asked"
        case _:
            return "refused"


def _reached(outcome: Resolution, expected: frozenset[str]) -> bool:
    """Did the reader reach the right detail -- bound to it, or offered it by name?

    A disambiguation naming the right answer is a good outcome. Counting it as a failure
    would make the honest path score worse than a silent guess, which is the opposite of
    what this engine is for.
    """
    match outcome:
        case Resolved(detail_id=detail_id):
            return detail_id in expected
        case Disambiguation(candidates=offered):
            return any(entry.detail_id in expected for entry in offered)
        case _:
            return False
