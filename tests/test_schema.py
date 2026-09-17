"""The schema step: three files, one owner per table, WAL read back, version enforced.

Story 1.6's acceptance criteria, asserted against the databases the step actually
builds rather than against the DDL text. Everything here runs on a temporary directory
or in memory -- no service, no shared environment, nothing left behind.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from askai.adapters.readmodel.schema import READ_MODEL
from askai.adapters.store.database import (
    SCHEMA_VERSION,
    DatabaseSchema,
    JournalModeError,
    SchemaDriftError,
    SchemaError,
    SchemaVersionMismatch,
    Table,
    connect_database,
    create_database,
    declared_tables,
)
from askai.adapters.store.provision import (
    ALL_SCHEMAS,
    TABLE_OWNERS,
    Databases,
    open_databases,
    provision,
)
from askai.adapters.store.schema import RECORD_STORE, SEMANTIC_INDEX
from askai.config.database import (
    DATABASE_DIR_ENV,
    ConfigError,
    DatabasePaths,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"

#: Every table the estate declares, and only those. Written out rather than derived from
#: the schemas, so adding a table has to be a decision taken here too -- which is how a
#: vector collection arriving early gets caught.
#:
#: ``analysis`` is the one addition to Epic 1's set. It is here, not in the index file,
#: because it is fetched by exact key: the semantic index finds *which* passage is
#: relevant, and the read model holds it.
EPIC_1_TABLES: Final = frozenset(
    {
        "catalogue",
        "detail",
        "datapoint",
        "analysis",
        "ref_country",
        "ref_lookup",
        "record",
        "conversation_turn",
    }
)


@pytest.fixture
def paths(tmp_path: Path) -> DatabasePaths:
    return DatabasePaths.beneath(tmp_path / "data")


@pytest.fixture
def databases(paths: DatabasePaths) -> Iterator[Databases]:
    with provision(paths) as created:
        yield created


@pytest.fixture
def in_memory() -> Iterator[Databases]:
    with provision() as created:
        yield created


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _scalar(connection: sqlite3.Connection, sql: str) -> object:
    row = connection.execute(sql).fetchone()
    assert row is not None
    value: object = row[0]
    return value


# ------------------------------------------------------- three distinct database files


def test_the_step_creates_three_distinct_files(paths: DatabasePaths, databases: Databases) -> None:
    files = [paths.read_model, paths.record_store, paths.semantic_index]
    assert all(path.is_file() for path in files), files
    assert len({path.resolve() for path in files}) == 3


def test_the_index_is_its_own_file_so_a_rebuild_never_shares_the_write_lock(
    paths: DatabasePaths, databases: Databases
) -> None:
    """AD-20's reason for the split, stated as a property of the paths."""
    assert paths.semantic_index != paths.read_model
    assert paths.semantic_index != paths.record_store


def test_two_databases_may_not_be_one_file(tmp_path: Path) -> None:
    same = tmp_path / "everything.sqlite3"
    with pytest.raises(ConfigError) as excinfo:
        DatabasePaths(read_model=same, record_store=same, semantic_index=tmp_path / "index")
    assert "three distinct files" in str(excinfo.value)


def test_the_index_database_declares_no_tables_in_epic_1(databases: Databases) -> None:
    """Vector collections arrive with Epic 2 and Epic 6, not here."""
    assert SEMANTIC_INDEX.tables == ()
    assert _table_names(databases.semantic_index) == set()


# ------------------------------------------------------------------ only Epic 1's tables


def test_only_the_tables_epic_1_needs_exist(databases: Databases) -> None:
    found = (
        _table_names(databases.read_model)
        | _table_names(databases.record_store)
        | _table_names(databases.semantic_index)
    )
    assert found == set(EPIC_1_TABLES)


def test_no_vector_table_was_created_early(databases: Databases) -> None:
    """A collection table must arrive with the story that fills it, in the index file."""
    forbidden = ("vector", "embedding", "vec_", "chunk", "fts")
    for connection in (databases.read_model, databases.record_store, databases.semantic_index):
        for name in _table_names(connection):
            assert not any(word in name.lower() for word in forbidden), name


