"""The base CMS layer, as names and existence only. It has no table and never will.

Purity: IO.

342 of the CMS's 531 indicators were never approved, and 281 of those carry a real
English name -- *"Classified Hotels (%)"*, *"The Rate of Volunteer Work"*. A reader will
ask about one. Answering *"this exists in the CMS but is not approved for publication"*
is a better refusal than *"I don't know about that"*, because it separates an editorial
gap from a failure of understanding (DATA-CONTRACT §1.4).

That is the whole of what the base layer is for here. It is loaded into memory as
:class:`~askai.ports.unpublished_catalogue.UnpublishedName` values -- two name fields
and nothing else -- and written to no table, so there is no row for a published query to
join to and no unapproved figure, period or definition anywhere in the read model.

Names are matched under the domain's single fold, so a reader's spelling meets a stored
one exactly as it does on the published side; a second fold here is the defect that
package exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from askai.adapters.readmodel.export import CmsExport, Row
from askai.domain.normalise import normalise
from askai.domain.text import is_published_text
from askai.ports.unpublished_catalogue import UnpublishedName

__all__ = ["UnpublishedCatalog"]


def _cell(row: Row, column: str) -> str:
    return row.get(column, "").strip()


@dataclass(frozen=True, slots=True)
class UnpublishedCatalog:
    """A read-only ``UnpublishedCatalogPort`` over the export, held in memory.

    Built once and frozen. There is no method here that writes, and no constructor that
    takes a connection, so this cannot become the back door through which the base layer
    reaches a database file.
    """

    entries: tuple[UnpublishedName, ...]
    by_name: Mapping[str, UnpublishedName]

    @classmethod
    def from_export(cls, export: CmsExport) -> UnpublishedCatalog:
        """Everything in the CMS catalogue that no published indicator maps back to.

        The published layer records the base id it came from, so "unapproved" is the
        complement of that set rather than a flag -- the base layer's own ``IsActive``
        and ``IsDeleted`` are ``True`` and ``False`` on all 531 rows and carry no signal.
        """
        published = {
            _cell(row, "SourceIndicatorId").casefold() for row in export.published_indicators()
        }
        entries: list[UnpublishedName] = []
        for row in export.base_indicators():
            if _cell(row, "Id").casefold() in published:
                continue
            name_en, name_ar = _cell(row, "NameEN"), _cell(row, "NameAR")
            # 61 base rows carry a blank English name. An entry with no name in either
            # language cannot be recognised or offered, so it is not an entry.
            if not is_published_text(name_en) and not is_published_text(name_ar):
                continue
            entries.append(UnpublishedName(name_en=name_en, name_ar=name_ar))

        ordered = tuple(sorted(entries, key=lambda entry: (entry.name_en, entry.name_ar)))
        index: dict[str, UnpublishedName] = {}
        for entry in ordered:
            for spelling in (entry.name_en, entry.name_ar):
                folded = normalise(spelling)
                if folded:
                    index.setdefault(folded, entry)
        return cls(entries=ordered, by_name=index)

    def holds(self, name: str) -> bool:
        """Does the unapproved catalogue carry *name*, in either language?"""
        return normalise(name) in self.by_name

    def names(self) -> Sequence[UnpublishedName]:
        """Every unapproved entry that carries a name, ordered by its English spelling."""
        return self.entries
