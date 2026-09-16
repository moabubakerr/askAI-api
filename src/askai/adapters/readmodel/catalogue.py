"""The read model, read as the three things the answer path asks a catalogue for.

Purity: IO.

Story 1.11 shipped ``SnapshotCatalogue`` as a pure in-memory ``CataloguePort`` and said
what would fill it: *"built from whatever the caller has -- the read model, in the story
that wires ingest to the answer path"*. This is that story, and this is that wiring.

Three implementations live here because they are three readings of the same five tables,
and splitting them across files would mean three connections' worth of ceremony for one
sqlite handle:

**The snapshot** (``read_model_snapshot``). Every published detail name and country name,
folded once by the engine's single ``normalise`` inside ``SnapshotCatalogue`` itself.
``declared_grain`` is **always ``None``**, and that is a statement about the export rather
than an omission: the published layer declares no default interval for a detail
anywhere -- ``P02`` has no such column -- and ``CatalogueDetail`` is explicit that the
field *"is never derived from the datapoints"*. Deriving it would be the newest row
deciding the grain, which is the single thing FR-5 exists to prevent. ``grains`` is
different and is derived: the grains a detail *publishes at* are read off the periods it
publishes, because that is what the words mean, and FR-6 needs them so that a grain the
reader named and the detail does not publish can be **stated** rather than swapped.

**The presentation** (``ReadModelPresentation``). The detail's published name, unit,
Format field and publishing source, in the requested language. Read after execution, so
nothing here is reachable while a spec is being bound.

**The source catalogue** (``ReadModelSources``). AD-7's closed-world check: a
``source_ref`` resolves only if the read model holds the exact row it names *and* that
row's detail is published by the source the reference claims. ``resolves`` is total by
contract, so a store that will not answer returns ``False`` rather than raising into
``assemble/``, which may not hold a broad handler.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from askai.compile.catalogue import CatalogueCountry, CatalogueDetail, SnapshotCatalogue, snapshot
from askai.domain.period import Grain, Period, PeriodFormatError
from askai.messages.lang import Lang
from askai.ports.presentation import PublishedDetail

__all__ = [
    "SOURCE_REF_SEGMENTS",
    "ReadModelPresentation",
    "ReadModelSources",
    "read_model_snapshot",
]

#: ``detail | period | country | source`` -- the four segments
#: :attr:`askai.assemble.provenance.Provenance.source_ref` joins, with the country
#: segment empty for a national row. Stated here because this is the module that takes
#: one apart, and a reference of any other shape resolves to nothing rather than being
#: parsed leniently.
SOURCE_REF_SEGMENTS = 4

_DETAIL_NAMES = """
SELECT detail_id, name_en, name_ar FROM detail ORDER BY detail_id
"""

_DETAIL_GRAINS = """
SELECT DISTINCT detail_id, period FROM datapoint ORDER BY detail_id
"""

_COUNTRY_NAMES = """
SELECT country_id, code, name_en, name_ar FROM ref_country ORDER BY country_id
"""

_PRESENTED_DETAIL = """
SELECT detail.detail_id,
       detail.name_en, detail.name_ar,
       unit.name_en, unit.name_ar,
       detail.value_format,
       detail.data_source_id
  FROM detail
  LEFT JOIN ref_lookup AS unit ON unit.lookup_id = detail.unit_id
 WHERE detail.detail_id = ?
"""

_COUNTRY = "SELECT name_en, name_ar FROM ref_country WHERE country_id = ?"

_ROW_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM datapoint
      JOIN detail ON detail.detail_id = datapoint.detail_id
     WHERE datapoint.detail_id = ? AND datapoint.period = ?
       AND datapoint.country_id IS ? AND detail.data_source_id = ?
)
"""


def read_model_snapshot(connection: sqlite3.Connection) -> SnapshotCatalogue:
    """Every published name the binder may resolve, as one immutable snapshot.

    Built whole rather than queried per question. Binding happens before any data access
    (AD-1), so the alternative -- a catalogue that runs a ``SELECT`` per candidate span --
    would put the read model inside ``compile/`` by the back door, and would make the same
    question bind differently depending on what a concurrent refresh had committed.
    """
    grains = _grains_by_detail(connection)
    details = [
        CatalogueDetail(
            detail_id=str(detail_id),
            names=_names(name_en, name_ar),
            # The published layer declares no default interval anywhere; see the module
            # docstring. `None` says exactly that, and the binder falls through to the
            # ungrained latest rather than to a grain the data was asked to choose.
            declared_grain=None,
            grains=frozenset(grains.get(str(detail_id), ())),
        )
        for detail_id, name_en, name_ar in connection.execute(_DETAIL_NAMES)
    ]
    countries = [
        # Published names only -- deliberately **not** the ISO code. A two-letter code
        # folds to a two-letter word, and `is`, `in`, `at`, `no`, `so` and `me` are all
        # country codes in this reference: admitting them would bind a country scope off
        # the grammar of the question, and "what is inflation now" would silently become
        # a question about Iceland.
        CatalogueCountry(country_id=str(country_id), names=_names(name_en, name_ar))
        for country_id, _code, name_en, name_ar in connection.execute(_COUNTRY_NAMES)
    ]
    return snapshot(details=details, countries=countries)


