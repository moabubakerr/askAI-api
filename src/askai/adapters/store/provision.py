"""The schema step: three database files, created once, opened with their version checked.

Purity: IO.

This is the one place that says "three databases, these three schemas". It lives in
``store/`` because ``store/`` owns the sqlite connection policy, and it imports the read
model's table declarations rather than restating them -- ownership stays where the
tables are declared (AD-20), and the direction of the import is deliberate: the schema
step knows about the read model, the read model knows nothing about the schema step.

Creating a table is not writing it. This module executes every ``CREATE TABLE`` in the
estate and owns none of them; ``Table.owner`` governs INSERT, UPDATE and DELETE, which
is what AD-20's rule is about and what ``tests/test_schema.py`` checks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final, Self

from askai.adapters.readmodel.schema import READ_MODEL
from askai.adapters.store.database import (
    connect_database,
    create_database,
    declared_tables,
)
from askai.adapters.store.schema import RECORD_STORE, SEMANTIC_INDEX
from askai.config.database import DatabasePaths

__all__ = ["ALL_SCHEMAS", "TABLE_OWNERS", "Databases", "open_databases", "provision"]

#: The estate, in creation order.
ALL_SCHEMAS: Final = (READ_MODEL, RECORD_STORE, SEMANTIC_INDEX)

#: Every table in the estate and the single module permitted to write it. Built by
#: ``declared_tables``, so a table declared in two files fails at import rather than
#: producing a map that quietly keeps the last declaration.
TABLE_OWNERS: Final = declared_tables(*ALL_SCHEMAS)


@dataclass(frozen=True, slots=True)
class Databases:
    """One open connection per file, named by role rather than handed out as a tuple."""

    read_model: sqlite3.Connection
    record_store: sqlite3.Connection
    semantic_index: sqlite3.Connection

    def close(self) -> None:
        """Close all three. For in-memory databases this also destroys them."""
        for connection in (self.read_model, self.record_store, self.semantic_index):
            connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def provision(paths: DatabasePaths | None = None) -> Databases:
    """Create the three databases and return open connections to them.

    *paths* of ``None`` provisions all three in memory, each its own database, living
    only for as long as the returned connections. That is how the answer path is tested
    under NFR-6: the same step builds what the tests run against, so a test cannot pass
    against a hand-made table shape the real startup would reject, and no directory,
    service or environment variable is shared between two tests.

    Repeatable against an existing directory: it re-verifies rather than rebuilding, and
    a file at another schema version raises instead of being silently adopted.
    """
    if paths is None:
        return Databases(
            read_model=create_database(READ_MODEL),
            record_store=create_database(RECORD_STORE),
            semantic_index=create_database(SEMANTIC_INDEX),
        )
    return Databases(
        read_model=create_database(READ_MODEL, paths.read_model),
        record_store=create_database(RECORD_STORE, paths.record_store),
        semantic_index=create_database(SEMANTIC_INDEX, paths.semantic_index),
    )


def open_databases(paths: DatabasePaths) -> Databases:
    """Open the three already-provisioned databases, or fail loudly.

    What a process does at startup. It sets nothing: journal mode and schema version are
    read back and compared, so a file that was never provisioned, was provisioned by a
    different build, or is not in WAL stops the process here rather than at the first
    question.
    """
    return Databases(
        read_model=connect_database(READ_MODEL, paths.read_model),
        record_store=connect_database(RECORD_STORE, paths.record_store),
        semantic_index=connect_database(SEMANTIC_INDEX, paths.semantic_index),
    )
