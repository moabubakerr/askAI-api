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

from askai.ports.index import Collection

__all__ = [
    "INDEX_SCHEMA_VERSION",
    "META_TABLE",
    "collection_table",
    "create_index_schema",
]

#: The shape version of an index file. Its own number, not the estate's: a generation is
#: built by this module and read by this module, and a change to the collection shape
#: invalidates every generation ever built without touching the read model or the record
#: store. A file at another version is refused at load rather than read as this one.
INDEX_SCHEMA_VERSION: Final = 1

#: One row, recording what built the file. Read before anything else at load, because a
#: cosine between two vector spaces is a number with no meaning and this is what makes
#: it refusable.
META_TABLE: Final = "index_meta"

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