def test_each_declared_table_is_created_in_its_own_database(databases: Databases) -> None:
    for schema, connection in (
        (READ_MODEL, databases.read_model),
        (RECORD_STORE, databases.record_store),
        (SEMANTIC_INDEX, databases.semantic_index),
    ):
        assert _table_names(connection) == {table.name for table in schema.tables}


# ------------------------------------------------------------------------ table ownership

# Only string constants are scanned, and docstrings are skipped: a docstring saying
# "INSERT, UPDATE and DELETE" is prose about the rule, not a write, and a scanner that
# could not tell the two apart would be turned off the first time it cried wolf.
_DML: Final = re.compile(
    r"(?:insert\s+or\s+\w+\s+into|insert\s+into|replace\s+into|delete\s+from|(?<!do )\bupdate)"
    r"\s+[\"'`\[]?(?P<table>\w+)",
    re.IGNORECASE,
)


def _sql_literals(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _tables_written_in(source: str) -> set[str]:
    return {
        match.group("table").lower()
        for literal in _sql_literals(source)
        for match in _DML.finditer(literal)
    }


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def test_every_table_has_exactly_one_owner() -> None:
    assert set(TABLE_OWNERS) == set(EPIC_1_TABLES)
    for schema in ALL_SCHEMAS:
        for table in schema.tables:
            assert TABLE_OWNERS[table.name] == table.owner


def test_a_table_may_not_be_declared_in_two_databases() -> None:
    twice = DatabaseSchema(
        name="rogue",
        tables=(Table(name="datapoint", owner="askai.adapters.store", ddl="CREATE TABLE x(a)"),),
    )
    with pytest.raises(SchemaError) as excinfo:
        declared_tables(READ_MODEL, twice)
    assert "exactly one owner" in str(excinfo.value)


#: The one module exempt from table ownership, and the reason.
#:
#: ``preflight`` proves the *filesystem* behaves -- WAL is active, the sidecars can be
#: created, a reader is not blocked by a writer, a row survives a close and reopen. Every
#: one of those needs a real write, and doing them against the estate would mean the
#: durability check could corrupt the thing it is checking. So it writes throwaway probe
#: databases it creates and deletes, which are not the estate and are declared by no
#: schema -- correctly, since nothing else may ever read them.
#:
#: The exemption is bounded by the test below: every table it writes must be probe-named,
#: so this cannot quietly widen into a licence to write the read model.
_PROBE_ONLY_MODULES = frozenset({"askai.adapters.store.preflight"})
_PROBE_TABLE_PREFIX = "probe"


def test_no_module_writes_a_table_it_does_not_own() -> None:
    """AD-20, checked against the source rather than against a comment.

    Creating a table is not writing it -- the schema step executes every ``CREATE
    TABLE`` and owns none of them. This is about INSERT, UPDATE, DELETE and REPLACE.
    """
    offences: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        module = _module_name(path)
        if module in _PROBE_ONLY_MODULES:
            continue
        for table in sorted(_tables_written_in(path.read_text(encoding="utf-8"))):
            owner = TABLE_OWNERS.get(table)
            if owner is None:
                offences.append(f"{module} writes {table!r}, which no schema declares")
            elif module != owner and not module.startswith(f"{owner}."):
                offences.append(f"{module} writes {table!r}, owned by {owner}")
    assert offences == []


def test_the_exempt_module_writes_only_probe_tables() -> None:
    """The bound on the exemption above, without which it is a hole rather than a carve-out."""
    for module in sorted(_PROBE_ONLY_MODULES):
        path = PACKAGE_ROOT.joinpath(*module.split(".")[1:]).with_suffix(".py")
        assert path.is_file(), f"{module} is exempt but does not exist"
        written = sorted(_tables_written_in(path.read_text(encoding="utf-8")))
        strays = [table for table in written if not table.startswith(_PROBE_TABLE_PREFIX)]
        assert not strays, f"{module} is probe-exempt but writes {strays}"
        assert written, f"{module} is exempt from ownership but writes nothing; drop the exemption"


def test_the_ownership_scanner_sees_a_write() -> None:
    """The check above is only worth its green while this stays true."""
    source = (
        '"""Docstring mentioning INSERT INTO record."""\n'
        'SQL = "INSERT INTO datapoint (a) VALUES (1)"\n'
    )
    assert _tables_written_in(source) == {"datapoint"}


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE datapoint SET actual = '1'",
        "DELETE FROM datapoint WHERE period = '2025'",
        "REPLACE INTO datapoint VALUES (1)",
        "insert or replace into datapoint values (1)",
    ],
)
def test_the_ownership_scanner_sees_every_write_form(statement: str) -> None:
    assert _tables_written_in(f'SQL = "{statement}"') == {"datapoint"}


