"""``UnpublishedCatalogPort`` -- what the CMS holds and never approved, as names only.

Purity: declarations only.

The base CMS layer carries 531 indicators; 189 of them reached readers. The other 342
are not junk -- 281 carry a real English name, and a reader can and will ask about one
of them (DATA-CONTRACT §1.4). Telling that reader "this exists but is not approved for
publication" is a materially better answer than "I don't know about that", because it
says the question was sensible and the gap is editorial.

That is the *only* thing the base layer is allowed to do here, and the port is shaped so
it cannot do anything else:

* the port returns :class:`UnpublishedName`, which has two fields and both are names.
  There is no id, no period, no country, no definition, no unit and no value on it, so
  an unapproved figure has nowhere to sit even if a caller wanted one;
* there is no method that takes a period, a country or a detail -- the port answers
  "does the catalogue hold this name" and "what names does it hold", and nothing else;
* it is read-only. Nothing on it writes, and the base layer has no table in the read
  model at all, so an unapproved row cannot be reached by a join from a published one.

``tests/test_ingest.py`` asserts that no type declared here is imported by any layer on
the answer path, which is the structural form of "no type from this port crosses into an
answer" while the answer package itself is still being built (Story 1.15).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["UnpublishedCatalogPort", "UnpublishedName"]


@dataclass(frozen=True, slots=True)
class UnpublishedName:
    """The bilingual name of something the CMS holds and did not publish.

    Deliberately two fields. A third -- an id, a date, a definition, a figure -- would
    be the first step of a convenience join, and the whole point of this type is that
    there is nothing on it to join *to*.
    """

    name_en: str
    name_ar: str


@runtime_checkable
class UnpublishedCatalogPort(Protocol):
    """Existence and names of unapproved catalogue entries. Read-only by construction."""

    def holds(self, name: str) -> bool:
        """Does the unapproved catalogue carry *name*, in either language?

        Compared under the engine's single text fold, so a reader's spelling meets the
        stored one the same way it does everywhere else.
        """
        ...

    def names(self) -> Sequence[UnpublishedName]:
        """Every unapproved entry that carries a name, in a stable order."""
        ...
