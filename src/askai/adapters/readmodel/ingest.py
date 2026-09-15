"""Materialise the published layer into the read model. The only writer of its tables.

Purity: IO.

Story 1.8. The published ``P*`` layer is copied into the local read model -- 189
indicators, 289 details, 8,127 datapoints and the reference tables -- and the base
``Item_*`` layer is not copied at all. It has no table here: it is reachable only
through :mod:`askai.adapters.readmodel.unpublished`, behind a port that exposes names
and existence, so an unapproved value has no row to be joined to.

Four properties are load-bearing, and each is structural rather than careful:

**The key is (detail, period, country), and the grain is not in it.** The period string
carries the grain, so it is read off the period where one is needed and never stored
beside it. Measured on this export: 8,127 rows, 8,127 distinct keys, no collision.

**The blank country is the national marker and is never filled in.** The CMS states the
national scope as an explicit value which publication converts to empty; 5,263 of 8,127
published rows carry it. Backfilling those with the home country's name would merge the
national series into the benchmark set -- and would also find nothing, because the data
names that country in none of its rows. So a blank country becomes ``NULL`` and nothing
here constructs a country name at all.

**Confidential indicators do not arrive.** They are refused twice: filtered here, and
unrepresentable in the table, because the read model's ``CHECK`` rejects the row. FR-50
is about counts, lists and group totals as much as about values, and a row that is not
in the table cannot be counted by anything.

**CMS state does not arrive either.** ``PublishingStatusName`` is ``Amended`` on 100% of
published indicators, so it distinguishes nothing; it has no column and is not stored.

Published prose is decoded and rendered to text here, once, by :mod:`content` -- no
reader-facing path strips markup (FR-64).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.countries import country_aliases_from
from askai.adapters.readmodel.export import CmsExport, Row
from askai.domain.period import Grain, Period, PeriodFormatError
from askai.rules.countries import CountryAliasError, CountryAliases

__all__ = ["IngestError", "IngestReport", "ingest_published_layer"]

#: The priority type an indicator may not be answerable at. Spelled as the published
#: vocabulary spells it, and mirrored by the read model's own ``CHECK`` -- the filter is
#: the polite refusal, the constraint is the one that cannot be forgotten.
CONFIDENTIAL: Final = "Confidential"

#: ``P13``'s three priority types are a reference vocabulary like any other, but the
#: file does not carry a lookup-type column of its own. This is the name they are filed
#: under in ``ref_lookup``, so a lookup id is unambiguous across all eleven vocabularies.
PRIORITY_LOOKUP_TYPE: Final = "IndicatorPriorityTypes"

# The published change columns, by the grain the row is at. Change is published, not
# computed (DATA-CONTRACT FACT 2), and `Percent` and `pp` are different quantities on an
# indicator already measured in per cent -- so they are carried across as two columns,
# never reconciled into one. Measured: no row carries a change column belonging to a
# grain other than its own, so selecting by grain loses nothing.
#
# A tuple rather than a dict: module-level mutable state is what AD-15 forbids, and this
# is a fixed table of three rows, not a collector.
_YOY_COLUMNS: Final = (
    (Grain.MONTHLY, "MonthlyYoYPercent", "MonthlyYoYpp"),
    (Grain.QUARTERLY, "QuarterlyYoYPercent", "QuarterlyYoYpp"),
    (Grain.YEARLY, "YearlyYoYPercent", "YearlyYoYpp"),
)

_COUNTRY_SQL: Final = """
    INSERT INTO ref_country (country_id, code, name_en, name_ar) VALUES (?, ?, ?, ?)
"""
_LOOKUP_SQL: Final = """
    INSERT INTO ref_lookup (lookup_id, lookup_type, name_en, name_ar) VALUES (?, ?, ?, ?)
