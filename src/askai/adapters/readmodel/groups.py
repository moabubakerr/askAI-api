"""The group layer, the published definitions, and the coverage counts -- read, not written.

Purity: IO.

Story 1.8 materialised the group layer into ``catalogue`` -- ``classification``,
``entity_id`` and the two entity names -- and nothing ever read it back. That is the
whole of Epic 5's opening complaint: *"a complete layer of the published catalogue stops
being invisible"*. This module is the reading.

It adds **no table and no column**. Every statement here is a ``SELECT`` over the five
tables ``adapters/readmodel/schema.py`` already declares, so the ingest remains the one
writer of all of them (AD-20) and ``SCHEMA_VERSION`` does not move. ``tests/`` asserts
the no-write half by scanning this package for a DML statement.

Two implementations live here because they are two readings of the same table:

**The group layer and metadata** (``ReadModelGroups``), answering ``GroupsPort``.

**The catalogue's half of the closed world** (``ReadModelCatalogueSources``). AD-7 makes
``assemble/`` refuse any element whose ``source_ref`` does not resolve, and a count of a
group is an element like any other -- Story 5.3 is explicit that *"a count is a figure and
obeys the same rules"*. But a count has no period and no country, so it cannot carry a
datapoint reference, and ``ReadModelSources`` in ``catalogue.py`` resolves only those.

The two reference shapes are therefore **distinguishable by construction rather than by
convention**: a datapoint reference is four ``|``-separated segments, a catalogue
reference is ``catalogue:<kind>:<key>``. Neither parses as the other -- a catalogue
reference splits on ``|`` into one part, which ``ReadModelSources`` already rejects -- so
``EitherSource`` can ask both without either one guessing. A shared separator would have
made *"the detail whose id happens to contain a pipe"* the failure mode, and it would have
been found by a reader rather than by a test.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from askai.domain.normalise import normalise
from askai.ports.groups import (
    Coverage,
    Group,
    GroupedIndicator,
    GroupLevel,
    PublishedDefinition,
)
from askai.ports.provenance_source import SourceCatalogue

__all__ = [
    "CATALOGUE_REF_PREFIX",
    "CATALOGUE_REF_SEGMENTS",
    "CATALOGUE_REF_SEPARATOR",
    "EitherSource",
    "ReadModelCatalogueSources",
    "ReadModelGroups",
]

#: ``catalogue:<kind>:<key>`` -- what a catalogue-fact element carries instead of a
#: datapoint reference. Spelled here, in the module that takes one apart, and built in
#: ``assemble/meta/reference.py``, which is the module that makes one.
CATALOGUE_REF_PREFIX: Final = "catalogue"
CATALOGUE_REF_SEPARATOR: Final = ":"
CATALOGUE_REF_SEGMENTS: Final = 3

_CLASSIFICATIONS = """
SELECT classification, classification, classification, COUNT(*)
  FROM catalogue
 GROUP BY classification
 ORDER BY classification
"""

# The entity names are stored on every row of the catalogue rather than in a table of
# their own, so `MIN` picks one deterministically; every row of a group carries the same
# pair, and `MIN` is how that is said in SQL without a subquery that implies otherwise.
_ENTITIES_IN = """
SELECT entity_id, MIN(entity_name_en), MIN(entity_name_ar), COUNT(*), MIN(classification)
  FROM catalogue
 WHERE classification = ? AND entity_id IS NOT NULL
 GROUP BY entity_id
 ORDER BY COUNT(*) DESC, MIN(entity_name_en)
"""

_ALL_ENTITIES = """
SELECT entity_id, MIN(entity_name_en), MIN(entity_name_ar), COUNT(*), MIN(classification)
  FROM catalogue
 WHERE entity_id IS NOT NULL
 GROUP BY entity_id
 ORDER BY MIN(classification), MIN(entity_name_en)
"""

_INDICATORS_BY_CLASSIFICATION = """
SELECT indicator_id, name_en, name_ar
  FROM catalogue
 WHERE classification = ?
 ORDER BY name_en, indicator_id
"""

_INDICATORS_BY_ENTITY = """
SELECT indicator_id, name_en, name_ar
  FROM catalogue
 WHERE entity_id = ?
 ORDER BY name_en, indicator_id
"""

# `is_main DESC` first: the overview wants one figure per indicator, and the main detail
# is the one the catalogue publishes as the indicator's own.
_DETAILS_OF = """
SELECT detail_id FROM detail
 WHERE indicator_id = ?
 ORDER BY is_main DESC, name_en, detail_id
"""

_DEFINITION = """
SELECT detail_id, definition_en, definition_ar, data_source_id
  FROM detail WHERE detail_id = ?
