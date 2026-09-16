"""What a *surface* is, and how one is carried on an index row.

Purity: pure -- values and string encoding, no IO.

Story 2.2's whole point is that a reader names a thing in more than one way, and that
each of those ways is scored **in its own right**. An indicator detail publishes an
English name, an Arabic name, an English label, an Arabic label, and inherits its
indicator's English and Arabic names; a short Arabic name and a long English one are
different lengths, different scripts and different vocabularies, and averaging them into
one vector per detail makes the short one unfindable. So each surface is its own row with
its own vector, and the detail's score is the **maximum** across its surfaces.

**Why the kind travels in the row id.** ``IndexRow`` is Story 2.1's contract and carries
the four scope columns AD-14 pre-filters on and nothing else; a fifth column for the
surface kind would be a change to a port for the benefit of one collection. The id is
already documented there as opaque and composite -- *"a detail id, a datapoint key plus
field"* -- so this collection spells its ids
``<indicator id>|<detail id>|<kind>|<lang>`` and parses them back here, in the one module
that knows the grammar. Nothing else splits a row id.

That encoding is what makes finding 32's disclosure rule answerable: a candidate does not
merely score, it scores *because the Arabic label matched*, and an answer can say so.

**Which surfaces exist is read off the export, not assumed.** The acceptance criteria
name "indicator name, detail name, label, alias". The published layer of this export
carries the first three in both languages and publishes **no alias table at all** -- no
column, no reference file, nothing in ``P01``/``P02`` or the reference tables spells an
alternative name for an indicator. There is therefore no ``ALIAS`` kind here: inventing
one would put an empty surface in the enum and make a reader believe aliases were
searched. The definition is a kind of its own for the opposite reason -- it exists, it is
long, and it must never be pooled with a name (see :mod:`askai.adapters.index.namesearch`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from askai.messages.lang import Lang
from askai.ports.index import IndexRow

__all__ = [
    "DEFINITION_SURFACES",
    "NAME_SURFACES",
    "SURFACE_ID_SEPARATOR",
    "NameSurface",
    "SurfaceIdError",
    "SurfaceKind",
    "surface_of",
    "surface_row_id",
]

#: Chosen because every id it joins is a published GUID, and a GUID contains hyphens but
#: never this. A separator that can occur inside a part is a parser that works until the
#: day it silently returns the wrong detail.
SURFACE_ID_SEPARATOR: Final = "|"

_PARTS: Final = 4


class SurfaceIdError(ValueError):
    """A ``names`` row id is not of the form this collection writes.

    Raised rather than guessed at. A row whose id cannot be parsed cannot be attributed
    to a detail, and a candidate attributed to the wrong detail is the failure the whole
    resolution path exists to prevent.
    """


class SurfaceKind(StrEnum):
    """A published, reader-facing way of naming one indicator detail.

    Closed, and closed against the export rather than against the epic's prose: each
    member below is a column that exists and is non-empty somewhere in the published
    layer. See this module's docstring for why there is no ``ALIAS``.
    """

    #: ``P02.NameEN`` / ``P02.NameAR`` -- the measurable's own name, the most specific
    #: surface there is, and the one a disclosure should prefer to name.
    DETAIL_NAME = "detail_name"

    #: ``P02.LabelEN`` / ``P02.LabelAR`` -- what the chart axis and the tile show. Equal
    #: to the detail name on most rows of this export and genuinely different on some.
    LABEL = "label"

    #: ``P01.NameEN`` / ``P01.NameAR`` -- the catalogue name of the indicator the detail
    #: belongs to. Carried on the detail's own rows, so a match resolves to a measurable
    #: rather than to a heading with no unit and no series.
    INDICATOR_NAME = "indicator_name"

    #: ``P02.DefinationEN`` / ``P02.DefinationAR`` (the export's spelling). A definition
    #: is not a name: it is prose, it is long, and it is scored in a **separate space**
    #: that is weighted down and combined at the end, never concatenated onto a name.
    DEFINITION = "definition"


#: The surfaces that are *names*, in the order a duplicate is resolved: the most specific
#: spelling wins the row, so a detail whose label repeats its name keeps one vector and
#: discloses the more informative kind.
NAME_SURFACES: Final = (
    SurfaceKind.DETAIL_NAME,
    SurfaceKind.LABEL,
    SurfaceKind.INDICATOR_NAME,
)

#: The other scoring space. A tuple rather than a bare member so the two spaces are
#: declared the same way and a third kind cannot join one by accident.
DEFINITION_SURFACES: Final = (SurfaceKind.DEFINITION,)


@dataclass(frozen=True, slots=True)
class NameSurface:
    """One reader-facing spelling of one detail, in one language.

    Frozen: a surface is a fact about the published export at build time, and the row
    that carries it is immutable for the life of the generation it lives in.
    """

    indicator_id: str
    detail_id: str
    kind: SurfaceKind
    lang: Lang
    text: str

    def __post_init__(self) -> None:
        for part in (self.indicator_id, self.detail_id):
            if not part.strip():
                raise SurfaceIdError("a surface names an indicator and a detail; neither is blank")
            if SURFACE_ID_SEPARATOR in part:
                raise SurfaceIdError(
                    f"{part!r} contains {SURFACE_ID_SEPARATOR!r}, which is the separator "
                    "a surface id is built from; the id could not be parsed back"
                )

    @property
    def row_id(self) -> str:
        """The id this surface occupies in the ``names`` collection."""
        return surface_row_id(self.indicator_id, self.detail_id, self.kind, self.lang)

    @property
    def is_definition(self) -> bool:
        """Whether this surface belongs to the definition scoring space rather than the name one."""
        return self.kind in DEFINITION_SURFACES

    def row(self) -> IndexRow:
        """This surface as the row Story 2.1's build indexes.

        ``detail_id`` is populated on every ``names`` row, including the ones carrying an
        indicator's name: AD-14's pre-filter is only available on a column that is there,
        and a candidate the discrimination stage cannot scope is a candidate it cannot
        discriminate.
        """
        return IndexRow(
            id=self.row_id,
            lang=self.lang,
            text=self.text,
            detail_id=self.detail_id,
        )


def surface_row_id(indicator_id: str, detail_id: str, kind: SurfaceKind, lang: Lang) -> str:
    """The ``names`` row id for one surface. The only place the grammar is written."""
    return SURFACE_ID_SEPARATOR.join((indicator_id, detail_id, kind.value, lang.value))


def surface_of(row: IndexRow) -> NameSurface:
    """The surface *row* carries, parsed back out of its id.

    Refuses rather than degrades: a row from another collection, or a hand-written row,
    has no surface and must not be given one by falling back to a default kind.
    """
    parts = row.id.split(SURFACE_ID_SEPARATOR)
    if len(parts) != _PARTS:
        raise SurfaceIdError(
            f"{row.id!r} is not a names row id; the collection writes "
            f"<indicator>{SURFACE_ID_SEPARATOR}<detail>{SURFACE_ID_SEPARATOR}"
            f"<kind>{SURFACE_ID_SEPARATOR}<lang>"
        )
    indicator_id, detail_id, kind, lang = parts
    try:
        surface_kind = SurfaceKind(kind)
    except ValueError as error:
        raise SurfaceIdError(f"{row.id!r} names surface kind {kind!r}, which is not one") from error
    if lang != row.lang.value:
        raise SurfaceIdError(
            f"{row.id!r} says language {lang!r} and the row says {row.lang.value!r}; a row "
            "that disagrees with its own id cannot be attributed to either"
        )
    return NameSurface(
        indicator_id=indicator_id,
        detail_id=detail_id,
        kind=surface_kind,
        lang=row.lang,
        text=row.text,
    )