"""
_CATALOGUE_SQL: Final = """
    INSERT INTO catalogue (
        indicator_id, name_en, name_ar, classification,
        entity_id, entity_name_en, entity_name_ar, priority_type
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
_DETAIL_SQL: Final = """
    INSERT INTO detail (
        detail_id, indicator_id, name_en, name_ar, definition_en, definition_ar,
        unit_id, value_format, data_source_id, polarity_id, value_type_id,
        aggregation_type_id, is_main
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_DATAPOINT_SQL: Final = """
    INSERT INTO datapoint (
        detail_id, period, country_id, source_datapoint_id,
        actual, target, baseline,
        change_mom_percent, change_mom_pp, change_qoq_percent, change_qoq_pp,
        change_yoy_percent, change_yoy_pp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

#: Emptied in this order -- children first -- so the foreign keys hold at every point of
#: the refresh rather than only at its end.
_CLEAR_SQL: Final = (
    "DELETE FROM datapoint",
    "DELETE FROM detail",
    "DELETE FROM catalogue",
    "DELETE FROM ref_lookup",
    "DELETE FROM ref_country",
)


class IngestError(RuntimeError):
    """The export cannot be materialised as it stands, and nothing was written."""


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What the ingest put in the read model, counted from the tables afterwards.

    Counted by reading the database back rather than by tallying what the loop intended
    to do: a count that comes from the writer agrees with the writer even when the
    writer is wrong.
    """

    countries: int
    lookups: int
    indicators: int
    details: int
    datapoints: int
    national_rows: int
    country_rows: int
    #: Read from the export and deliberately **not** stored. Analyst prose is retrieved
    #: with a mandatory metadata filter from the semantic index, which is a different
    #: file with a different owner and arrives in Epic 2; the read model declares no
    #: table for it. Counted here so a refresh still reports what the export held.
    analyses_available: int
    #: Refused by FR-50, before the read model's own ``CHECK`` would have refused them.
    confidential_indicators_excluded: int
    #: The reviewed alias table, widened by the names this export publishes. Carried on
    #: the report because it is built from the same export in the same pass: a map built
    #: from one export while the rows came from another would resolve names the data
    #: does not carry. The home country resolves through it to ``HomeCountry``, which
    #: has no code, so it still cannot become a filter value.
    country_aliases: CountryAliases

    @property
    def rows_written(self) -> int:
        """Every row in the read model after the ingest."""
        return self.countries + self.lookups + self.indicators + self.details + self.datapoints


def _text(row: Row, column: str) -> str:
    return row.get(column, "").strip()


def _optional(row: Row, column: str) -> str | None:
    """A published cell, or ``None`` when it is blank.

    The empty string and ``NULL`` are the same fact here -- "this row publishes no such
    figure" -- and keeping both would give every later ``IS NULL`` a second case to
    remember.
    """
    return _text(row, column) or None


def _flag(row: Row, column: str) -> int:
    return 1 if _text(row, column).casefold() == "true" else 0


def _entity_names(export: CmsExport) -> Mapping[str, tuple[str, str]]:
    """Group names by entity id, from the two files that hold them.

    The ids are GUIDs spelled in upper case in the loose files and lower case in the
    catalogue, so they are matched case-insensitively. All 189 resolve.
    """
    return {
        _text(row, "Id").casefold(): (_text(row, "NameEN"), _text(row, "NameAR"))
        for row in export.entity_names()
    }


def _priority_names(export: CmsExport) -> Mapping[str, str]:
    return {
        _text(row, "Id"): _text(row, "NameEN") for row in export.reference_priority_types()
    }


def _country_rows(export: CmsExport) -> list[tuple[str | None, ...]]:
    return [
        (
            _text(row, "Id"),
            _optional(row, "Code"),
            _text(row, "NameEN"),
            _text(row, "NameAR"),
        )
        for row in export.reference_countries()
    ]


def _lookup_rows(export: CmsExport) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = [
        (_text(row, "Id"), _text(row, "LookupType"), _text(row, "NameEN"), _text(row, "NameAR"))
        for row in export.reference_lookups()
    ]
    rows.extend(
        (_text(row, "Id"), PRIORITY_LOOKUP_TYPE, _text(row, "NameEN"), _text(row, "NameAR"))
        for row in export.reference_priority_types()
    )
    return rows


def _catalogue_rows(
    export: CmsExport, priorities: Mapping[str, str]
) -> tuple[list[tuple[str | None, ...]], int]:
    """The published catalogue, minus anything confidential. Returns the rows and the cut."""
    entities = _entity_names(export)
    rows: list[tuple[str | None, ...]] = []
    excluded = 0
    for indicator in export.published_indicators():
        # An indicator with no declared priority type is not thereby non-priority: the
        # export leaves the column blank on 84 of 189 and states nothing. Stored as the
        # empty string, which is "the catalogue declares none", not a rank.
        priority = priorities.get(_text(indicator, "IndicatorPriorityTypeId"), "")
        if priority == CONFIDENTIAL:
            excluded += 1
            continue
        entity_id = _text(indicator, "IndicatorEntityTypeId")
        names = entities.get(entity_id.casefold())
        rows.append(
            (
                _text(indicator, "PublishedIndicatorId"),
                _text(indicator, "NameEN"),
                _text(indicator, "NameAR"),
                _text(indicator, "EntityClassificationName"),
                entity_id or None,
                names[0] if names else None,
                names[1] if names else None,
                priority,
            )
        )
    return rows, excluded


def _detail_rows(export: CmsExport, indicators: frozenset[str]) -> list[tuple[object, ...]]:
    return [
        (
            _text(detail, "PublishedIndicatorDetailId"),
            _text(detail, "PublishedIndicatorId"),
            _text(detail, "NameEN"),
            _text(detail, "NameAR"),
            # "Defination" is the export's spelling of the column, not a typo here.
            published_text(_text(detail, "DefinationEN")),
            published_text(_text(detail, "DefinationAR")),
            _text(detail, "UnitId"),
            _optional(detail, "Format"),
            _text(detail, "DataSourceId"),
            _text(detail, "PolarityId"),
            _text(detail, "ValueTypeId"),
            _text(detail, "AggregationTypeId"),
            _flag(detail, "IsMain"),
        )
        for detail in export.published_details()
        if _text(detail, "PublishedIndicatorId") in indicators
    ]


def _datapoint_row(datapoint: Row) -> tuple[object, ...]:
    period = _text(datapoint, "Period")
    try:
        grain = Period(period).grain
    except PeriodFormatError as error:
        raise IngestError(
            f"datapoint {_text(datapoint, 'PublishedDataPointId')} publishes period "
            f"{period!r}, whose grain cannot be read; nothing was ingested"
        ) from error
    yoy_percent, yoy_pp = next(
        (percent, pp) for at, percent, pp in _YOY_COLUMNS if at is grain
    )
    return (
        _text(datapoint, "PublishedIndicatorDetailId"),
        period,
        # The one place FR-10 is decided. Blank stays blank: it is the national marker,
        # and the country *name* column beside it is never read at all.
        _optional(datapoint, "CountryId"),
        _text(datapoint, "PublishedDataPointId"),
        _optional(datapoint, "Actual"),
        _optional(datapoint, "Target"),
        # The export publishes a baseline per detail, not per datapoint, so there is no
        # cell to carry across. Left NULL rather than filled from the detail, which
        # would make one declared baseline look like 8,127 measured ones.
        None,
        _optional(datapoint, "MonthlyMoMPercent"),
        _optional(datapoint, "MonthlyMoMpp"),
        _optional(datapoint, "QuarterlyQoQPercent"),
        _optional(datapoint, "QuarterlyQoQpp"),
        _optional(datapoint, yoy_percent),
        _optional(datapoint, yoy_pp),
    )


def _datapoint_rows(export: CmsExport, details: frozenset[str]) -> list[tuple[object, ...]]:
    return [
        _datapoint_row(datapoint)
        for datapoint in export.published_datapoints()
        if _text(datapoint, "PublishedIndicatorDetailId") in details
    ]


def _count(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    if row is None:
        raise IngestError(f"{sql!r} returned no row")
    count: object = row[0]
    if not isinstance(count, int):
        raise IngestError(f"{sql!r} returned {count!r}, expected a count")
    return count


def _keys(rows: Sequence[tuple[object, ...]]) -> set[tuple[object, object, object]]:
    return {(row[0], row[1], row[2]) for row in rows}


def ingest_published_layer(connection: sqlite3.Connection, export: CmsExport) -> IngestReport:
    """Replace the read model's contents with *export*'s published layer.

    One transaction: a reader on another connection sees the previous contents until it
    commits, and sees the new ones afterwards, never a mixture. A failure anywhere --
    an unreadable period, a reference that does not resolve, a duplicate key -- leaves
    the previous contents in place, because a half-ingested read model answers
    confidently and wrongly.
    """
    # Built before anything is written, so a reference table that contradicts the
    # reviewed alias groups stops the refresh rather than half-completing it.
    try:
        aliases = country_aliases_from(export)
    except CountryAliasError as error:
        raise IngestError(
            f"the export's country reference cannot extend the reviewed alias table: "
            f"{error}"
        ) from error

    priorities = _priority_names(export)
    catalogue, excluded = _catalogue_rows(export, priorities)
    indicators = frozenset(str(row[0]) for row in catalogue)
    details = _detail_rows(export, indicators)
    detail_ids = frozenset(str(row[0]) for row in details)
    datapoints = _datapoint_rows(export, detail_ids)

    # Checked before the write, so the collision is reported as itself rather than as
    # whichever of the two unique constraints sqlite happens to reach first.
    if len(_keys(datapoints)) != len(datapoints):
        raise IngestError(
            f"{len(datapoints) - len(_keys(datapoints))} datapoints share a "
            "(detail, period, country) key; the identity fact does not hold for this "
            "export and nothing was ingested"
        )

    try:
        with connection:
            for statement in _CLEAR_SQL:
                connection.execute(statement)
            connection.executemany(_COUNTRY_SQL, _country_rows(export))
            connection.executemany(_LOOKUP_SQL, _lookup_rows(export))
            connection.executemany(_CATALOGUE_SQL, catalogue)
            connection.executemany(_DETAIL_SQL, details)
            connection.executemany(_DATAPOINT_SQL, datapoints)
    except sqlite3.DatabaseError as error:
        raise IngestError(f"the export was refused by the read model: {error}") from error

    return IngestReport(
        countries=_count(connection, "SELECT COUNT(*) FROM ref_country"),
        lookups=_count(connection, "SELECT COUNT(*) FROM ref_lookup"),
        indicators=_count(connection, "SELECT COUNT(*) FROM catalogue"),
        details=_count(connection, "SELECT COUNT(*) FROM detail"),
        datapoints=_count(connection, "SELECT COUNT(*) FROM datapoint"),
        national_rows=_count(
            connection, "SELECT COUNT(*) FROM datapoint WHERE country_id IS NULL"
        ),
        country_rows=_count(
            connection, "SELECT COUNT(*) FROM datapoint WHERE country_id IS NOT NULL"
        ),
        analyses_available=len(export.published_analyses()),
        confidential_indicators_excluded=excluded,
        country_aliases=aliases,
    )
