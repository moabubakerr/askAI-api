"""The persisted shape of one index generation: a collection table, and what built it.

Purity: IO.

AD-20 puts the index in **its own database file**, never written in place alongside live
records or conversation state, and this module is that file's schema. It is deliberately
not part of ``store/provision.py``'s estate, and the reason is the difference between
the two kinds of file:

* the read model and the record store are *provisioned once and written in place*, so
  their tables are declared where the estate is declared and their versions move
  together;
* an index generation is *built whole and never written again*. It is created by
  :mod:`askai.adapters.index.build` into a file of its own, loaded into memory, and
  superseded by a later generation rather than updated. Nothing ever opens it to write.

Because of that, every table here is owned by ``askai.adapters.index`` and by nothing
else -- AD-20's rule holds, with this module as the single declaration point and
``tests/test_index.py`` scanning the tree to prove no other module writes a ``vec_``
table. The estate's ``TABLE_OWNERS`` map covers the three provisioned files and, in
Epic 1's shape, pins its own set; wiring a built generation onto the provisioned index
path is the refresh story's job and carries that declaration with it.

The row shape is Story 2.1's, exactly: ``id``, ``lang``, ``text`` -- the exact text
embedded, for audit -- ``embedding``, and the four scope columns AD-14 pre-filters on,
with an index over ``(detail_id, period, country_id, lang)``.
"""

from __future__ import annotations

import sqlite3
from typing import Final

from askai.adapters.index.lexical import create_names_lexical_table
from askai.ports.index import Collection

__all__ = [
    "FACTS_TABLE",
    "FACT_PERIODS_TABLE",
    "INDEX_SCHEMA_VERSION",
    "META_TABLE",
    "collection_table",
    "create_index_schema",
]

#: The shape version of an index file. Its own number, not the estate's: a generation is
#: built by this module and read by this module, and a change to the collection shape
#: invalidates every generation ever built without touching the read model or the record
#: store. A file at another version is refused at load rather than read as this one.
#:
#: Version 2 adds the ``names`` collection's full-text table (Story 2.2). It is a shape
#: change and therefore a version change: a generation built before it exists has no
#: lexical half, and half a hybrid search returning fewer candidates is precisely the
#: kind of degradation that looks healthy. Older generations are refused at load and
#: rebuilt, which is what this number is for.
#:
#: Version 3 adds ``detail_facts`` (Story 2.4). Same argument, more sharply: a generation
#: without it produces candidates whose structural facts are all empty, which does not
#: fail -- every signal simply goes silent and every question disambiguates. A silent
#: discriminator is the failure mode hardest to notice from the outside, so the file that
#: lacks the table is refused at load rather than searched.
INDEX_SCHEMA_VERSION: Final = 3

#: One row, recording what built the file. Read before anything else at load, because a
#: cosine between two vector spaces is a number with no meaning and this is what makes
#: it refusable.
META_TABLE: Final = "index_meta"

#: One row per indicator detail, holding the structural facts AD-25's stage 2
#: discriminates on (Story 2.4). In the *index* file rather than the read model, and
#: owned by this package, for three reasons that all point the same way:
#:
#: * a candidate and the facts it is discriminated against then come out of the **same
#:   immutable generation** (AD-13, AD-20), so a candidate scored against one build and
#:   told apart by another is unrepresentable rather than unlikely;
#: * the facts are rebuilt by the same job that rebuilds the collection they describe, so
#:   the two cannot drift;
#: * ``compile/`` is forbidden to reach an adapter, so the facts have to arrive as values
#:   on the candidate anyway -- and assembling them at build time is what lets stage 2 be
#:   pure.
#:
#: Nothing here is a value. Every column is a statement about what the catalogue
#: *publishes* -- which periods exist, which unit, which entity -- and the periods live in
#: a separate table precisely so that no column here can ever become a figure.
FACTS_TABLE: Final = "detail_facts"

#: The periods each detail publishes a row for. Coverage, never content: a row here says
#: a datapoint exists for that period and is silent about what is in it. That is the same
#: line ``CataloguePort`` draws, drawn again in the storage so that stage 2 cannot acquire
#: the ability to peek at a figure while deciding which indicator the reader meant.
FACT_PERIODS_TABLE: Final = "detail_fact_periods"

_TABLE_PREFIX: Final = "vec_"


def collection_table(collection: Collection) -> str:
    """The table name holding *collection*'s vectors.

    Derived from the collection rather than written out three times: the shape is
    identical for all three, and a hand-written name is how a fourth collection gets a
    table that differs from the others in one column nobody notices.
    """
    return f"{_TABLE_PREFIX}{collection.value}"