def test_the_ownership_scanner_ignores_prose_and_upsert_clauses() -> None:
    source = (
        '"""INSERT INTO record is described here."""\n'
        'SQL = "INSERT INTO record (a) VALUES (1) ON CONFLICT DO UPDATE SET a = 2"\n'
    )
    assert _tables_written_in(source) == {"record"}


# --------------------------------------------------------------------------- WAL, once


def test_wal_is_on_every_file_and_is_read_back(databases: Databases) -> None:
    for connection in (databases.read_model, databases.record_store, databases.semantic_index):
        assert _scalar(connection, "PRAGMA journal_mode") == "wal"


def test_opening_does_not_set_the_journal_mode_but_does_verify_it(
    paths: DatabasePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Set once at startup, not per connection" -- observed, not asserted in a docstring."""
    provision(paths).close()

    statements: list[str] = []
    real_connect = sqlite3.connect

    def spy(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    # The adapter holds no reference of its own to `connect`, so patching it on the
    # module is what the adapter will call. Undone by monkeypatch at teardown.
    monkeypatch.setattr(sqlite3, "connect", spy)
    open_databases(paths).close()

    assignments = [sql for sql in statements if re.search(r"journal_mode\s*=", sql, re.IGNORECASE)]
    assert assignments == [], "journal mode is a property of the file, set by the schema step"
    assert [sql for sql in statements if "journal_mode" in sql.lower()], "it must be read back"


def test_a_file_that_is_not_in_wal_is_refused(paths: DatabasePaths) -> None:
    provision(paths).close()
    tamper = sqlite3.connect(str(paths.record_store))
    tamper.execute("PRAGMA journal_mode = delete")
    tamper.close()

    with pytest.raises(JournalModeError) as excinfo:
        open_databases(paths)
    assert "record store" in str(excinfo.value)
    assert "delete" in str(excinfo.value)


def test_an_in_memory_database_is_accepted_without_wal(in_memory: Databases) -> None:
    """A database with no file cannot have a write-ahead log; it says so and is allowed."""
    assert _scalar(in_memory.read_model, "PRAGMA journal_mode") == "memory"


# ------------------------------------------------------------------------ schema version


def test_every_file_carries_the_schema_version(databases: Databases) -> None:
    for connection in (databases.read_model, databases.record_store, databases.semantic_index):
        assert _scalar(connection, "PRAGMA user_version") == SCHEMA_VERSION


def test_startup_fails_loudly_on_a_version_mismatch(paths: DatabasePaths) -> None:
    provision(paths).close()
    tamper = sqlite3.connect(str(paths.read_model))
    tamper.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    tamper.close()

    with pytest.raises(SchemaVersionMismatch) as excinfo:
        open_databases(paths)
    message = str(excinfo.value)
    assert str(paths.read_model) in message, "the failure must name the file"
    assert f"version {SCHEMA_VERSION + 1}" in message, "it must name what it found"
    assert f"writes {SCHEMA_VERSION}" in message, "and what this build expects"


def test_an_unprovisioned_database_is_not_created_by_opening_it(paths: DatabasePaths) -> None:
    with pytest.raises(SchemaError) as excinfo:
        open_databases(paths)
    assert "does not exist" in str(excinfo.value)
    assert not paths.read_model.exists()


def test_an_undeclared_table_in_the_file_is_a_failure(paths: DatabasePaths) -> None:
    provision(paths).close()
    tamper = sqlite3.connect(str(paths.record_store))
    tamper.execute("CREATE TABLE stowaway (a TEXT)")
    tamper.close()

    with pytest.raises(SchemaDriftError) as excinfo:
        open_databases(paths)
    assert "stowaway" in str(excinfo.value)


def test_the_step_is_repeatable(paths: DatabasePaths) -> None:
    with provision(paths) as first:
        first.read_model.execute(
            "INSERT INTO ref_country (country_id, code, name_en, name_ar) "
            "VALUES ('c1', 'BH', 'Bahrain', 'البحرين')"
        )
        first.read_model.commit()

    with provision(paths) as second:
        assert _scalar(second.read_model, "SELECT count(*) FROM ref_country") == 1
        assert _table_names(second.read_model) == {table.name for table in READ_MODEL.tables}


# ------------------------------------------------------------- the datapoint identity key


def test_the_datapoint_key_is_detail_period_country(in_memory: Databases) -> None:
    columns = list(in_memory.read_model.execute("PRAGMA table_info(datapoint)"))
    key = [str(row[1]) for row in sorted(columns, key=lambda row: int(row[5])) if int(row[5]) > 0]
    assert key == ["detail_id", "period", "country_id"]


def test_country_id_is_nullable_because_blank_is_the_national_marker(
    in_memory: Databases,
) -> None:
    columns = in_memory.read_model.execute("PRAGMA table_info(datapoint)")
    nullable = {str(row[1]): not int(row[3]) for row in columns}
    assert nullable["country_id"] is True
    assert nullable["detail_id"] is False
    assert nullable["period"] is False


def test_grain_is_not_a_column_anywhere(databases: Databases) -> None:
    """The period string carries the grain; a column would be a second opinion."""
    for schema, connection in (
        (READ_MODEL, databases.read_model),
        (RECORD_STORE, databases.record_store),
    ):
        for table in schema.tables:
            columns = [
                str(row[1]) for row in connection.execute(f"PRAGMA table_info({table.name})")
            ]
            assert not [name for name in columns if "grain" in name.lower()], table.name
            assert not [name for name in columns if name.lower() == "interval"], table.name


def _seed_one_detail(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO ref_lookup (lookup_id, lookup_type, name_en, name_ar) "
        "VALUES ('l1', 'Units', 'Percent', 'نسبة')"
    )
    connection.execute(
        "INSERT INTO ref_country (country_id, code, name_en, name_ar) "
        "VALUES ('c1', 'BH', 'Bahrain', 'البحرين')"
    )
    connection.execute(
        "INSERT INTO catalogue (indicator_id, name_en, name_ar, classification, priority_type) "
        "VALUES ('i1', 'Inflation', 'التضخم', 'Sectors', 'Priority')"
    )
    connection.execute(
        "INSERT INTO detail (detail_id, indicator_id, name_en, name_ar, unit_id, "
        "data_source_id, polarity_id, value_type_id, aggregation_type_id, is_main) "
        "VALUES ('d1', 'i1', 'Headline', 'العام', 'l1', 'l1', 'l1', 'l1', 'l1', 1)"
    )
    connection.commit()


def test_one_national_row_per_detail_and_period(in_memory: Databases) -> None:
    """The primary key alone cannot enforce this: two NULLs compare distinct in sqlite."""
    connection = in_memory.read_model
    _seed_one_detail(connection)
    connection.execute(
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
        "VALUES ('d1', '2025', NULL, 'p1', '2.5')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
            "VALUES ('d1', '2025', NULL, 'p2', '9.9')"
        )


def test_one_row_per_detail_period_and_named_country(in_memory: Databases) -> None:
    connection = in_memory.read_model
    _seed_one_detail(connection)
    connection.execute(
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
        "VALUES ('d1', '2025', 'c1', 'p1', '2.5')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
            "VALUES ('d1', '2025', 'c1', 'p2', '9.9')"
        )


def test_the_national_row_and_a_country_row_coexist(in_memory: Databases) -> None:
    connection = in_memory.read_model
    _seed_one_detail(connection)
    connection.executescript(
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
        "VALUES ('d1', '2025', NULL, 'p1', '2.5');"
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
        "VALUES ('d1', '2025', 'c1', 'p2', '3.5');"
    )
    assert _scalar(connection, "SELECT count(*) FROM datapoint") == 2


@pytest.mark.parametrize("period", ["2025", "2025-Q1", "2025-Q4", "2025-01", "2025-12"])
def test_the_published_period_forms_are_accepted(in_memory: Databases, period: str) -> None:
    connection = in_memory.read_model
    _seed_one_detail(connection)
    connection.execute(
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id) "
        "VALUES ('d1', ?, NULL, 'p1')",
        (period,),
    )


@pytest.mark.parametrize("period", ["2025-13", "2025-Q5", "last year", "2025-1", "25", ""])
def test_a_period_that_carries_no_grain_is_refused(in_memory: Databases, period: str) -> None:
    connection = in_memory.read_model
    _seed_one_detail(connection)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id) "
            "VALUES ('d1', ?, NULL, 'p1')",
            (period,),
        )


