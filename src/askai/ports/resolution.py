"""``CandidatePort`` -- the candidates a question reaches, each carrying what tells it apart.

Purity: declarations only.

AD-25 runs resolution in three stages and forbids collapsing them into one scoring pass.
Stage 1 generates, stage 2 discriminates, stage 3 decides. This port is the seam between
stage 1 and stage 2, and its shape is the reason stage 2 can be **pure**.

**Why a candidate carries facts and not a connection.** Stage 2's signals are structural
-- *does this detail publish yearly rows spanning 2022-2025, in a GDP-shaped unit, for the
sector the reader named* -- and every one of them is a question about the catalogue rather
than about a figure. A port that answered them one at a time would put a live store inside
``compile/``, which AD-1 forbids and the import contract prevents. So the adapter assembles
the facts and the candidate arrives carrying them, and discrimination is arithmetic over
frozen values: testable with no index, no store and no model, which is what NFR-5 and
NFR-6 actually require of this stage.

**These are catalogue facts, never values.** ``CandidateFacts`` can say *that* a detail
publishes ``2024-Q1`` and never *what* it published for it. That is the same line
``CataloguePort`` draws -- ``published_grains`` exists, and nothing on it returns a row --
drawn again here because stage 2 needs coverage and must not acquire the ability to peek
at a figure while deciding which indicator the reader meant. A candidate holding an
``actual`` would make "the spec is bound before any data access" a discipline instead of a
property.

**One generation, one set of facts.** An implementation is expected to serve candidates
and facts out of the same immutable generation (AD-13, AD-20). A candidate scored against
one build and discriminated against another is a defect with no symptom: every number
looks reasonable and the answer is about a different indicator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from askai.domain.period import Grain, Period
from askai.messages.lang import Lang

__all__ = [
    "Candidate",
    "CandidateFacts",
    "CandidatePort",
    "MatchedSurface",
    "UnitShape",
]


class UnitShape(StrEnum):
    """What kind of quantity a published unit expresses.

    Closed, and deliberately coarse. Story 2.4 asks for *"unit shape (amount vs share vs
    rank across 28 published units)"* -- the distinction that separates *"how much does
    the economy produce"* from *"what share of it is non-oil"* from *"where do we
    rank"*. It is not a units library and does not try to be: the published layer spells
    the same shape 28 ways (``QAR``, ``bn QAR``, ``m USD``, ``Count``, ``jobs``), and what
    stage 2 needs is which of those questions the reader asked.

    ``UNKNOWN`` is a member rather than an absence because 54 of the export's details
    publish the unit ``NA``. An unknown shape must never *discriminate* -- it cannot rule a
    candidate out and cannot rule one in -- and having the member makes that a case the
    matching function handles rather than a ``None`` every call site must remember.
    """

    #: A magnitude in some unit: money, counts, masses, distances. The commonest shape.
    AMOUNT = "amount"

    #: A proportion -- per cent, percentage points. Answers *"what share"*.
    SHARE = "share"

    #: An ordinal position in a published league table. Answers *"where do we rank"*.
    RANK = "rank"

    #: A composite index in points, which is a level rather than a quantity or a share.
    INDEX = "index"

    #: A span of time published as the measured quantity -- months, hours, a season.
    DURATION = "duration"

    #: The published unit says nothing about shape, most often because it is ``NA``.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MatchedSurface:
    """Which published spelling carried a candidate, kept for finding 32's disclosure.

    Carried through the port rather than left in the adapter because an answer is entitled
    to say *the Arabic label matched*, and a candidate that arrived without it would have
    to be re-searched to find out.
    """

    kind: str
    lang: Lang
    text: str


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    """Everything stage 2 discriminates on, as frozen values.

    Every field is a fact about what the catalogue *publishes*, and no field is a figure.
    A field that is empty is genuinely empty -- a detail declaring no benchmark set, a
    unit the vocabulary does not classify -- and each signal treats its own emptiness as
    "this tells us nothing" rather than as a failed match, because a detail cannot be
    ruled out by a fact the export never recorded.
    """

    #: Every period this detail publishes a row for. Coverage, never content: this says a
    #: row exists and is silent about what is in it.
    periods: frozenset[Period] = frozenset()

    #: The countries this detail publishes a benchmark row for. Empty for the 268 of 289
    #: details that declare no benchmark set at all, which is the commonest case and is
    #: why an empty set may not be read as "no country matches".
    benchmark_countries: frozenset[str] = frozenset()

    #: The published shape of the detail's unit.
    unit_shape: UnitShape = UnitShape.UNKNOWN

    #: The entity the parent indicator belongs to -- a sector, a special entity, a
    #: project -- in each language, normalised by the caller's own fold. This is Story
    #: 2.4's "group or sector", and it is what tells eight details all named
    #: *Sector Contribution To GDP* apart.
    entity_names: tuple[str, ...] = ()

    #: The published classification of that entity: ``Sectors``, ``Enablers``,
    #: ``NationalIndicators`` and four others.
    classification: str = ""

    @property
    def grains(self) -> frozenset[Grain]:
        """The intervals this detail publishes at, read off the periods it publishes.

        Derived rather than stored, for FR-5's reason: a grain is a property of the
        periods that exist, and a separately stored grain is a second statement free to
        disagree with the first.
        """
        return frozenset(period.grain for period in self.periods)



@dataclass(frozen=True, slots=True)
class Candidate:
    """One detail a question reached in stage 1, with its score and its facts.

    ``score`` is stage 1's ranking quantity and is carried **only** so that stage 3 can
    report what generation thought. Stage 2 may not rank on it: Story 2.13 measured that
    where a wrong candidate outranked the right one its median score was 0.831 against a
    derived floor of 0.838, so by score alone a wrong top answer is indistinguishable from
    a right one. That measurement is the reason this stage exists, and re-sorting on
    ``score`` inside it would undo it.
    """

    detail_id: str
    indicator_id: str
    score: float
    matched: MatchedSurface
    facts: CandidateFacts

    #: The candidate's published **name** surfaces, folded -- its detail name, its label
    #: and its indicator's name. What the structural gate admits on.
    #:
    #: Kept apart from the definitions for the reason Story 2.2 keeps them apart when
    #: scoring: a name is what the thing is *called* and a definition is prose *about* it,
    #: and pooling them lets a coincidental word in a paragraph stand in for a name. That
    #: is not hypothetical -- measured over `names-v1`, a gate that pooled them admitted
    #: *Commodity Price Index* for "what is the average temperature in summer", because
    #: its definition contains the word "average".
    name_surfaces: tuple[str, ...] = ()

    #: Every published surface, names and definitions alike, folded. The light
    #: content-overlap signal reads these; the gate does not.
    surfaces: tuple[str, ...] = ()


@runtime_checkable
class CandidatePort(Protocol):
    """Stage 1 of AD-25, as ``compile/`` sees it: text in, candidates with facts out."""

    def candidates(
        self,
        subject: str,
        *,
        lang: Lang | None = None,
        limit: int | None = None,
    ) -> tuple[Candidate, ...]:
        """The details *subject* reaches, best first, each carrying what tells it apart.

        *subject* is the question with its period and request vocabulary already removed
        (R-158): stage 1 ranks on what the reader is asking *about*, and the words saying
        *when* they want it are handled by the period binder and must not also compete for
        subject salience.

        *lang* of ``None`` searches both languages, which is the answer path's normal
        case: a reader may name an indicator in either, and a question's language does not
        restrict which published surface may match it.

        *limit* of ``None`` takes the reviewed candidate count from ``rules/``. Returns an
        empty tuple when nothing resembles *subject* -- a well-founded absence, and stage
        3's refusal with a stated cause, not a degradation.
        """
        ...
