"""The source admission set -- the reader's provenance contract, as a closed type.

Purity: pure, imports nothing in-project.

AD-10 gives the reader a three-way choice of agent, and the system being replaced spent
that choice on **three routing paths with three sets of guards**: one for the approved
answer, one for the external one, and a third that composed a Combined answer its own
way. Three paths mean three places for provenance separation to be remembered, and the
third is the one that forgets -- a Combined-specific composition is by definition a
second way of building the approved half, free to drift from the first.

This module replaces the three paths with **one type**. ``SourceAdmission`` has exactly
three inhabitants -- ``{Approved}``, ``{External}``, ``{Approved, External}`` -- and the
enum has no fourth member to add one. A request carries an admission, one answer path
reads ``admits`` off it, and the approved package is composed by the same call in every
case that admits it. Provenance separation stops being a rule each path must remember
and becomes a property of the type the path is parameterised by (Story 9.1).

**Why a ``StrEnum`` and not a ``frozenset``.** A set of two members has four subsets, and
the empty one is representable: a request selecting nothing would be a value the type
admits and every reader of it has to reject. Selecting no source is not a narrower
question, it is no question, and the closed enum is how that stops being expressible at
all. ``of`` is the one door in, and a selection it cannot name is refused loudly rather
than narrowed silently -- FR-82's *"the engine never silently answers from a different
agent"* is the same sentence read from the other end.

**The engine's only authorisation is membership** (AD-24). It authenticates nothing, owns
no session and has no notion of a caller who may or may not select the external agent.
Checking that ``sources`` is within this closed set is the whole of what validating a
request means here; anything more would be an access decision the surrounding platform
already made.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

__all__ = ["AdmissionError", "PackageSource", "SourceAdmission"]


class PackageSource(StrEnum):
    """Where a package's content came from -- the spine's ``provenance`` field.

    A property of the whole package rather than of its elements, and distinct from an
    element's ``class``: the two answer different questions, and an approved package can
    hold a ``derived`` element while an external one never holds a ``measured`` one.

    It lives in ``domain/`` rather than beside ``AnswerPackage`` because ``api/`` and
    ``narrate/`` both have to name it -- the request says which sources it admits and the
    package says which one it came from -- and ``domain/`` is the only layer both may
    import. ``narrate.package`` re-exports it, so the layer that owns the package still
    reads as the layer that owns its provenance field.
    """

    APPROVED = "approved"
    """The published layer the engine holds its own copy of (AD-9a)."""

    EXTERNAL = "external"
    """A third-party source. Always caveated, unconditionally (FR-84, FR-88)."""


class AdmissionError(ValueError):
    """A selection of sources that is not one of the three admissions.

    A ``ValueError`` so that the one place it is raised from -- request parsing -- turns
    it into a 4xx without the edge having to translate it. An out-of-set selection is a
    malformed request, never a request quietly answered from a smaller set: narrowing
    ``{Approved, Oxford}`` to ``{Approved}`` would be the engine deciding which agent the
    reader meant, which is exactly what FR-82 forbids.
    """


class SourceAdmission(StrEnum):
    """The set of sources a request admits. Three members, and there is no fourth.

    Closed by construction rather than by validation: the three members *are* the three
    admissible sets, so a value of this type is already authorised and nothing downstream
    re-checks it. ``admits`` is the only way to get from an admission to the sources it
    covers, which is what makes "one answer path" a fact about the call graph -- the path
    iterates a tuple it was handed and has no branch naming a particular admission.

    The values are the wire's own spelling so a record or a log carries the reader's
    choice in the words the reader made it in.
    """

    APPROVED_ONLY = "approved"
    """The approved published data alone -- the default, and the answer that can be
    defended in front of the Council without a caveat."""

    EXTERNAL_ONLY = "external"
    """The external agent alone. Nothing approved is composed, and the external half
    carries its unconditional caveat as it always does."""

    BOTH = "approved+external"
    """Combined: two answers side by side, never one blended one (AD-10, FR-84). The
    approved half is the *same* package ``APPROVED_ONLY`` would have produced."""

    @property
    def admits(self) -> tuple[PackageSource, ...]:
        """The sources this admission covers, approved first (FR-84).

        Ordered here as well as in ``respond/`` because the two orderings answer
        different questions -- this is the order the packages are *built* in, and that
        one is the order they are returned in -- and an answer whose construction order
        and return order disagree is one whose audit record lists its rows in an order
        the response does not.
        """
        match self:
            case SourceAdmission.APPROVED_ONLY:
                return (PackageSource.APPROVED,)
            case SourceAdmission.EXTERNAL_ONLY:
                return (PackageSource.EXTERNAL,)
            case SourceAdmission.BOTH:
                return (PackageSource.APPROVED, PackageSource.EXTERNAL)

    def admits_source(self, source: PackageSource) -> bool:
        """Whether *source* is inside this admission. The whole of the authorisation."""
        return source in self.admits

    @classmethod
    def of(cls, sources: Iterable[PackageSource]) -> SourceAdmission:
        """The admission naming exactly *sources*, or ``AdmissionError``.

        Order and repetition are not part of the identity of a set, so ``["external",
        "approved"]`` and ``["approved", "approved", "external"]`` name the same
        admission -- a client quirk, answered once. An empty selection names none of the
        three and is refused here rather than defaulted to the approved layer: a default
        would answer a request that never asked anything.
        """
        selected = frozenset(sources)
        for admission in cls:
            if frozenset(admission.admits) == selected:
                return admission
        named = ", ".join(sorted(str(source) for source in selected)) or "nothing"
        offered = ", ".join(
            "{" + ", ".join(source.value for source in admission.admits) + "}"
            for admission in cls
        )
        raise AdmissionError(
            f"the sources selected ({named}) are not one of the three admissions "
            f"({offered}); a selection outside the closed set is a malformed request, "
            "never a request answered from a narrower set the reader did not choose"
        )