def test_a_datapoint_cannot_reference_an_unknown_detail(in_memory: Databases) -> None:
    """Foreign keys are enforced, so the references in the DDL are not decoration."""
    connection = in_memory.read_model
    _seed_one_detail(connection)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id) "
            "VALUES ('nobody', '2025', NULL, 'p1')"
        )


def test_a_confidential_indicator_cannot_be_stored(in_memory: Databases) -> None:
    """Excluded from the read model entirely, so it cannot appear in any count or list."""
    with pytest.raises(sqlite3.IntegrityError):
        in_memory.read_model.execute(
            "INSERT INTO catalogue (indicator_id, name_en, name_ar, classification, "
            "priority_type) VALUES ('i9', 'Secret', 'سري', 'Sectors', 'Confidential')"
        )


def test_published_values_are_stored_as_text_not_float(in_memory: Databases) -> None:
    """Decimal, never float -- the rounding defect must not arrive through storage."""
    connection = in_memory.read_model
    _seed_one_detail(connection)
    connection.execute(
        "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id, actual) "
        "VALUES ('d1', '2025', NULL, 'p1', '0.1')"
    )
    assert _scalar(connection, "SELECT actual FROM datapoint") == "0.1"
    declared = {
        str(row[1]): str(row[2]) for row in connection.execute("PRAGMA table_info(datapoint)")
    }
    value_columns = [name for name in declared if name in {"actual", "target", "baseline"}]
    assert value_columns, "the datapoint table must carry the published measures"
    assert all(declared[name] == "TEXT" for name in value_columns), declared


