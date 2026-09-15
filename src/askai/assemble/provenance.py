"""Provenance, and the point at which an element that has none is refused.

Purity: pure. Asks one question through ``ports/`` and imports no adapter.

Two things live here, and they are the two halves of AD-6 and AD-7.

**What provenance *is*.** ``Provenance`` carries the five things FR-44 requires a figure
to arrive with -- the detail, the period, the country scope, the publishing source, and
the grain. The grain is a property read off the period rather than a field beside it,
because a period string carries its grain with no exceptions and two of them can
disagree where only one cannot. The country is ``None`` for national scope and never a
blank string: national scope is the *absence* of a country (AD-5), and a blank that
could be compared, joined or filtered on is the shape that silently drops the home
country from its own comparison.

**What happens when it does not resolve.** ``admit`` asks the ``SourceCatalogue`` port
whether an element's ``source_ref`` names something the loaded published layer actually
holds. An element that does not resolve is **refused with a typed ``Degradation``**, and
the refusal travels on the result beside the elements that were admitted -- never
through an ambient collector (AD-15), and never as a quiet ``continue``. A silent drop
would leave a shorter answer that reads exactly like a complete one, which is the
failure AD-7 exists to make impossible rather than unlikely.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from askai.domain.degradation import Degradation
from askai.domain.element import Element
from askai.domain.period import Grain, Period
from askai.ports.provenance_source import SourceCatalogue

__all__ = [
    "Admitted",
    "Assembled",
    "Provenance",
    "ProvenanceFailure",
    "Refused",
    "admit",
    "admit_all",
]


class ProvenanceFailure(StrEnum):
    """Why ``assemble/`` refused an element.

    A named kind rather than a message, because Story 1.17 counts these and a count over
    free text is a count of typos. It is spelled here and not in ``domain/`` for the same
    reason ``Degradation.kind`` is still a plain string there: the closed taxonomy is
    1.17's to draw, and this is the one member ``assemble/`` can produce today.
    """

    UNRESOLVED_SOURCE_REF = "unresolved_source_ref"


class Layer(StrEnum):
    """Where a degradation happened, so a rising rate has an address (AD-15)."""

    ASSEMBLE = "assemble"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where one figure came from: detail, period, country scope, publishing source.

    Frozen, and with no field that can be blank. A provenance that can be half-filled is
    a provenance that can be filled in later, and *later* is render time -- which is
    exactly the droppable label AD-6 replaced.
    """

    detail_id: str
    period: Period
    country: str | None
    source_id: str

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise ValueError("Provenance requires a detail; a figure with no detail is not one")
        if not self.source_id.strip():
            raise ValueError(
                "Provenance requires a publishing source; the catalogue publishes one for "
                "every row, and an element that cannot name its source cannot be defended"
            )
        if self.country is not None and not self.country.strip():
            raise ValueError(
                "Provenance takes None for national scope, never a blank country; a blank "
                "that can be compared or filtered on is how national scope becomes a "
                "country value again"
            )

    @property
    def grain(self) -> Grain:
        """Read off the period, never stored beside it."""
        return self.period.grain

    @property
    def is_national(self) -> bool:
        return self.country is None

    @property
    def source_ref(self) -> str:
        """The reference an element carries and the catalogue resolves.

        Derived from the five fields rather than supplied alongside them, so a reference
        and the provenance it claims to describe cannot disagree. National scope leaves
        its segment empty, which is what the published rows themselves do.
        """
        return "|".join((self.detail_id, self.period.value, self.country or "", self.source_id))


@dataclass(frozen=True, slots=True)
class Admitted:
    """The element resolved, and goes into the answer as constructed."""

    element: Element


@dataclass(frozen=True, slots=True)
class Refused:
    """The element did not resolve. It is not in the answer, and this says so."""

    degradation: Degradation


type Admission = Admitted | Refused


@dataclass(frozen=True, slots=True)
class Assembled:
    """What ``assemble/`` hands on: the elements that resolved, and every refusal.

    Both, always. A caller that wants only the elements must step over the refusals in
    order to ignore them, which is a line a reviewer can see.
    """

    elements: tuple[Element, ...]
    degradations: tuple[Degradation, ...]


def admit(element: Element, sources: SourceCatalogue) -> Admission:
    """Admit *element* if its ``source_ref`` resolves against *sources*, else refuse it."""
    if sources.resolves(element.source_ref):
        return Admitted(element=element)
    return Refused(
        degradation=Degradation(
            kind=ProvenanceFailure.UNRESOLVED_SOURCE_REF.value,
            where=Layer.ASSEMBLE.value,
            detail=(
                f"source_ref {element.source_ref!r} on a {element.element_class.value} "
                f"element does not resolve against the loaded published layer, so the "
                f"element was refused rather than shown unsourced"
            ),
        )
    )


def admit_all(elements: Iterable[Element], sources: SourceCatalogue) -> Assembled:
    """Admit each of *elements*, keeping every refusal.

    Nothing is dropped: every element that goes in comes out as either an element or a
    degradation, and ``tests/test_assemble.py`` asserts the two counts add up.
    """
    admitted: list[Element] = []
    refused: list[Degradation] = []
    for element in elements:
        match admit(element, sources):
            case Admitted(element=accepted):
                admitted.append(accepted)
            case Refused(degradation=degradation):
                refused.append(degradation)
    return Assembled(elements=tuple(admitted), degradations=tuple(refused))
