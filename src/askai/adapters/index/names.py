"""The ``names`` collection, built from the published export: one row per surface.

Purity: IO -- it reads the CMS export through the published-layer reader and nothing else.

This is the build side of Story 2.2. It turns the published layer into
:class:`~askai.adapters.index.surfaces.NameSurface` values and then into Story 2.1's
``IndexRow``s, and every decision it makes is about *not* pooling text:

**One vector per surface, never one per detail.** Each published spelling gets its own
row and therefore its own vector. Scoring takes the maximum across a detail's surfaces
(:mod:`askai.adapters.index.namesearch`), so a two-word Arabic name competes at its own
length instead of being averaged against a nine-word English one that happens to name the
same measurable.

**Every row points at a detail.** An indicator's catalogue name is emitted on the rows of
each of its details rather than on a row of its own. An indicator is not answerable --
it has no unit, no format and no series -- so a candidate that resolved only to one would
have to be re-resolved downstream, and AD-14's scope pre-filter would have nothing to
filter on. The cost is that an indicator with several details carries its name several
times; the benefit is that stage 1 hands stage 2 the thing stage 2 discriminates.

**A surface repeated is one surface.** Most details in this export publish a label
identical to their name, and about half publish a name identical to their indicator's.
Indexing those twice would buy nothing and would make the disclosure ambiguous -- two
rows, the same text, the same score, and no answer to *which surface matched*. So
duplicates are resolved on the engine's one normal form (AD-26), in the order
``NAME_SURFACES`` declares, and the most specific spelling keeps the row.

**The definition is carried, and kept apart.** It is indexed as its own kind so that it
can be scored in its own space and weighted down at the end. It is never appended to a
name: on this corpus concatenation cost four first-place answers and doubled the false
positives, which is recorded with the weight in ``rules/`` rather than here.

**Confidential indicators are not surfaced.** FR-50 is about lists and names as much as
about values, and a name in this collection is a name a reader can find. The filter is
the published priority vocabulary, read the way the ingest reads it, so the two cannot
disagree about what "confidential" means.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Final

from askai.adapters.index.surfaces import NAME_SURFACES, NameSurface, SurfaceKind
from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.export import CmsExport, Row
from askai.adapters.readmodel.ingest import CONFIDENTIAL
from askai.domain.normalise import normalise
from askai.messages.lang import Lang
from askai.ports.index import IndexRow

__all__ = ["NamesCorpusError", "name_rows", "name_surfaces"]

_INDICATOR_ID: Final = "PublishedIndicatorId"
_DETAIL_ID: Final = "PublishedIndicatorDetailId"
_PRIORITY_ID: Final = "IndicatorPriorityTypeId"

#: The published columns each language's surfaces are read from, in one table rather than
#: in two branches: the English and Arabic paths differ only in which column they read,
#: and a branch per language is how one of them quietly loses a surface.
_COLUMNS: Final = (
    (Lang.EN, "NameEN", "LabelEN", "DefinationEN"),
    (Lang.AR, "NameAR", "LabelAR", "DefinationAR"),
)


class NamesCorpusError(RuntimeError):
    """The export cannot be turned into a ``names`` corpus, and none was built.

    Raised rather than degraded to a partial collection, for the reason ``IndexBuildError``
    is: a names index missing rows nobody noticed answers confidently about a corpus that
    is not the published one.
    """


def _cell(row: Row, column: str) -> str:
    return row.get(column, "").strip()


def _confidential(export: CmsExport) -> frozenset[str]:
    """The priority-type ids FR-50 refuses. Empty is a legitimate answer for an export."""
    return frozenset(
        _cell(row, "Id")
        for row in export.reference_priority_types()
        if _cell(row, "NameEN") == CONFIDENTIAL
    )


def _answerable_indicators(export: CmsExport) -> Mapping[str, Row]:
    refused = _confidential(export)
    return {
        _cell(indicator, _INDICATOR_ID): indicator
        for indicator in export.published_indicators()
        if _cell(indicator, _PRIORITY_ID) not in refused
    }


def _surfaces_of(indicator: Row, detail: Row) -> Iterator[NameSurface]:
    """Every distinct published spelling of *detail*, in both languages.

    The fold decides what "distinct" means, and it is the engine's one ``normalise()``:
    a label differing from its name by a stray space, a hamza spelling or a casing is the
    same surface, and indexing it twice would split one reader-facing name into two
    vectors that each score a little worse than the one would have.
    """
    indicator_id = _cell(indicator, _INDICATOR_ID)
    detail_id = _cell(detail, _DETAIL_ID)
    for lang, name_column, label_column, definition_column in _COLUMNS:
        seen: set[str] = set()
        spellings = {
            SurfaceKind.DETAIL_NAME: _cell(detail, name_column),
            SurfaceKind.LABEL: _cell(detail, label_column),
            SurfaceKind.INDICATOR_NAME: _cell(indicator, name_column),
        }
        # Iterated in `NAME_SURFACES` order rather than in the order this literal happens
        # to be written, so the declared preference is the one that decides the winner.
        for kind in NAME_SURFACES:
            text = spellings[kind]
            folded = normalise(text)
            if not folded or folded in seen:
                continue
            seen.add(folded)
            yield NameSurface(
                indicator_id=indicator_id,
                detail_id=detail_id,
                kind=kind,
                lang=lang,
                text=text,
            )
        # Published prose, rendered to text here the way the ingest renders it -- markup
        # never reaches a reader (FR-64) and never reaches a vector either, or the index
        # would be scoring tag names.
        definition = published_text(_cell(detail, definition_column))
        folded_definition = normalise(definition or "")
        if folded_definition and folded_definition not in seen:
            yield NameSurface(
                indicator_id=indicator_id,
                detail_id=detail_id,
                kind=SurfaceKind.DEFINITION,
                lang=lang,
                # `definition` is not None: an empty render folds to nothing above.
                text=definition or "",
            )


def name_surfaces(export: CmsExport) -> tuple[NameSurface, ...]:
    """Every published surface in *export*, in export order, deduplicated per detail.

    A detail whose indicator is absent from the answerable catalogue is skipped rather
    than indexed against a missing parent: the read model refuses the same row for the
    same reason, and a name with no indicator behind it cannot be answered from.
    """
    indicators = _answerable_indicators(export)
    surfaces = [
        surface
        for detail in export.published_details()
        if (indicator := indicators.get(_cell(detail, _INDICATOR_ID))) is not None
        for surface in _surfaces_of(indicator, detail)
    ]
    _refuse_duplicate_ids(surfaces)
    return tuple(surfaces)


def _refuse_duplicate_ids(surfaces: Sequence[NameSurface]) -> None:
    """A row id occupied twice would be an ``IntegrityError`` three layers later.

    Checked here, where the message can name the detail and the kind, rather than at the
    insert, where it can only name a primary key.
    """
    seen: set[str] = set()
    for surface in surfaces:
        if surface.row_id in seen:
            raise NamesCorpusError(
                f"{surface.row_id} is published twice; a surface id is "
                "(indicator, detail, kind, language) and must identify one row"
            )
        seen.add(surface.row_id)


def name_rows(export: CmsExport) -> tuple[IndexRow, ...]:
    """*export*'s published surfaces as the rows a generation is built from."""
    return tuple(surface.row() for surface in name_surfaces(export))