# -------------------------------------------------------------------- the record store


def test_a_record_can_be_written_and_read_back(in_memory: Databases) -> None:
    connection = in_memory.record_store
    connection.execute(
        "INSERT INTO record (record_id, recorded_at, caller_id, identity_asserted, language, "
        "question, spec_version, spec_json, answer_json) "
        "VALUES ('r1', '2026-09-15T10:00:00Z', NULL, 0, 'en', 'what is inflation', 1, '{}', '{}')"
    )
    assert _scalar(connection, "SELECT identity_asserted FROM record") == 0


def test_an_anonymous_caller_is_recorded_as_a_fact_not_a_blank(in_memory: Databases) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        in_memory.record_store.execute(
            "INSERT INTO record (record_id, recorded_at, identity_asserted, language, question, "
            "spec_version, spec_json, answer_json) "
            "VALUES ('r2', '2026-09-15T10:00:00Z', NULL, 'en', 'q', 1, '{}', '{}')"
        )


def test_a_conversation_turn_is_unique_within_its_conversation(in_memory: Databases) -> None:
    connection = in_memory.record_store
    connection.execute(
        "INSERT INTO conversation_turn (conversation_id, turn, asked_at, question, spec_json) "
        "VALUES ('c1', 1, '2026-09-15T10:00:00Z', 'q', '{}')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO conversation_turn (conversation_id, turn, asked_at, question, spec_json) "
            "VALUES ('c1', 1, '2026-09-15T10:01:00Z', 'q2', '{}')"
        )


