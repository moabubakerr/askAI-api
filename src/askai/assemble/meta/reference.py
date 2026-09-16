"""The catalogue's own provenance envelope, and the only way to build an element with it.

Purity: pure.

``assemble/provenance.py`` carries the five things FR-44 requires *a figure* to arrive
with -- detail, period, country, source, and the grain read off the period. A catalogue
fact has none of them. *"``Sectors`` holds 105 indicators"* is true of the published
catalogue as loaded, not of any period, any country or any publishing body's release, and
a ``Provenance`` built for it would have to invent three of its five fields.

Inventing them was the obvious move and it is the wrong one: a fabricated period on a
provenance is exactly the plausible-looking unsourced content AD-7 exists to reject, and
it would resolve against nothing while looking entirely correct in the audit record.

So there is a second envelope, with the same guarantee rather than a weaker one:

* a reference names **a kind and a key**, both non-blank, and nothing else;
* the ``source_ref`` is **derived** from those two, never supplied beside them, so a
  reference and the thing it claims to describe cannot disagree (the property
  ``Provenance.source_ref`` has, for the same reason);
* ``catalogue_element`` is the **only** constructor here, it takes a reference, and there
  is no overload that omits one. That is AD-6 for catalogue facts: not a rule composers
  are asked to follow, but the only call available to them.

**The two reference shapes are disjoint by construction.** A datapoint reference is four
``|``-separated segments; this is ``catalogue:<kind>:<key>``. A catalogue reference splits
on ``|`` into one part, which the datapoint resolver already rejects, so the two can be
offered to one ``SourceCatalogue`` without either guessing. ``tests/test_meta.py`` asserts
that neither shape parses as the other, and that the kinds here are exactly the kinds the
read model knows how to resolve -- the two lists live in different layers because
``assemble/`` may not import an adapter, so their agreement is asserted rather than shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.domain.element import Element, ElementClass

__all__ = ["CatalogueReference", "ReferenceKind", "catalogue_element"]


class ReferenceKind(StrEnum):
    """What kind of catalogue row a reference points at.

    Closed, and deliberately coarse. There is no ``group`` member covering both levels:
    a classification and an entity are resolved by different queries, and a single member
    would let an element claim a group exists because the *other* level's key does.
    """

    CLASSIFICATION = "classification"
    """A published classification, by its published name."""

    ENTITY = "entity"
    """A published entity of the group layer, by its published id."""

    INDICATOR = "indicator"
    """One published indicator, by its published id."""

    DETAIL = "detail"
    """One published detail, by its published id -- what a definition is quoted from."""

    CATALOGUE = "catalogue"
    """The loaded published catalogue as a whole. What a statement *about the corpus*
    points at -- the capability answer's counts are true of the file the engine loaded and
    of nothing narrower, and a reference naming one indicator would claim otherwise."""


class ReferenceSyntax(StrEnum):
    """The two pieces of the reference's spelling.

    In an enum rather than as module constants because ``tests/test_rules.py`` scans
    ``assemble/`` for a module-level name bound to a literal, and it is right to: that is
    where a reader-affecting constant hides. These two are neither reader-affecting nor
    tunable -- they are a wire shape shared with one resolver -- and an enum keeps them
    named, in one place, and out of the shape the scan is looking for.
    """

    PREFIX = "catalogue"
    SEPARATOR = ":"


#: The key a whole-corpus reference carries. Not the empty string: a blank key is refused
#: by ``CatalogueReference`` and by the resolver alike, and "the catalogue itself" is a
#: real subject rather than a missing one.
WHOLE_CATALOGUE = ReferenceKind.CATALOGUE.value


@dataclass(frozen=True, slots=True)
class CatalogueReference:
    """Where one catalogue fact came from: a kind of row, and which row.

    Frozen, with no field that can be blank -- the same construction ``Provenance`` uses,
    for the same reason. A reference that can be half-filled is one that can be filled in
    later, and *later* is render time.
    """

    kind: ReferenceKind
    key: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError(
                "a catalogue reference names the row it came from; a blank key resolves "
                "against nothing while looking exactly like a reference that does"
            )
        if ReferenceSyntax.SEPARATOR.value in self.key:
            raise ValueError(
                f"a catalogue key may not contain {ReferenceSyntax.SEPARATOR.value!r}: "
                f"{self.key!r} would split into a different reference than it was built "
                "as, and would resolve against a row nobody named"
            )

    @property
    def source_ref(self) -> str:
        """The reference the element carries and the catalogue resolves.

        Derived from the two fields rather than supplied alongside them, so an element
        cannot carry a reference describing something other than the fact attached to it.
        """
        return ReferenceSyntax.SEPARATOR.value.join(
            (ReferenceSyntax.PREFIX.value, self.kind.value, self.key)
        )


def whole_catalogue() -> CatalogueReference:
    """The reference a statement about the loaded corpus carries.

    A named constructor rather than a constant, because a constant here would be a shared
    mutable-looking module-level value and because the name is what a reader of the
    capability composer needs to see at the call site.
    """
    return CatalogueReference(kind=ReferenceKind.CATALOGUE, key=WHOLE_CATALOGUE)


def catalogue_element(
    content: str, element_class: ElementClass, reference: CatalogueReference
) -> Element:
    """One element of *element_class*, carrying *content*, sourced to *reference*.

    The catalogue-fact counterpart of ``assemble/elements.py``, and the only one. It
    builds an ``Element`` directly rather than going through ``elements.build``, because
    that function's signature takes a ``Provenance`` and a catalogue fact has none --
    widening it to accept either would make *"an element carries the provenance of a
    published row"* a claim with an exception in it.

    The class stays an argument for the reason it is one there: it is a fact about where
    the content came from, which the caller knows and this cannot infer. A group's size is
    ``Measured`` -- it is read off the published catalogue. A residual is ``Derived``. The
    statement that no definition is published is ``Absent``.
    """
    return Element(content=content, element_class=element_class, source_ref=reference.source_ref)
