"""Stage 2 of AD-25: tell the candidates apart on the rest of the question.

Purity: pure. No port, no store, no model -- values in, values out.

This is the stage Story 2.13 demonstrated is **necessary rather than assumed**. Over
``names-v1``, where a wrong candidate outranked the right one, that wrong candidate's
median score was 0.831 against a derived floor of 0.838, and its 95th percentile was
identical to the relevant 95th percentile. By similarity alone a wrong top answer is
indistinguishable from a right one, and an embedding model makes it worse rather than
better: *Real GDP* and *Nominal GDP* are genuinely similar and differ by the one word that
changes the answer.

So this stage does not score similarity again. It asks questions the published layer can
answer definitely, using signals the compiler has already extracted from the question, and
it never re-ranks on stage 1's score -- which would undo the measurement that put it here.

**Two of the six signals are vetoes, and a veto is not a heavy weight.** FR-6 and Story
2.4 both say a detail that does not publish the named grain is *out*, not merely ranked
lower; a weight, however large, can always be outvoted by enough of the others. Grain and
period coverage are the two places the catalogue gives a definite negative -- it knows
exactly which periods exist -- so a candidate contradicting one is removed.

**The other four are evidence, and each is silent when the question is silent.** A
question naming no sector must not penalise every candidate that has one, and a candidate
declaring no benchmark set must not be penalised for a country the reader named: 268 of
289 details declare no benchmark set at all, so reading that absence as disagreement would
eliminate almost the whole catalogue on any question mentioning a country. A signal that
cannot speak contributes nothing in either direction and says so.

**The worked example.** *"a chart of the national GDP from 2022 to 2025"* arrives with 15
lexical candidates. The period binder has already read 2022-2025 as a yearly range, so
grain removes every detail publishing only quarterly or monthly rows, period coverage
removes every detail that does not publish all four years, and unit shape prefers a
GDP-shaped amount over a share or a rank. **No candidate is selected by string overlap
alone** -- that signal carries the least weight of the four precisely because it is the
one stage 1 already used.

**And when discrimination cannot decide, it says so.** ``Sector Contribution To GDP`` is
published by eight sectors. A question naming no sector supplies nothing that separates
them, every one scores identically, and this stage returns all eight rather than breaking
a tie it has no evidence to break. Stage 3 turns that into a disambiguation; inventing an
order here would make an arbitrary pick look like a decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from askai.compile.resolve.coverage import PeriodWindow
from askai.compile.resolve.generate import Subject, content_ngrams
from askai.compile.resolve.tuning import (
    content_overlap_weight,
    country_weight,
    entity_weight,
    grain_is_a_veto,
    minimum_ngram,
    period_coverage_is_a_veto,
    shape_words,
    unit_shape_weight,
)
from askai.domain.period import Grain
from askai.ports.resolution import Candidate, UnitShape

__all__ = [
    "Discriminated",
    "QuestionSignals",
    "Scored",
    "Signal",
    "SignalName",
    "Vetoed",
    "discriminate",
]


class SignalName(StrEnum):
    """The six signals of Story 2.4, named once and closed.

    Closed for the reason ``UnboundReason`` is: these names travel into the audit record
    and into a disambiguation's account of what it could not tell apart, and a signal
    invented at a call site is a signal with no weight in ``rules/`` and no reviewed
    account of what it means.
    """

    GRAIN = "grain"
    PERIOD_COVERAGE = "period-coverage"
    ENTITY = "group-or-sector"
    COUNTRY = "country"
    UNIT_SHAPE = "unit-shape"
    CONTENT_OVERLAP = "content-overlap"


@dataclass(frozen=True, slots=True)
class Signal:
    """One signal's verdict on one candidate, with the weight it carried.

    Kept per candidate rather than summed away, because a disambiguation has to be able to
    say *what it could not tell apart* and an audit record has to be able to say what
    decided. A total alone answers neither.
    """

    name: SignalName
    #: ``True`` when the question supplied something this signal could read. A signal the
    #: question said nothing about contributes nothing and is not evidence of agreement.
    spoke: bool
    agreed: bool
    weight: float

    @property
    def contribution(self) -> float:
        return self.weight if self.spoke and self.agreed else 0.0


@dataclass(frozen=True, slots=True)
class Vetoed:
    """A candidate removed by a veto, with the signal that removed it.

    Carried out of this stage rather than dropped silently: *"that indicator does not
    publish yearly figures"* is a far better refusal than *"nothing matched"*, and Story
    2.7's refusals cannot phrase it if the reason never leaves here.
    """

    candidate: Candidate
    by: SignalName


@dataclass(frozen=True, slots=True)
class Scored:
    """One surviving candidate, its discrimination score, and how it got there."""

    candidate: Candidate
    score: float
    signals: tuple[Signal, ...]

    #: The signals that told this *set* of candidates apart. A signal may have spoken
    #: about this candidate and still be absent here, because it said the same thing about
    #: every other one -- see :func:`_separating`.
    separating: frozenset[SignalName] = frozenset()

    @property
    def spoke(self) -> tuple[SignalName, ...]:
        """The signals that had something to say *and* separated the candidates."""
        return tuple(
            signal.name
            for signal in self.signals
            if signal.spoke and signal.name in self.separating
        )


@dataclass(frozen=True, slots=True)
class Discriminated:
    """What stage 2 produced: the survivors in order, and what it removed and why."""

    survivors: tuple[Scored, ...]
    vetoed: tuple[Vetoed, ...]

    @property
    def any_survived(self) -> bool:
        return bool(self.survivors)


@dataclass(frozen=True, slots=True)
class QuestionSignals:
    """What the compiler already extracted from the question, as stage 2 reads it.

    Every field is something another binder has *already* determined -- the grain and the
    periods from the period binder, the countries from the country binder -- rather than
    re-parsed here. AD-25 says this stage uses *"structural signals the compiler has
    already extracted"*, and re-reading the question would make this a second parser free
    to disagree with the first about what the reader said.
    """

    #: The interval the reader named, if any. FR-4's named grain.
    grain: Grain | None = None

    #: The calendar span the question asks about, or ``None`` when the reader named a
    #: deferred period -- *"the latest"* -- whose periods are a fact about the rows and
    #: not knowable here (AD-1). ``None`` leaves the coverage signal silent.
    window: PeriodWindow | None = None

    #: The countries the reader named, already resolved to ids by the country binder.
    countries: frozenset[str] = frozenset()

    #: The question's folded text, for the two signals that read words rather than
    #: resolved values -- the named sector and the asked unit shape.
    subject: Subject | None = None


def discriminate(
    candidates: tuple[Candidate, ...], asked: QuestionSignals
) -> Discriminated:
    """Apply the reviewed signals to *candidates*, deterministically and with no model.

    Order is total and stable: candidates sort by discrimination score descending, then by
    the order stage 1 delivered, then by ``detail_id``. So the same question produces the
    same order on every run (NFR-1, AD-17), and ties are *left* as ties -- stage 3 decides
    what a tie means, and breaking one here would hide an ambiguity behind an ordering.
    """
    survivors: list[tuple[int, Candidate, tuple[Signal, ...]]] = []
    vetoed: list[Vetoed] = []
    for position, candidate in enumerate(candidates):
        veto = _vetoed_by(candidate, asked)
        if veto is not None:
            vetoed.append(Vetoed(candidate=candidate, by=veto))
            continue
        survivors.append((position, candidate, _signals(candidate, asked)))

    separating = _separating(survivors)
    scored = [
        (
            position,
            Scored(
                candidate=candidate,
                score=sum(
                    signal.contribution for signal in signals if signal.name in separating
                ),
                signals=signals,
                separating=separating,
            ),
        )
        for position, candidate, signals in survivors
    ]
    # Score first, then **the order stage 1 delivered**, then the detail id.
    #
    # The middle key is the one that matters and it took a measurement to get right. Stage
    # 2 refines stage 1; it does not replace it. A question naming no grain, no period, no
    # country and no sector supplies nothing for the structural signals to read, and then
    # whatever the sort falls back on becomes the answer. Falling back on the detail id
    # orders by an accident of the export; falling back on stage 1 keeps the hybrid ranking
    # measured at 96% recall@1 on exactly-typed names. Over `names-v1`, ordering by id
    # dropped exact recall@1 from 96.0% to 80.0% and the overall figure to 63.4%.
    scored.sort(key=lambda entry: (-entry[1].score, entry[0], entry[1].candidate.detail_id))
    return Discriminated(
        survivors=tuple(entry for _position, entry in scored), vetoed=tuple(vetoed)
    )


def _separating(
    survivors: Sequence[tuple[int, Candidate, tuple[Signal, ...]]],
) -> frozenset[SignalName]:
    """The signals that actually told these candidates apart.

    **A signal with the same verdict for every candidate has discriminated nothing**, and
    this is the rule that makes the stage deserve its name. It is not a refinement; it is
    what the word means. A question about medical tourism reaches twenty candidates that
    are *all* in the Tourism sector, so "names the sector" is true of all twenty and
    separates none of them -- and a question naming a share reaches candidates that are all
    published in per cent.

    Letting such a signal contribute is worse than useless: every candidate gains the same
    amount, the ordering among them is then decided by whatever is left, and what is left
    is the lightest and least reliable signal there is. Measured over `names-v1`, counting
    non-separating signals cost exactly-typed Arabic names their rank-one answer in
    precisely this way -- `exact-ar-021` and `exact-ar-023`, where "السياحة" matched every
    tourism candidate's sector and "نسبة" matched every percentage candidate's unit.

    This also removes the need to prune the reviewed vocabularies against the corpus. A
    word like `share`, `total` or `نسبة` occurs in dozens of published names *and* is
    genuinely how a reader asks for a shape; the distinction cannot be made by editing the
    word list, because the word really does mean both things. It can be made here, by
    noticing that on this question the signal separated nothing.
    """
    separating: set[SignalName] = set()
    for name in SignalName:
        contributions = {
            next(
                (signal.contribution for signal in signals if signal.name is name),
                0.0,
            )
            for _position, _candidate, signals in survivors
        }
        # More than one distinct contribution means this signal placed the candidates in
        # at least two groups. One distinct value -- however large -- means it did not.
        if len(contributions) > 1:
            separating.add(name)
    return frozenset(separating)


# --------------------------------------------------------------------------- the vetoes


def _vetoed_by(candidate: Candidate, asked: QuestionSignals) -> SignalName | None:
    """The signal that rules *candidate* out, or ``None`` if none does.

    Both vetoes are silent unless the question named something *and* the candidate
    publishes enough for the absence to mean anything. A detail whose published periods
    are unknown -- an export that recorded none -- is not vetoed: a veto on missing
    evidence would remove candidates for a gap in the export rather than for a mismatch.
    """
    if asked.grain is not None and grain_is_a_veto():
        grains = candidate.facts.grains
        if grains and asked.grain not in grains:
            # FR-6 and Story 2.4: a yearly-only detail asked for monthly is *out*, not
            # ranked lower. The catalogue knows exactly which grains exist, so this is a
            # definite negative rather than weak evidence.
            return SignalName.GRAIN
    if asked.window is not None and period_coverage_is_a_veto():
        published = candidate.facts.periods
        if published and not asked.window.covered_by(published):
            # Publishes rows, and none of them inside the span the reader named at the
            # interval they named it at. The catalogue knows that definitely, so this is
            # a candidate that cannot answer the question as asked rather than one that
            # answers it less well.
            return SignalName.PERIOD_COVERAGE
    return None


# -------------------------------------------------------------------------- the evidence


def _signals(candidate: Candidate, asked: QuestionSignals) -> tuple[Signal, ...]:
    """The four weighted signals, each reporting whether it had anything to say."""
    return (
        _entity_signal(candidate, asked),
        _country_signal(candidate, asked),
        _unit_shape_signal(candidate, asked),
        _content_overlap_signal(candidate, asked),
    )


def _entity_signal(candidate: Candidate, asked: QuestionSignals) -> Signal:
    """Does the question name the group or sector this candidate's indicator belongs to?

    This is the signal that separates the eight details published as *Sector Contribution
    To GDP*: only the entity tells them apart, and a question naming *tourism* names one
    of them. Matched on the folded entity name appearing in the folded subject, because
    the reader writes *"the tourism sector"* and the export publishes *"Tourism"*.
    """
    weight = entity_weight()
    names = candidate.facts.entity_names
    subject = asked.subject
    if subject is None or not names:
        return Signal(name=SignalName.ENTITY, spoke=False, agreed=False, weight=weight)
    asked_text = subject.asked_folded
    agreed = any(name and name in asked_text for name in names)
    # The signal *spoke* only if it found the entity named. A question naming no sector
    # must not count against a candidate that has one -- every candidate has one.
    return Signal(name=SignalName.ENTITY, spoke=agreed, agreed=agreed, weight=weight)


def _country_signal(candidate: Candidate, asked: QuestionSignals) -> Signal:
    """Does this candidate publish a benchmark row for a country the reader named?

    Only 21 of 289 details declare a benchmark set. A candidate declaring none is
    therefore *silent* rather than disagreeing: reading an empty benchmark set as "does
    not match this country" would eliminate 268 details on any question naming one, which
    is the whole catalogue for a signal that was meant to be a refinement.
    """
    weight = country_weight()
    declared = candidate.facts.benchmark_countries
    if not asked.countries or not declared:
        return Signal(name=SignalName.COUNTRY, spoke=False, agreed=False, weight=weight)
    agreed = bool(asked.countries & declared)
    return Signal(name=SignalName.COUNTRY, spoke=True, agreed=agreed, weight=weight)


def _unit_shape_signal(candidate: Candidate, asked: QuestionSignals) -> Signal:
    """Does the shape the reader asked for match the shape this candidate publishes?

    Amount against share against rank -- *"how much"*, *"what share"*, *"where do we
    rank"*. Silent when the reader asked for no shape, and silent when the published unit
    is one the reviewed table does not classify: 54 details publish the unit ``NA``, and a
    detail whose unit the publisher did not record cannot be ruled in or out by it.
    """
    weight = unit_shape_weight()
    shape = candidate.facts.unit_shape
    subject = asked.subject
    if subject is None or shape is UnitShape.UNKNOWN:
        return Signal(name=SignalName.UNIT_SHAPE, spoke=False, agreed=False, weight=weight)
    wanted = _asked_shape(subject)
    if wanted is None:
        return Signal(name=SignalName.UNIT_SHAPE, spoke=False, agreed=False, weight=weight)
    return Signal(name=SignalName.UNIT_SHAPE, spoke=True, agreed=wanted is shape, weight=weight)


def _asked_shape(subject: Subject) -> UnitShape | None:
    """The shape the question asks for, or ``None`` when it names none.

    A question naming words for two different shapes names neither: *"what share of the
    total"* contains both a share word and an amount word, and guessing between them would
    make the signal fire on a coin toss. Returning ``None`` makes it silent, which is the
    honest reading of an ambiguous request.
    """
    words = set(subject.asked_folded.split())
    found = [shape for shape, vocabulary in shape_words().items() if words & vocabulary]
    if len(found) != 1:
        return None
    return found[0]


def _content_overlap_signal(candidate: Candidate, asked: QuestionSignals) -> Signal:
    """How much of the subject's content the candidate's best surface covers.

    Deliberately the *lightest* of the four, and deliberately graded rather than binary.
    Both choices were measured over `names-v1`.

    Graded, because containment is too strict to be useful: requiring a surface to hold
    **every** run of the subject was measured at 70.1% overall against 74.4% for the
    graded form, and it cost synonym recall@1 half its value (75.0% to 50.0%). A reader who
    says *"non-oil"* for *"Non-Hydrocarbon"* shares some of the subject and never all of
    it, which is exactly the case this signal should be able to speak about.

    Lightest, because it is the signal stage 1 has already used, and Story 2.13 measured it
    as unable to carry the distinction on its own. Its weight is small enough that any of
    the other three overrides it, so its job is to separate candidates the others were all
    silent about -- not to decide between candidates they spoke about.
    """
    weight = content_overlap_weight()
    subject = asked.subject
    if subject is None:
        return Signal(name=SignalName.CONTENT_OVERLAP, spoke=False, agreed=False, weight=weight)
    size = minimum_ngram()
    wanted = content_ngrams(subject.text, size)
    if not wanted:
        # The subject is shorter than one run, or is entirely generic measure nouns.
        return Signal(name=SignalName.CONTENT_OVERLAP, spoke=False, agreed=False, weight=weight)
    best = 0.0
    for surface in candidate.surfaces:
        runs = content_ngrams(surface, size)
        if runs:
            best = max(best, len(wanted & runs) / len(wanted))
    # Scaled into the weight rather than added as a raw share, so this signal cannot
    # outweigh one whose weight is larger however well the strings happen to overlap.
    return Signal(
        name=SignalName.CONTENT_OVERLAP, spoke=True, agreed=True, weight=weight * best
    )
