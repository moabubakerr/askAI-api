"""The sqlite connection policy: one WAL setting, one schema version, loud on mismatch.

Purity: IO.

AD-20's connection policy in code. Three properties are load-bearing and each is a
function here rather than a convention:

**WAL is set once, at creation, and verified by reading it back.** ``journal_mode`` is a
persistent property of the database *file*, not of a connection, so setting it per
connection is a redundant write that serialises openers and hides the case where it did
not take. ``create_database`` sets it; ``connect_database`` only reads it and refuses to
hand back a connection to a file that is not in WAL.

**The schema carries a version**, stored in ``PRAGMA user_version`` -- a property of the
file, so it cannot be missing the way a metadata table can be absent or empty. Opening a
file whose version is not the one this build writes raises. Startup fails there; it does
not run a query against a shape it does not expect.

**A table is declared with its owner.** ``Table.owner`` is the one module AD-20 permits
to write it. Declaring it beside the DDL is what lets ``tests/test_schema.py`` check the
claim against the source rather than against a comment.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "SCHEMA_VERSION",
    "DatabaseSchema",
    "JournalModeError",
    "SchemaDriftError",
    "SchemaError",
    "SchemaVersionMismatch",
    "Table",
    "connect_database",
    "create_database",
    "declared_tables",
]

#: The shape version of every database this build creates. One number for all three
#: files: they are provisioned by a single step, so a shape change to any of them
#: invalidates the set, and three independently drifting numbers would be three ways to
#: be half-migrated.
SCHEMA_VERSION: Final = 1

#: Applied to every connection. WAL removes the reader/writer conflict but not the
#: writer/writer one, so a concurrent writer must wait rather than raise immediately.
BUSY_TIMEOUT_MS: Final = 5_000

_WAL: Final = "wal"
#: An in-memory database cannot journal to a WAL file, and reports this instead. It is
#: the one accepted answer other than ``wal``, and only for a database with no path.
_MEMORY: Final = "memory"


class SchemaError(RuntimeError):
    """The database on disk is not the one this build is written against."""


class SchemaVersionMismatch(SchemaError):
    """The file carries a schema version this build does not write.

    Raised at open, before any query. Running against an unexpected shape is how a
    column that moved becomes a wrong number rather than a failed startup.
    """

    def __init__(self, where: str, found: int, expected: int) -> None:
        super().__init__(
            f"{where} is at schema version {found}, this build writes {expected}; "
            "run the schema step against a fresh directory or migrate the file -- "
            "it will not be read at a version it was not written for"
        )
        self.found = found
        self.expected = expected


class JournalModeError(SchemaError):
    """The file is not in WAL. Not repaired on the fly -- see the module docstring."""


class SchemaDriftError(SchemaError):
    """The file holds a different set of tables than the schema declares."""


@dataclass(frozen=True, slots=True)
class Table:
    """One table, its DDL, and the single module AD-20 lets write it."""

    name: str
    owner: str
    ddl: str
    #: Indexes that are part of the table's identity rather than a tuning choice --
    #: the uniqueness the primary key cannot express, in particular.
    indexes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatabaseSchema:
    """The complete table set of one database file.

    ``name`` is the human name used in errors ("read model"), because a failure that
    names a path tells an operator which file, and a failure that names the role tells
    them what stopped working.
    """

    name: str
    tables: tuple[Table, ...]

    def __post_init__(self) -> None:
        names = [table.name for table in self.tables]
        if len(set(names)) != len(names):
            raise SchemaError(f"{self.name} declares a table twice: {sorted(names)}")


def declared_tables(*schemas: DatabaseSchema) -> dict[str, str]:
    """Table name to owning module across *schemas*, refusing any name declared twice.

    The table names are global across the three files on purpose. Two files each
    holding a ``datapoint`` table, owned by different modules, is precisely the
    ambiguity that makes "which module owns this table" unanswerable at a call site.
    """
    owners: dict[str, str] = {}
    for schema in schemas:
        for table in schema.tables:
            if table.name in owners:
                raise SchemaError(
                    f"table {table.name!r} is declared in more than one database "
                    f"({owners[table.name]} and {table.owner}); AD-20 gives a table "
                    "exactly one owner, so the name must be unique across all three"
                )
            owners[table.name] = table.owner
    return owners


def create_database(schema: DatabaseSchema, path: Path | None = None) -> sqlite3.Connection:
    """Create *schema*'s tables in the file at *path* and return an open connection.

    *path* of ``None`` is an in-memory database, which exists only for the returned
    connection: closing it destroys the database. That is the whole point for tests --
    NFR-6 wants the answer path exercised against a database this same step built, with
    no directory to clean up and nothing shared between two tests.

    Repeatable: running it against an already-provisioned directory re-verifies rather
    than rebuilding, and a file whose version does not match raises instead of being
    silently upgraded.
    """
    connection = _connect(path)
    try:
        _set_journal_mode_once(connection, path)
        _apply(connection, schema)
        _verify(connection, schema, path)
    except BaseException:
        connection.close()
        raise
    return connection


def connect_database(schema: DatabaseSchema, path: Path) -> sqlite3.Connection:
    """Open an already-created database, verifying what ``create_database`` set.

    Sets no persistent property. Everything WAL and version related is *read* here; a
    connection that repaired what it found would turn a provisioning failure into a
    per-process guess about which half of the estate is correct.
    """
    if not path.exists():
        raise SchemaError(
            f"the {schema.name} database does not exist at {path}; it is created by "
            "the schema step, never by opening it"
        )
    connection = _connect(path)
    try:
        _verify(connection, schema, path)
    except BaseException:
        connection.close()
        raise
    return connection


def _connect(path: Path | None) -> sqlite3.Connection:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(":memory:" if path is None else str(path))
    # Per-connection, and legitimately so: unlike journal mode, foreign key
    # enforcement is off by default on every new connection and is not stored in the
    # file. Without it the datapoint -> detail references below are documentation.
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def _set_journal_mode_once(connection: sqlite3.Connection, path: Path | None) -> None:
    """Set WAL only if the file is not already in it. In-memory is left alone."""
    if path is None:
        return
    if _read_text_pragma(connection, "journal_mode") == _WAL:
        return
    connection.execute(f"PRAGMA journal_mode = {_WAL}")


def _apply(connection: sqlite3.Connection, schema: DatabaseSchema) -> None:
    with connection:
        for table in schema.tables:
            connection.execute(table.ddl)
            for index in table.indexes:
                connection.execute(index)
        # `user_version` takes no parameter binding -- it is a pragma, not a query.
        # The value is this module's own integer constant, never caller input.
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _verify(connection: sqlite3.Connection, schema: DatabaseSchema, path: Path | None) -> None:
    where = schema.name if path is None else f"{schema.name} at {path}"

    version = _read_int_pragma(connection, "user_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionMismatch(where, found=version, expected=SCHEMA_VERSION)

    expected_mode = _MEMORY if path is None else _WAL
    mode = _read_text_pragma(connection, "journal_mode")
    if mode != expected_mode:
        raise JournalModeError(
            f"{where} is in journal mode {mode!r}, expected {expected_mode!r}; "
            "WAL is set once by the schema step and read back here, never assumed"
        )

    found = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    declared = {table.name for table in schema.tables}
    if found != declared:
        raise SchemaDriftError(
            f"{where} holds tables {sorted(found)}, the schema declares "
            f"{sorted(declared)}; a table nobody declared has no owner"
        )


def _read_text_pragma(connection: sqlite3.Connection, pragma: str) -> str:
    return str(_read_pragma(connection, pragma))


def _read_int_pragma(connection: sqlite3.Connection, pragma: str) -> int:
    value = _read_pragma(connection, pragma)
    if not isinstance(value, int):
        raise SchemaError(f"PRAGMA {pragma} returned {value!r}, expected an integer")
    return value


def _read_pragma(connection: sqlite3.Connection, pragma: str) -> object:
    row = connection.execute(f"PRAGMA {pragma}").fetchone()
    if row is None:
        raise SchemaError(f"PRAGMA {pragma} returned nothing")
    value: object = row[0]
    return value
