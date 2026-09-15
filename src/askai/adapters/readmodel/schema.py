"""The read model's tables -- catalogue, detail, datapoint, and the two reference tables.

Purity: IO.

The local copy of the *published* layer (AD-9a), and only that: the base CMS layer has
no grain, no Arabic analysis, no unit and no format, so it cannot answer anything
(DATA-CONTRACT §1.0) and has no table here. Confidential indicators are refused by a
CHECK rather than by an ingest filter, so an indicator the Council never approved is
unrepresentable in the file an answer is computed from, not merely unlikely.

Epic 1's tables and no others. The vector collections -- `names` in Epic 2, analyst and
article content in Epic 2 and Epic 6 -- are created by the story that fills them, in
the separate index file AD-20 keeps them in.

Every table here is owned by ``askai.adapters.readmodel``: the ingest of Story 1.8
writes them and nothing else does. The record store's tables are owned elsewhere and
live in a different file.
"""

from __future__ import annotations

from typing import Final

from askai.adapters.store.database import DatabaseSchema, Table

__all__ = ["CATALOGUE", "DATAPOINT", "DETAIL", "OWNER", "READ_MODEL", "REF_COUNTRY", "REF_LOOKUP"]

#: The one module AD-20 permits to write these tables.
OWNER: Final = "askai.adapters.readmodel"

# `STRICT` on every table it can carry: without it sqlite stores whatever it is given,
# so a value arriving as a float would be kept as one and the "published values are
# decimal, never float" rule would hold only as long as every caller remembered it.
# `datapoint` is the exception, and says why below.

CATALOGUE: Final = Table(
    name="catalogue",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS catalogue (
        indicator_id            TEXT    NOT NULL PRIMARY KEY,
        name_en                 TEXT    NOT NULL,
        name_ar                 TEXT    NOT NULL,
        classification          TEXT    NOT NULL,
        entity_id               TEXT,
        entity_name_en          TEXT,
        entity_name_ar          TEXT,
        priority_type           TEXT    NOT NULL,
        -- FR: confidential indicators may not appear in any answer, count, list or
        -- total. Enforced as a constraint on the store rather than as a step in the
        -- ingest, because a filter can be forgotten by the next writer and this cannot.
        CHECK (priority_type <> 'Confidential')
    ) STRICT
    """,
)

DETAIL: Final = Table(
    name="detail",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS detail (
        detail_id               TEXT    NOT NULL PRIMARY KEY,
        indicator_id            TEXT    NOT NULL REFERENCES catalogue(indicator_id),
        name_en                 TEXT    NOT NULL,
        name_ar                 TEXT    NOT NULL,
        definition_en           TEXT,
        definition_ar           TEXT,
        -- The formatter takes the detail's published unit and format and nothing else,
        -- so both are stored on the detail rather than derived at render time.
        unit_id                 TEXT    NOT NULL REFERENCES ref_lookup(lookup_id),
        value_format            TEXT,
        data_source_id          TEXT    NOT NULL REFERENCES ref_lookup(lookup_id),
        polarity_id             TEXT    NOT NULL REFERENCES ref_lookup(lookup_id),
        value_type_id           TEXT    NOT NULL REFERENCES ref_lookup(lookup_id),
        aggregation_type_id     TEXT    NOT NULL REFERENCES ref_lookup(lookup_id),
        is_main                 INTEGER NOT NULL CHECK (is_main IN (0, 1))
    ) STRICT
    """,
    indexes=("CREATE INDEX IF NOT EXISTS detail_by_indicator ON detail(indicator_id)",),
)

DATAPOINT: Final = Table(
    name="datapoint",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS datapoint (
        detail_id               TEXT    NOT NULL REFERENCES detail(detail_id),
        -- The period carries the grain, so there is no grain column and no grain in
        -- the key. The CHECK is the published spelling of a period, and it is here
        -- because a period the engine cannot classify is a row whose grain is
        -- unknowable -- 2025 yearly, 2025-Q1 quarterly, 2025-01 monthly.
        period                  TEXT    NOT NULL CHECK (
            period GLOB '[0-9][0-9][0-9][0-9]'
            OR period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]'
            OR period GLOB '[0-9][0-9][0-9][0-9]-0[1-9]'
            OR period GLOB '[0-9][0-9][0-9][0-9]-1[0-2]'
        ),
        -- NULL is the national marker. National scope is a query shape, not a country
        -- value: the home country appears in 0 of the 8,127 published datapoints, so a
        -- filter naming it would match nothing while looking entirely correct.
        country_id              TEXT             REFERENCES ref_country(country_id),
        source_datapoint_id     TEXT    NOT NULL UNIQUE,
        -- Values are TEXT, not REAL. A published decimal read back as a float is the
        -- rounding defect arriving through the storage layer; the formatter parses
        -- the exact published digits.
        actual                  TEXT,
        target                  TEXT,
        baseline                TEXT,
        -- Change is published, not computed (DATA-CONTRACT FACT 2). The basis is not a
        -- grain: one quarterly row can publish both QoQ and YoY, which is exactly why
        -- these are columns on the row rather than a grain the row claims to be at.
        change_mom_percent      TEXT,
        change_mom_pp           TEXT,
        change_qoq_percent      TEXT,
        change_qoq_pp           TEXT,
        change_yoy_percent      TEXT,
        change_yoy_pp           TEXT,
        PRIMARY KEY (detail_id, period, country_id)
    )
    """,
    # Not STRICT, and the reason is structural rather than a preference: sqlite makes
    # every PRIMARY KEY column of a STRICT table implicitly NOT NULL, which would
    # forbid the national marker above. The cost is paid back by the CHECKs.
    indexes=(
        # The primary key does not constrain the national rows at all: sqlite lets a
        # rowid table's PRIMARY KEY hold NULL, and two NULLs compare distinct, so
        # (detail, period, NULL) can be inserted twice. This partial index is what
        # actually makes one national figure per detail and period unrepresentable.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS datapoint_one_national_row
            ON datapoint(detail_id, period) WHERE country_id IS NULL
        """,
        "CREATE INDEX IF NOT EXISTS datapoint_by_period ON datapoint(period)",
    ),
)

REF_COUNTRY: Final = Table(
    name="ref_country",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS ref_country (
        country_id              TEXT    NOT NULL PRIMARY KEY,
        code                    TEXT,
        name_en                 TEXT    NOT NULL,
        name_ar                 TEXT    NOT NULL
    ) STRICT
    """,
)

REF_LOOKUP: Final = Table(
    name="ref_lookup",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS ref_lookup (
        lookup_id               TEXT    NOT NULL PRIMARY KEY,
        -- One table for all ten published lookup types (units, polarities, value
        -- types, data sources, aggregation and input methods, ...) because their ids
        -- are globally unique GUIDs and ten near-identical two-column tables would be
        -- ten places to forget one.
        lookup_type             TEXT    NOT NULL,
        name_en                 TEXT    NOT NULL,
        name_ar                 TEXT    NOT NULL
    ) STRICT
    """,
    indexes=("CREATE INDEX IF NOT EXISTS ref_lookup_by_type ON ref_lookup(lookup_type)",),
)

READ_MODEL: Final = DatabaseSchema(
    name="read model",
    # Reference tables first: the order is the creation order, and a table is easier to
    # read when the things it points at already exist above it.
    tables=(REF_COUNTRY, REF_LOOKUP, CATALOGUE, DETAIL, DATAPOINT),
)