# ------------------------------------------------------------- no shared environment (NFR-6)


def test_two_in_memory_estates_share_nothing(in_memory: Databases) -> None:
    with provision() as other:
        _seed_one_detail(in_memory.read_model)
        assert _scalar(in_memory.read_model, "SELECT count(*) FROM detail") == 1
        assert _scalar(other.read_model, "SELECT count(*) FROM detail") == 0


def test_the_answer_path_databases_need_no_environment_variable() -> None:
    """``provision()`` with no argument reads nothing: no directory, no settings, no service."""
    with provision() as created:
        assert _table_names(created.read_model) == {table.name for table in READ_MODEL.tables}


def test_a_missing_database_directory_setting_fails_loudly() -> None:
    with pytest.raises(ConfigError) as excinfo:
        DatabasePaths.from_env({})
    assert DATABASE_DIR_ENV in str(excinfo.value)


def test_a_blank_database_directory_setting_fails_loudly() -> None:
    with pytest.raises(ConfigError):
        DatabasePaths.from_env({DATABASE_DIR_ENV: "   "})


def test_the_database_directory_setting_is_resolved_to_absolute_paths(tmp_path: Path) -> None:
    resolved = DatabasePaths.from_env({DATABASE_DIR_ENV: str(tmp_path)})
    assert resolved.read_model.is_absolute()
    assert resolved.read_model.parent == tmp_path.resolve()


def _reads_the_environment(tree: ast.Module) -> bool:
    """Does this module actually read the environment, as opposed to mentioning it?

    Parsed rather than grepped. A substring search flags ``src/askai/adapters/store/cli.py``,
    whose only occurrence of ``os.getenv`` is a docstring saying not to use it -- which is
    the right thing to write and the wrong thing to fail a build on.
    """
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"environ", "getenv"}
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "os"
            and any(alias.name in {"environ", "getenv"} for alias in node.names)
        ):
            return True
    return False


def test_the_environment_is_read_only_in_config() -> None:
    """The typed settings object is the only in-project reader of the environment."""
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if _reads_the_environment(ast.parse(path.read_text(encoding="utf-8")))
        and path.parent != PACKAGE_ROOT / "config"
    ]
    assert offenders == []


def test_the_environment_scanner_tells_a_read_from_a_mention() -> None:
    """Both halves, or the scan above is either vacuous or a nuisance."""
    assert _reads_the_environment(ast.parse("import os\nD = os.environ['X']\n"))
    assert _reads_the_environment(ast.parse("from os import getenv\nD = getenv('X')\n"))
    assert not _reads_the_environment(ast.parse('"""Never call os.getenv here."""\n'))
    assert not _reads_the_environment(ast.parse("# os.environ is banned outside config/\n"))


def test_a_failed_creation_leaves_no_open_connection(tmp_path: Path) -> None:
    """A half-built database must not be handed back; the connection is closed on the way out."""
    broken = DatabaseSchema(
        name="broken",
        tables=(Table(name="oops", owner="askai.adapters.store", ddl="CREATE TABLE ( NOT SQL"),),
    )
    with pytest.raises(sqlite3.OperationalError):
        create_database(broken, tmp_path / "broken.sqlite3")


def test_connecting_to_a_database_built_by_this_step_verifies_rather_than_rebuilds(
    paths: DatabasePaths,
) -> None:
    provision(paths).close()
    connection = connect_database(READ_MODEL, paths.read_model)
    try:
        assert _table_names(connection) == {table.name for table in READ_MODEL.tables}
    finally:
        connection.close()