def _collection_ddl(collection: Collection) -> tuple[str, str]:
    table = collection_table(collection)
    create = f"""
    CREATE TABLE {table} (
        id           TEXT NOT NULL PRIMARY KEY,
        lang         TEXT NOT NULL CHECK (lang IN ('en', 'ar')),
        -- The exact text that was embedded, kept for audit and for display: a retrieved
        -- passage must be quotable as the build saw it, not as a later re-derivation
        -- would render it.
        text         TEXT NOT NULL,
        -- float32, little-endian, L2-normalised at build time so that cosine is a plain
        -- dot product at query time.
        embedding    BLOB NOT NULL,
        -- The scope columns of AD-14, each genuinely absent for some rows: an article
        -- has no detail and no period, a national figure has no country, and only an
        -- article carries a date.
        detail_id    TEXT,
        period       TEXT,
        country_id   TEXT,
        article_date TEXT
    ) STRICT
    """
    scope_index = (
        f"CREATE INDEX {table}_scope ON {table}(detail_id, period, country_id, lang)"
    )
    return create, scope_index


def create_index_schema(connection: sqlite3.Connection) -> None:
    """Create every collection table, its scope index, and the provenance table.

    All three collections are created in every generation, including the ones a
    particular build has no rows for. An empty collection and a missing one are different
    failures -- the first returns nothing, the second cannot be searched at all -- and a
    file whose shape depends on what the corpus happened to contain would make them
    indistinguishable at the call site.
    """
    for collection in Collection:
        create, scope_index = _collection_ddl(collection)
        connection.execute(create)
        connection.execute(scope_index)
    # The lexical half of the ``names`` hybrid, in the same file as the vectors it is
    # fused with (Story 2.2). Only ``names`` has one: ``analyst`` retrieval is governed by
    # AD-14's mandatory scope pre-filter rather than by lexical recall, and ``articles``
    # has no key to filter on at all and is the one path AD-30 gives a derived floor.
    create_names_lexical_table(connection)
    _create_facts_tables(connection)
    connection.execute(
        f"""
        CREATE TABLE {META_TABLE} (
            -- One row, and the CHECK is what makes that true rather than intended.
            only_row         INTEGER NOT NULL PRIMARY KEY CHECK (only_row = 1),
            built_at         TEXT    NOT NULL,
            source_identity  TEXT    NOT NULL,
            dimensions       INTEGER NOT NULL CHECK (dimensions >= 1)
        ) STRICT
        """
    )
    connection.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")


def _create_facts_tables(connection: sqlite3.Connection) -> None:
    """The two tables holding stage 2's structural facts (Story 2.4).

    Two tables rather than one with a packed period list, because "does this detail
    publish a row for 2024-Q1" is a membership question asked once per candidate per
    question, and a delimited string in a column is a parser waiting to disagree with the
    one in ``domain/period.py`` about what a period is.
    """
    connection.execute(
        f"""
        CREATE TABLE {FACTS_TABLE} (
            detail_id       TEXT NOT NULL PRIMARY KEY,
            indicator_id    TEXT NOT NULL,
            -- The published unit's name, as published. Classified into a shape by the
            -- reviewed table in `rules/` at query time rather than here: the shape is a
            -- reader-affecting decision (AD-11) and baking it into the file would freeze
            -- one reviewer's reading of it into every generation ever built.
            unit_name       TEXT NOT NULL,
            -- The entity the parent indicator belongs to -- a sector, a special entity,
            -- a project -- already folded by the engine's one `normalise()` (AD-26), in
            -- both published languages, tab-separated. Folded at build time because the
            -- comparison is against a folded question and folding 289 entity names on
            -- every question is work with one possible answer.
            entity_folded   TEXT NOT NULL,
            classification  TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        f"""
        CREATE TABLE {FACT_PERIODS_TABLE} (
            detail_id    TEXT NOT NULL REFERENCES {FACTS_TABLE}(detail_id),
            period       TEXT NOT NULL,
            -- A country id when this is a benchmark row, NULL when it is the national
            -- one. The same spelling of national scope the read model uses (AD-5), so
            -- the two files cannot disagree about what a national row is.
            country_id   TEXT,
            PRIMARY KEY (detail_id, period, country_id)
        )
        """
    )
    connection.execute(
        f"CREATE INDEX {FACT_PERIODS_TABLE}_by_detail ON {FACT_PERIODS_TABLE}(detail_id)"
    )