"""

_COVERAGE = """
SELECT (SELECT COUNT(*) FROM catalogue),
       (SELECT COUNT(DISTINCT detail.indicator_id) FROM detail
          JOIN datapoint ON datapoint.detail_id = detail.detail_id),
       (SELECT COUNT(*) FROM detail),
       (SELECT COUNT(DISTINCT detail_id) FROM datapoint),
       (SELECT COUNT(*) FROM datapoint),
       (SELECT COUNT(*) FROM ref_country),
       (SELECT COUNT(DISTINCT detail_id) FROM datapoint WHERE country_id IS NOT NULL),
       (SELECT COUNT(DISTINCT classification) FROM catalogue),
       (SELECT COUNT(DISTINCT entity_id) FROM catalogue WHERE entity_id IS NOT NULL)
"""

_CLASSIFICATION_EXISTS = "SELECT EXISTS (SELECT 1 FROM catalogue WHERE classification = ?)"
_ENTITY_EXISTS = "SELECT EXISTS (SELECT 1 FROM catalogue WHERE entity_id = ?)"
_INDICATOR_EXISTS = "SELECT EXISTS (SELECT 1 FROM catalogue WHERE indicator_id = ?)"
_DETAIL_EXISTS = "SELECT EXISTS (SELECT 1 FROM detail WHERE detail_id = ?)"
_ANY_CATALOGUE = "SELECT EXISTS (SELECT 1 FROM catalogue)"


@dataclass(frozen=True, slots=True)
class ReadModelGroups:
    """``GroupsPort`` over the read model. Reads only; writes nothing, ever."""

    connection: sqlite3.Connection

    # ------------------------------------------------------------------ the group layer

    def classifications(self) -> tuple[Group, ...]:
        return tuple(
            Group(
                level=GroupLevel.CLASSIFICATION,
                key=str(key),
                # A classification is published as one name and no translation: the
                # export carries `EntityClassificationName` and nothing beside it. Both
                # language fields therefore hold the same string, which is the honest
                # shape -- a blank Arabic name would be read as "not published in Arabic"
                # by every caller that checks, and this is not that.
                name_en=str(name_en),
                name_ar=str(name_ar),
                indicator_count=_count(count),
                classification=str(key),
            )
            for key, name_en, name_ar, count in self._all(_CLASSIFICATIONS, ())
        )

    def entities_in(self, classification: str) -> tuple[Group, ...]:
        return tuple(self._entities(_ENTITIES_IN, (classification,)))

    def groups_named(self, normalised_name: str) -> tuple[Group, ...]:
        """Every group whose published name folds to *normalised_name*, at either level.

        The catalogue side is folded here with the engine's single ``normalise``, and the
        caller's side was folded with the same function before it arrived -- the contract
        ``CataloguePort`` states and the reason there is exactly one such function in the
        tree. Nothing here scores, ranks or approximates: a name that is not a published
        name returns nothing rather than the nearest thing to it.

        Classifications are searched before entities so that a name matching both states
        the wider reading first, which is the reading a reader is more likely to have
        meant and the one they are least likely to expect. Neither is chosen; both are
        returned, and ``assemble/meta/`` turns two into a clarification (FR-2).
        """
        wanted = normalise(normalised_name)
        if not wanted:
            return ()
        found = [
            group
            for group in self.classifications()
            if wanted in {normalise(group.name_en), normalise(group.name_ar)}
        ]
        found += [
            group
            for group in self._entities(_ALL_ENTITIES, ())
            if wanted in {normalise(group.name_en), normalise(group.name_ar)}
        ]
        return tuple(found)

    def indicators_in(self, level: GroupLevel, key: str) -> tuple[GroupedIndicator, ...]:
        match level:
            case GroupLevel.CLASSIFICATION:
                sql = _INDICATORS_BY_CLASSIFICATION
            case GroupLevel.ENTITY:
                sql = _INDICATORS_BY_ENTITY
            case _:
                raise ValueError(
                    f"{level!r} is not a level of the group layer; a level the port "
                    "offers is a level this query has to be written for"
                )
        return tuple(
            GroupedIndicator(
                indicator_id=str(indicator_id), name_en=str(name_en), name_ar=str(name_ar)
            )
            for indicator_id, name_en, name_ar in self._all(sql, (key,))
        )

    # ---------------------------------------------------------------------- metadata

    def details_of(self, indicator_id: str) -> tuple[str, ...]:
        return tuple(str(detail_id) for (detail_id,) in self._all(_DETAILS_OF, (indicator_id,)))

    def definition(self, detail_id: str) -> PublishedDefinition | None:
        found = self._all(_DEFINITION, (detail_id,))
        if not found:
            return None
        found_id, definition_en, definition_ar, source_id = found[0]
        return PublishedDefinition(
            detail_id=str(found_id),
            # Carried exactly as published, `-` included. The decision about a
            # placeholder belongs to `assemble/meta/`, which fires a named rule making
            # it; cleaning here would hide the decision in an adapter.
            definition_en=str(definition_en or ""),
            definition_ar=str(definition_ar or ""),
            source_id=str(source_id),
        )

    def coverage(self) -> Coverage:
        found = self._all(_COVERAGE, ())
        if not found:  # pragma: no cover -- a scalar subquery row always comes back
            raise sqlite3.DataError("the read model answered no row to the coverage counts")
        (
            indicators,
            indicators_with_data,
            details,
            details_with_data,
            datapoints,
            countries,
            details_with_country_data,
            classifications,
            entities,
        ) = found[0]
        return Coverage(
            indicators=_count(indicators),
            indicators_with_data=_count(indicators_with_data),
            details=_count(details),
            details_with_data=_count(details_with_data),
            datapoints=_count(datapoints),
            countries=_count(countries),
            details_with_country_data=_count(details_with_country_data),
            classifications=_count(classifications),
            entities=_count(entities),
        )

    # ----------------------------------------------------------------------- plumbing

    def _entities(self, sql: str, parameters: tuple[object, ...]) -> list[Group]:
        return [
            Group(
                level=GroupLevel.ENTITY,
                key=str(entity_id),
                name_en=str(name_en or ""),
                name_ar=str(name_ar or ""),
                indicator_count=_count(count),
                classification=str(classification),
            )
            for entity_id, name_en, name_ar, count, classification in self._all(sql, parameters)
        ]

    def _all(self, sql: str, parameters: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
        return tuple(tuple(row) for row in self.connection.execute(sql, parameters))


@dataclass(frozen=True, slots=True)
class ReadModelCatalogueSources:
    """``SourceCatalogue`` for the catalogue-shaped references Epic 5 elements carry.

    The same closed world as ``ReadModelSources``, asked about a different kind of row:
    a count of a group resolves only if the group exists in the loaded catalogue, and a
    quoted definition only if the detail does. An element whose group was removed by the
    last refresh is refused with a typed degradation exactly as a stale datapoint
    reference is -- which is what keeps *"a count is a figure and obeys the same rules"*
    from being a remark in a story.
    """

    connection: sqlite3.Connection

    def resolves(self, source_ref: str) -> bool:
        parts = source_ref.split(CATALOGUE_REF_SEPARATOR, CATALOGUE_REF_SEGMENTS - 1)
        if len(parts) != CATALOGUE_REF_SEGMENTS:
            return False
        prefix, kind, key = parts
        if prefix != CATALOGUE_REF_PREFIX or not key.strip():
            return False
        query = _EXISTS_BY_KIND.get(kind)
        if query is None:
            return False
        sql, keyed = query
        try:
            found = self.connection.execute(sql, (key,) if keyed else ()).fetchone()
        except sqlite3.Error:
            # Total by contract, like every `SourceCatalogue`: a store that will not
            # answer arrives as "this does not resolve" and is refused with a typed
            # degradation, never as an exception into a layer with no handler.
            return False
        return bool(found is not None and found[0])


#: Which query answers each catalogue reference kind, and whether it takes the key. A
#: mapping rather than a chain of ``if``s so that a kind ``assemble/meta/`` can build and
#: this cannot resolve is a missing key -- which returns ``False`` and refuses the
#: element -- rather than a fall-through that admits it.
#:
#: ``catalogue`` is the one unkeyed kind: it is the reference a statement about the whole
#: loaded corpus carries, and it resolves when the read model holds any published
#: indicator at all. A capability answer computed from an empty read model is thereby
#: refused rather than reported as a catalogue of nothing.
#: Read-only, because a module-level ``dict`` in this engine is the shape an ambient
#: collector takes and ``tests/test_domain_invariants.py`` refuses one.
_EXISTS_BY_KIND: Final[Mapping[str, tuple[str, bool]]] = MappingProxyType(
    {
        "classification": (_CLASSIFICATION_EXISTS, True),
        "entity": (_ENTITY_EXISTS, True),
        "indicator": (_INDICATOR_EXISTS, True),
        "detail": (_DETAIL_EXISTS, True),
        "catalogue": (_ANY_CATALOGUE, False),
    }
)


@dataclass(frozen=True, slots=True)
class EitherSource:
    """One ``SourceCatalogue`` over both reference shapes.

    An answer can carry a group's count and a figure from a datapoint in the same
    package -- the executive overview does exactly that -- so the admission step needs
    one port that resolves both. It asks each in turn and never parses: the two shapes
    are disjoint, so a reference that is not a datapoint reference is rejected by the
    first without being mistaken for something, and the second decides.
    """

    datapoints: SourceCatalogue
    catalogue: SourceCatalogue

    def resolves(self, source_ref: str) -> bool:
        return self.datapoints.resolves(source_ref) or self.catalogue.resolves(source_ref)


def _count(value: object) -> int:
    """A ``COUNT(*)`` cell as an ``int``.

    Via ``str`` because the driver types every cell as ``object`` under ``--strict`` and
    ``int(object)`` does not type-check. Deliberately not a ``cast``: a cell that is not a
    number raises here, in the adapter, rather than reaching a composer as a value that
    was only asserted to be a count.
    """
    return int(str(value))
