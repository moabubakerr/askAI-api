"""``AnswerPackage`` -- the unit of an answer, and the only layer allowed to build one.

Purity: pure.

AD-10: *"Packages are constructed in one layer (``narrate/``); the response layer may
order and concatenate packages but never mutate or reach inside one."* Both halves are
structural rather than promised.

**Constructed in one layer.** The type is declared here, in ``narrate/``, and
``respond/`` is forbidden by an ``import-linter`` contract from importing ``narrate`` or
``assemble`` at all -- so the layer that orders packages cannot name the type it orders,
let alone build one. A response layer that cannot say ``AnswerPackage`` cannot reach into
one either; that is the same fact seen twice.

**Never mutated.** The package is frozen and every field is a tuple. There is no
``add_element``, no ``with_caveat`` and no ``merge``, because a merge is the specific
thing AD-10 forbids: an approved package and an external one are returned side by side,
ordered, so a reader can always see which half is which. Two packages blended into one
lose exactly the distinction FR-96 exists to keep.

**Structured only, permanently.** This epic composes elements and no prose (Epic 8 adds
the narration, behind a guard). The package therefore has no ``prose`` field that is
merely empty today: NFR-8 makes the no-prose answer the state the system falls back to
whenever the model is unavailable, so it is a supported shape rather than a stage. A
field waiting to be filled would invite a reader of the JSON to treat its absence as a
fault.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.roles import Placed
from askai.compile.binding import Binding
from askai.domain.degradation import Degradation
from askai.domain.spec import QuerySpec
from askai.execute.value import PeriodResolution

__all__ = ["AnswerPackage", "Chartable", "PackageKind", "PackageSource"]


class PackageSource(StrEnum):
    """Where a package's content came from -- the spine's ``provenance`` field.

    A property of the whole package rather than of its elements, and distinct from an
    element's ``class``: the two answer different questions, and an approved package can
    hold a ``derived`` element while an external one never holds a ``measured`` one.
    """

    APPROVED = "approved"
    """The published layer the engine holds its own copy of (AD-9a)."""

    EXTERNAL = "external"
    """A third-party source. Always caveated, unconditionally (FR-84, FR-88)."""


class PackageKind(StrEnum):
    """What the package *is*. Closed, and the corpus asserts on it.

    Three members, not two. A refusal says the published data cannot answer the question
    as asked; a clarification says the reader has not yet said enough to be answered. An
    engine with only "answer" and "not answer" has to choose one of those wordings for
    both, and it will choose the wrong one on whichever case is commoner.
    """

    ANSWER = "answer"
    REFUSAL = "refusal"
    CLARIFICATION = "clarification"


@dataclass(frozen=True, slots=True)
class Chartable:
    """Whether this package can be charted, and how -- the client's rendering hint.

    Epic 1 answers single figures, and one figure is not a chart, so ``available`` is
    false and the view lists are empty. The block is on the package anyway because its
    absence and its emptiness mean different things to a client: absent would be "this
    engine does not say", empty is "this engine says no".
    """

    available: bool = False
    default_view: str | None = None
    alternate_views: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.available and (self.default_view or self.alternate_views):
            raise ValueError(
                "a package that is not chartable names no views; offering a view for a "
                "chart that cannot be drawn is a client-side failure with a server-side "
                "cause"
            )


@dataclass(frozen=True, slots=True)
class AnswerPackage:
    """One answer, complete: what was asked, what was found, and what went wrong.

    Frozen, with tuples throughout. ``respond/`` receives these and puts them in an
    order; nothing downstream of here changes one, and the type offers no way to.
    """

    source: PackageSource
    kind: PackageKind
    spec: QuerySpec
    bindings: tuple[Binding, ...]
    #: What ``execute/`` resolved a deferred period to, so the answer and the audit
    #: record state the same period rather than each deciding one (FR-8, AD-16).
    resolution: PeriodResolution | None = None
    elements: tuple[Placed, ...] = ()
    chartable: Chartable = Chartable()
    #: Unconditional on an external package (FR-84, FR-88); ``None`` on an approved one.
    caveat: str | None = None
    #: What a refusal or a clarification says, in the reader's language, composed from
    #: the bilingual catalogue. ``None`` on an answer, which says what it did through
    #: its elements instead. It is a field rather than an element because an element
    #: cannot exist without a ``source_ref`` (AD-6), and a question that bound no detail
    #: has no row to point at -- a refusal has no provenance, by construction.
    reason: str | None = None
    degradations: tuple[Degradation, ...] = ()
    #: The published rows this package was computed from, for the audit record (AD-16).
    row_ids: tuple[str, ...] = ()
    #: The rules that took part, by id. Ids only: the statements live in ``rules/``, and
    #: copying one here would be a second place for it to drift.
    rules_fired: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.source is PackageSource.EXTERNAL) and not self.caveat:
            raise ValueError(
                "an external package carries a caveat unconditionally (FR-84, FR-88); "
                "there is no external content the reader is not entitled to be warned "
                "about"
            )
        if self.kind is PackageKind.ANSWER and not self.elements:
            raise ValueError(
                "an answer is its elements; a package with none is a refusal or a "
                "clarification, and saying which is the whole of what it owes the reader"
            )
        if self.kind is not PackageKind.ANSWER and not self.reason:
            raise ValueError(
                "a refusal or a clarification states its reason; an unexplained nothing "
                "is indistinguishable from the failure AD-15 separates it from"
            )
