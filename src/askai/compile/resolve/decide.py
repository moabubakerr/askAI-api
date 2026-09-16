"""Stage 3 of AD-25: bind one, name the candidates, or refuse with a stated cause.

Purity: pure.

Three outcomes and no fourth, because the fourth is the defect. A resolver that could
also return *"the best guess"* is a resolver that answers confidently about an indicator
the reader did not ask for, and with 257 of 320 published names ambiguous it would do so
constantly.

**Disambiguation is a primary path, not an error path.** That is FR-2's wording and it is
a design instruction rather than a sentiment: the code below reaches a disambiguation by
the same route it reaches a binding, out of the same comparison, and there is no branch in
which disambiguating is handled as a failure of something else. On this corpus it is the
*expected* outcome for a large share of questions.

**The margin is a rule, and it is relative.** FR-2 requires the ambiguity threshold to be
reviewable and tunable in ``rules/`` rather than a code constant, and requires the value
to carry the labelled-set version it was derived from. It is expressed as a share of the
leader's own discrimination score rather than as an absolute, because that score is a sum
of whichever signals the question actually supplied: a question naming a sector, a country
and a unit shape produces larger numbers throughout than a bare name, and an absolute
margin would disambiguate freely on the first and never on the second.

**A refusal states which cause.** *"I hold nothing like that"*, *"everything that matched
was ruled out by something you said"*, and *"several things match and I cannot tell which
you mean"* are three different facts about the world, and a reader can act on each of them
differently. Collapsing them into one is the silent failure AD-15 exists to prevent. The
causes are a closed set of codes rather than sentences, for the reason ``UnboundReason``
is: composing reader-facing text is ``narrate/``'s job from the bilingual catalogue, and
English prose here could not be answered in Arabic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.compile.resolve.discriminate import Discriminated, Scored, SignalName
from askai.compile.resolve.tuning import ambiguity_margin, margin_labelled_set, maximum_offered

__all__ = [
    "Disambiguation",
    "Offered",
    "Refusal",
    "RefusalCause",
    "Resolution",
    "Resolved",
    "decide",
]


class RefusalCause(StrEnum):
    """Why resolution produced nothing. A closed set of codes, never a sentence.

    These are three of the six distinct refusals Story 2.7 phrases. They are declared here
    because this is the stage that *discovers* them, and a cause discovered here and
    invented again in the refusal module would be two statements free to drift.
    """

    #: Stage 1 found nothing sharing content with the question at all. The corpus holds
    #: nothing like it, so far as the published surfaces can say.
    NOTHING_MATCHED = "nothing-matched"

    #: Stage 1 found candidates and stage 2 vetoed every one of them. This is a *better*
    #: refusal than the first and must not be collapsed into it: the engine holds the
    #: indicator and cannot answer it as asked -- a grain it does not publish, a span it
    #: does not cover -- which is a fact the reader can act on by asking differently.
    ALL_CANDIDATES_RULED_OUT = "all-candidates-ruled-out"

    #: More candidates survived than a closed question can name. Eight details are
    #: published as *Sector Contribution To GDP*; offering all eight restates the problem
    #: rather than helping, so the tie is reported as too wide rather than truncated into
    #: a question that looks answerable and is not.
    TOO_MANY_TO_NAME = "too-many-to-name"


@dataclass(frozen=True, slots=True)
class Resolved:
    """Exactly one candidate survived and binds, as the resolved **detail**.

    A detail and never an indicator (FR-1, Story 2.5): an indicator has no unit, no format
    and no series, so binding one would defer the real resolution to a layer that has
    already lost the question.
    """

    detail_id: str
    indicator_id: str
    score: float

    #: Which published surface carried it, for finding 32's disclosure, and which signals
    #: had anything to say, so an audit record can state what actually decided.
    matched_surface: str
    decided_by: tuple[SignalName, ...]


@dataclass(frozen=True, slots=True)
class Offered:
    """One candidate named in a disambiguation."""

    detail_id: str
    indicator_id: str
    #: The published surface that matched, as the text to show the reader when the
    #: question is put. Carried from the index rather than re-read, so the reader is
    #: offered the spelling that actually matched.
    surface: str
    score: float


@dataclass(frozen=True, slots=True)
class Disambiguation:
    """Several candidates survived and none leads by the reviewed margin (FR-2).

    A primary path. The candidates are *named* so the question put to the reader is closed
    and specific -- Story 2.11's shape -- rather than an invitation to rephrase.
    """

    candidates: tuple[Offered, ...]

    #: The signals that spoke about at least one candidate. What a good clarifying
    #: question asks *about* is the thing that would have separated them, and the
    #: signals that stayed silent are exactly that thing.
    signals_that_spoke: tuple[SignalName, ...]


@dataclass(frozen=True, slots=True)
class Refusal:
    """Nothing binds, and the cause is stated (FR-38)."""

    cause: RefusalCause

    #: For ``ALL_CANDIDATES_RULED_OUT``, the signals that did the ruling out -- so the
    #: refusal can say *"that indicator does not publish yearly figures"* rather than
    #: *"nothing matched"*.
    vetoed_by: tuple[SignalName, ...] = ()


type Resolution = Resolved | Disambiguation | Refusal


def decide(discriminated: Discriminated) -> Resolution:
    """Turn stage 2's survivors into one of AD-25's three outcomes.

    Deterministic: the survivors arrive in a total order and the margin comes from
    ``rules/``, so the same question resolves to the same outcome on every run (NFR-1).
    """
    survivors = discriminated.survivors
    if not survivors:
        return _refused(discriminated)

    leader = survivors[0]
    contenders = _within_margin(survivors)
    if len(contenders) == 1:
        return Resolved(
            detail_id=leader.candidate.detail_id,
            indicator_id=leader.candidate.indicator_id,
            score=leader.score,
            matched_surface=leader.candidate.matched.text,
            decided_by=leader.spoke,
        )
    if len(contenders) > maximum_offered():
        return Refusal(cause=RefusalCause.TOO_MANY_TO_NAME)
    return Disambiguation(
        candidates=tuple(
            Offered(
                detail_id=scored.candidate.detail_id,
                indicator_id=scored.candidate.indicator_id,
                surface=scored.candidate.matched.text,
                score=scored.score,
            )
            for scored in contenders
        ),
        signals_that_spoke=tuple(
            dict.fromkeys(name for scored in contenders for name in scored.spoke)
        ),
    )


def _within_margin(survivors: tuple[Scored, ...]) -> tuple[Scored, ...]:
    """The leader, and every survivor close enough to it to be a genuine contender.

    Relative to the leader's own score, per ``R-RESOLVE-AMBIGUITY-MARGIN``. The zero case
    is handled explicitly rather than by the arithmetic: when *no* signal spoke about any
    candidate every score is zero, a relative margin is meaningless, and every survivor is
    equally unseparated -- which is a disambiguation, not a binding of whichever one
    happened to sort first.
    """
    leader = survivors[0]
    if leader.score <= 0.0:
        return survivors
    floor = leader.score * (1.0 - ambiguity_margin())
    return tuple(scored for scored in survivors if scored.score >= floor)


def _refused(discriminated: Discriminated) -> Refusal:
    """Why nothing survived -- which is two different facts, kept apart.

    A question that reached no candidate at all and a question whose every candidate was
    ruled out are different things to be told, and the second is much the more useful.
    """
    if discriminated.vetoed:
        return Refusal(
            cause=RefusalCause.ALL_CANDIDATES_RULED_OUT,
            vetoed_by=tuple(dict.fromkeys(entry.by for entry in discriminated.vetoed)),
        )
    return Refusal(cause=RefusalCause.NOTHING_MATCHED)


def margin_provenance() -> str:
    """The labelled set the ambiguity margin records, which FR-2 requires it to carry."""
    return margin_labelled_set()