def _grains_by_detail(connection: sqlite3.Connection) -> dict[str, set[Grain]]:
    """The grains each detail publishes at, read off the periods it publishes.

    A period the engine cannot classify is skipped rather than raised on: the ingest and
    the table's own CHECK both refuse one, so this can only be reached by a file written
    by something else -- and a catalogue that refused to load would take the whole answer
    path down for one bad row, where a missing grain only costs FR-6 its statement.
    """
    found: dict[str, set[Grain]] = defaultdict(set)
    for detail_id, period in connection.execute(_DETAIL_GRAINS):
        try:
            grain = Period(str(period)).grain
        except PeriodFormatError:
            continue
        found[str(detail_id)].add(grain)
    return found


def _names(*published: object) -> tuple[str, ...]:
    """The published spellings of one thing, blanks dropped and duplicates collapsed.

    Order is preserved so the same read model builds the same snapshot on every run
    (AD-17); ``SnapshotCatalogue`` folds each one through the engine's single
    ``normalise``, so nothing here compares or cases text.
    """
    names: list[str] = []
    for value in published:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in names:
            names.append(text)
    return tuple(names)


def _in(lang: Lang, english: object, arabic: object) -> str:
    """The published spelling in *lang*, falling back to the other only when blank.

    The fallback is not a translation: it is the published layer having left one half
    empty, and showing the half that exists beats showing nothing where a unit belongs.
    """
    match lang:
        case Lang.EN:
            first, second = english, arabic
        case Lang.AR:
            first, second = arabic, english
    return str(first or "").strip() or str(second or "").strip()


@dataclass(frozen=True, slots=True)
class ReadModelPresentation:
    """``PresentationPort`` over the read model. Reads only; writes nothing, ever."""

    connection: sqlite3.Connection

    def detail(self, detail_id: str, lang: Lang) -> PublishedDetail | None:
        found = self.connection.execute(_PRESENTED_DETAIL, (detail_id,)).fetchone()
        if found is None:
            return None
        found_id, name_en, name_ar, unit_en, unit_ar, value_format, source_id = found
        return PublishedDetail(
            detail_id=str(found_id),
            name=_in(lang, name_en, name_ar),
            unit=_in(lang, unit_en, unit_ar),
            # Carried as published, empty string included: the empty Format field is what
            # `R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT`'s fallback clause exists for.
            value_format=str(value_format or ""),
            source_id=str(source_id),
        )

    def country(self, country_id: str, lang: Lang) -> str | None:
        found = self.connection.execute(_COUNTRY, (country_id,)).fetchone()
        if found is None:
            return None
        return _in(lang, found[0], found[1])


@dataclass(frozen=True, slots=True)
class ReadModelSources:
    """``SourceCatalogue`` over the read model -- AD-7's closed world, asked of sqlite.

    The check is the whole reference and not a prefix of it. A reference naming a row
    that exists under a different publishing source does **not** resolve: an element
    carrying a source the row does not have is precisely the unsourced content AD-7
    rejects, and it would be the most plausible-looking kind.
    """

    connection: sqlite3.Connection

    def resolves(self, source_ref: str) -> bool:
        parts = source_ref.split("|")
        if len(parts) != SOURCE_REF_SEGMENTS:
            return False
        detail_id, period, country, source_id = parts
        if not detail_id or not period or not source_id:
            return False
        try:
            found = self.connection.execute(
                _ROW_EXISTS, (detail_id, period, country or None, source_id)
            ).fetchone()
        except sqlite3.Error:
            # Total by contract (``SourceCatalogue.resolves``): ``assemble/`` may not
            # hold a handler, so a store that will not answer must arrive as "this does
            # not resolve" and be refused with a typed degradation like any other.
            return False
        return bool(found is not None and found[0])
