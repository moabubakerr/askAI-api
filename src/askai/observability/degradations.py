"""The closed degradation taxonomy, the tally that counts it, and the carriers.

Purity: pure -- it names kinds, counts values and wraps results. Nothing here does IO,
holds process state, or knows a store exists.

AD-15 asks three things of a soft failure, and this module supplies the three shapes
that make each one structural rather than remembered.

**Typed.** ``DegradationKind`` is the closed set. ``Degradation.kind`` is spelled
``str`` in ``domain/`` because ``domain/`` imports nothing in-project (AD-2) and the
field predates the taxonomy, so closure is enforced here instead, at the only two places
that matter: nothing is counted and nothing reaches the record unless its kind is a
member. ``classify`` raises on anything else rather than tallying it under an "other"
bucket, because a bucket named *other* is how a taxonomy stops being closed.
``tests/test_degradations.py`` scans every ``Degradation(...)`` construction under
``src/askai/`` and fails on a kind that is not a member, so a new producer either adds
its kind to this enum -- where a reviewer sees it -- or does not build.

**Counted.** ``Tally`` is a frozen value: counts per kind, built from the degradations a
result is already carrying, added to another tally by ``+``. It is deliberately not a
counter object anyone registers with. A module-level counter is precisely the ambient
collector AD-15 forbids -- two concurrent requests would count into each other, and
``assemble/`` could not be exercised in isolation. The count is *derived from the
carried value*, so a degradation that is not on the result is not counted anywhere,
which is the property that makes the count trustworthy.

**Carried, and distinguishable from absence.** ``Carried`` pairs a value with the
degradations that happened producing it, so a soft failure travels by return rather than
by side effect. ``Outcome`` is the other half of AD-15's clause: ``Found`` is a value,
``Absent`` is a well-founded nothing with its reason, and ``Failed`` is a component that
did not work, carrying at least one degradation. They are three states, not two, so the
findings-23/128/150 failure -- an error rendering as "no approved figures" -- cannot be
written: a caller matching on an ``Outcome`` must name ``Failed`` separately from
``Absent`` or the match is not exhaustive and ``mypy --strict`` says so.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from askai.domain.degradation import Degradation

__all__ = [
    "NO_DEGRADATIONS",
    "Absent",
    "Carried",
    "DegradationKind",
    "Failed",
    "Found",
    "Outcome",
    "Tally",
    "UnknownDegradationKind",
    "classify",
    "degradations_of",
    "degrade",
    "gather",
    "is_known_kind",
]


class DegradationKind(StrEnum):
    """Every soft failure this system may report, and nothing else.

    Closed on purpose. A free-text kind makes a count a count of typos, and makes
    "this rule stopped firing" indistinguishable from "this rule was never reached" --
    the exact confusion AD-15 exists to end. Each member names the thing that went
    wrong, never the message shown for it; the reader-facing wording is a message id
    resolved elsewhere, and two kinds may share one.

    Adding a member is a deliberate, reviewable act: it widens what the system admits
    is possible. Removing one is not -- an old record may hold it -- so a kind that
    falls out of use stays, deprecated in its comment rather than deleted.
    """

    #: ``assemble/`` refused an element whose ``source_ref`` did not resolve against the
    #: loaded published layer. AD-6: provenance is a construction precondition, so an
    #: unsourceable element is refused rather than shown bare.
    UNRESOLVED_SOURCE_REF = "unresolved_source_ref"

    #: No approved analyst commentary exists for a datapoint that otherwise answered.
    #: A genuine absence in the published layer, reported so the answer can say so.
    ANALYSIS_ABSENT = "analysis_absent"

    #: The model could not be reached or refused to produce. AD-15: loss of the model
    #: degrades prose only -- the structured answer is unaffected.
    MODEL_UNAVAILABLE = "model_unavailable"

    #: The external agent could not be reached. AD-15: degrade to the approved answer
    #: with the gap stated, never to a blended one that hides which half is missing.
    EXTERNAL_AGENT_UNAVAILABLE = "external_agent_unavailable"

    #: A guard discarded model output. AD-28: default is discard, and every discard is
    #: counted, so a rising rate surfaces a prompt or model problem early.
    GUARD_DISCARD = "guard_discard"

    #: A row was rejected during ingest of the published layer. AD-21: ingest rejections
    #: are surfaced with counts and examples, never swallowed.
    INGEST_REJECTION = "ingest_rejection"

    #: An adapter's own typed failure, converted at the boundary where AD-15 allows
    #: broad handling, so an IO fault arrives as a value rather than as a stack trace.
    ADAPTER_UNAVAILABLE = "adapter_unavailable"

    #: A rule the answer needed could not be applied. The motivating case: a rule that
    #: stopped firing now says so, instead of looking like one never reached.
    RULE_UNAVAILABLE = "rule_unavailable"


class UnknownDegradationKind(ValueError):
    """A degradation whose ``kind`` is outside the closed taxonomy.

    Raised rather than bucketed. Counting an unrecognised kind under *other* would let
    the set drift open one producer at a time, which is the failure this is here to stop.
    """


#: The member values, as a set, for the scans that ask "is this string a kind?" without
#: paying for an exception. Frozen -- it is read, never added to.
_KIND_VALUES: Final = frozenset(kind.value for kind in DegradationKind)


def is_known_kind(kind: str) -> bool:
    """Whether *kind* names a member of the taxonomy."""
    return kind in _KIND_VALUES


def classify(kind: str) -> DegradationKind:
    """The taxonomy member *kind* names, or raise.

    The one door between the ``str`` on ``Degradation`` and the closed set. Counting and
    recording both go through it, so an unrecognised kind cannot be quietly tallied.
    """
    if kind not in _KIND_VALUES:
        raise UnknownDegradationKind(
            f"{kind!r} is not a degradation kind; the taxonomy is closed and holds "
            f"{sorted(_KIND_VALUES)}. Add the member to DegradationKind -- where a "
            "reviewer sees it -- rather than widening the set at the call site."
        )
    return DegradationKind(kind)


def degrade(kind: DegradationKind, where: str, detail: str) -> Degradation:
    """Build a ``Degradation`` whose kind is a taxonomy member by construction.

    The preferred constructor for every producer. It exists because ``Degradation`` must
    keep a ``str`` field for ``domain/`` to stay import-free, and a typed front door is
    the way a producer gets the compiler's help anyway: ``degrade(DegradationKind.X,
    ...)`` will not build with a kind nobody declared, whereas ``Degradation(kind="x")``
    only fails later, at the scan.
    """
    if not where.strip():
        raise ValueError("a degradation needs the layer it happened in; AD-15 wants an address")
    if not detail.strip():
        raise ValueError(
            "a degradation needs its detail; a kind alone cannot reconstruct the decision"
        )
    return Degradation(kind=kind.value, where=where, detail=detail)


# ------------------------------------------------------------------------- the count


@dataclass(frozen=True, slots=True)
class Tally:
    """How many of each kind happened, as a value.

    Frozen and derived, never accumulated into. ``Tally.of`` reads the degradations a
    result is already carrying; ``+`` combines two results' tallies on the way up. There
    is no ``add`` and no ``reset``, because either would make this the shared mutable
    counter AD-15 rules out -- and a counter that a caller can reach is a counter two
    requests can corrupt.

    Kinds with a zero count are absent rather than present-as-zero: the tally says what
    happened, and the enum already says what could.
    """

    #: Sorted by kind value, so two tallies of the same multiset compare and hash equal.
    counts: tuple[tuple[DegradationKind, int], ...] = ()

    def __post_init__(self) -> None:
        kinds = [kind for kind, _ in self.counts]
        if kinds != sorted(kinds):
            raise ValueError("tally counts are held in kind order; build one with Tally.of")
        if len(set(kinds)) != len(kinds):
            raise ValueError("a tally holds one entry per kind; a repeated kind is two counts")
        for kind, count in self.counts:
            if count < 1:
                raise ValueError(
                    f"{kind.value} is tallied {count}; an absent kind is simply absent"
                )

    @classmethod
    def of(cls, degradations: Iterable[Degradation]) -> Tally:
        """Count *degradations* by kind, rejecting any kind outside the taxonomy."""
        totals: dict[DegradationKind, int] = {}
        for degradation in degradations:
            kind = classify(degradation.kind)
            totals[kind] = totals.get(kind, 0) + 1
        return cls(counts=tuple(sorted(totals.items(), key=lambda pair: pair[0].value)))

    @property
    def total(self) -> int:
        """How many degradations in all -- the number the record already reports."""
        return sum(count for _, count in self.counts)

    @property
    def kinds(self) -> tuple[DegradationKind, ...]:
        """The kinds that actually happened, in kind order."""
        return tuple(kind for kind, _ in self.counts)

    def count(self, kind: DegradationKind) -> int:
        """How many of *kind* happened; zero if none did."""
        for candidate, count in self.counts:
            if candidate is kind:
                return count
        return 0

    def as_mapping(self) -> Mapping[DegradationKind, int]:
        """A read-only view, for a metrics sink that wants a mapping."""
        return MappingProxyType(dict(self.counts))

    def __add__(self, other: Tally) -> Tally:
        """Combine two tallies -- how a count travels up a call chain without a collector."""
        totals: dict[DegradationKind, int] = dict(self.counts)
        for kind, count in other.counts:
            totals[kind] = totals.get(kind, 0) + count
        return Tally(counts=tuple(sorted(totals.items(), key=lambda pair: pair[0].value)))

    def __bool__(self) -> bool:
        return bool(self.counts)


#: The tally of nothing having gone wrong. A value, not a singleton anyone mutates.
NO_DEGRADATIONS: Final = Tally()


# ------------------------------------------------------------------------ the carrier


@dataclass(frozen=True, slots=True)
class Carried[T]:
    """A value and the degradations that happened producing it, travelling together.

    This is AD-15's "on the result value" made into a type. A function that can degrade
    returns ``Carried[T]``; its caller cannot take the value without the failures being
    in its hands, and the only way to lose one is to write the line that drops it.
    """

    value: T
    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        for degradation in self.degradations:
            classify(degradation.kind)

    @property
    def tally(self) -> Tally:
        """The per-kind count of what this result carries."""
        return Tally.of(self.degradations)

    @property
    def clean(self) -> bool:
        """Whether nothing went wrong producing this value."""
        return not self.degradations

    def also(self, *degradations: Degradation) -> Carried[T]:
        """The same value, carrying *degradations* as well."""
        return Carried(value=self.value, degradations=self.degradations + degradations)

    def map[U](self, transform: Callable[[T], U]) -> Carried[U]:
        """Transform the value, keeping every degradation collected so far."""
        return Carried(value=transform(self.value), degradations=self.degradations)

    def then[U](self, step: Callable[[T], Carried[U]]) -> Carried[U]:
        """Run a step that can itself degrade, concatenating what both carried.

        The whole point of the shape: a pipeline accumulates failures by returning
        them, so no stage needs to know where a shared list lives.
        """
        following = step(self.value)
        return Carried(
            value=following.value,
            degradations=self.degradations + following.degradations,
        )


def gather[T](results: Iterable[Carried[T]]) -> Carried[tuple[T, ...]]:
    """Collapse many carried results into one carrying every value and every failure.

    The fan-in counterpart of ``then``. Nothing is dropped: the degradation count of the
    result equals the sum of the parts', which ``tests/test_degradations.py`` asserts.
    """
    values: list[T] = []
    degradations: list[Degradation] = []
    for result in results:
        values.append(result.value)
        degradations.extend(result.degradations)
    return Carried(value=tuple(values), degradations=tuple(degradations))


# ------------------------------------------------------- failure is not absence


@dataclass(frozen=True, slots=True)
class Found[T]:
    """The component produced what was asked of it."""

    value: T


@dataclass(frozen=True, slots=True)
class Absent:
    """There is genuinely nothing -- and this is not a failure.

    *"No approved figures exist for that period"* is an ``Absent``. It carries its
    reason because "nothing" with no account of why is what an error used to look like.
    """

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                "an absence states why it is empty; an unexplained nothing is "
                "indistinguishable from the failure AD-15 separates it from"
            )


@dataclass(frozen=True, slots=True)
class Failed:
    """The component did not work. Never rendered as an absence.

    Non-empty by construction: a failure with no degradation would carry no kind, no
    address and no detail, and would be exactly the silent nothing this type exists to
    make unrepresentable.
    """

    degradations: tuple[Degradation, ...]

    def __post_init__(self) -> None:
        if not self.degradations:
            raise ValueError(
                "a failure carries at least one degradation; without one it is an "
                "absence wearing a different name"
            )
        for degradation in self.degradations:
            classify(degradation.kind)

    @property
    def tally(self) -> Tally:
        return Tally.of(self.degradations)


type Outcome[T] = Found[T] | Absent | Failed
"""Three states, so a component that broke can never be read as one that found nothing.

``mypy --strict`` refuses an inexhaustive match over these, so a caller that handles
``Found`` and ``Absent`` and forgets ``Failed`` does not build -- which is the
foreclosure, rather than a convention about how to write the ``else``.
"""


def degradations_of(outcome: Outcome[object]) -> tuple[Degradation, ...]:
    """What *outcome* failed with -- empty for a value and for a well-founded absence."""
    match outcome:
        case Failed(degradations=degradations):
            return degradations
        case Found() | Absent():
            return ()
