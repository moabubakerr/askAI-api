"""Story 1.16: one bounded record per answer, written once from the finished package.

Everything here runs against a database ``provision()`` built in memory or under
``tmp_path`` -- no service, no directory, no environment variable (NFR-6). The record is
asserted as it lands in the record store, not as the builder intended it: a test that
read back its own in-memory value could not tell a column that was never written from
one that was.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

import pytest

from askai.adapters.store.provision import TABLE_OWNERS, Databases, provision
from askai.adapters.store.records import DuplicateRecord, RecordWriteError, SqliteRecordStore
from askai.domain.degradation import Degradation
from askai.domain.element import Element, ElementClass
from askai.domain.period import Grain, Period
from askai.domain.scope import DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Exact,
    LastN,
    Latest,
    Measure,
    Operation,
    QuerySpec,
    Range,
    Unbound,
    period_field,
)
from askai.messages.lang import Lang
from askai.observability.identity import (
    MAX_ID_CHARS,
    Anonymous,
    Asserted,
    CallerIdentity,
    IdentityError,
    caller_identity,
)
from askai.observability.record import (
    MAX_RECORD_BYTES,
    SPEC_FIELDS,
    AnswerRecord,
    BindingMechanism,
    FieldBinding,
    PromptUse,
    RecordError,
    RuleFired,
    row_size_bytes,
    to_row,
)
from askai.observability.recorder import RecordAlreadyWritten, Recorder
from askai.ports.record import RecordPort, RecordRow

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"

#: The tables Story 1.16 concerns itself with, and their single owner per AD-20.
RECORD_STORE_TABLES: Final = frozenset({"record", "conversation_turn"})

TODAY: Final = date(2026, 9, 15)
NOW: Final = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


# ------------------------------------------------------------------------- fixtures


@pytest.fixture
def databases() -> Iterator[Databases]:
    with provision() as created:
        yield created


@pytest.fixture
def store(databases: Databases) -> SqliteRecordStore:
    return SqliteRecordStore(databases.record_store)


@pytest.fixture
def recorder(store: SqliteRecordStore) -> Recorder:
    return Recorder(store)


def a_spec(
    *,
    detail: object = None,
    period: object = None,
    country_scope: object = None,
) -> QuerySpec:
    return QuerySpec(
        detail=Bound("d-inflation-headline") if detail is None else detail,  # type: ignore[arg-type]
        period=period_field(Exact(Period("2025-Q2"))) if period is None else period,  # type: ignore[arg-type]
        country_scope=Bound(National()) if country_scope is None else country_scope,  # type: ignore[arg-type]
        measure=Bound(Measure.ACTUAL),
        operation=Bound(Operation.VALUE),
        today=TODAY,
    )


def all_bound(
    mechanism: BindingMechanism = BindingMechanism.NAMED_IN_QUESTION,
) -> tuple[FieldBinding, ...]:
    return tuple(FieldBinding(field=name, mechanism=mechanism) for name in SPEC_FIELDS)


def a_record(
    *,
    record_id: str = "r-0001",
    identity: CallerIdentity | None = None,
    spec: QuerySpec | None = None,
    bindings: tuple[FieldBinding, ...] | None = None,
    question: str = "what is headline inflation",
    **extra: Any,
) -> AnswerRecord:
    return AnswerRecord(
        record_id=record_id,
        recorded_at=NOW,
        identity=Anonymous() if identity is None else identity,
        language=Lang.EN,
        question=question,
        spec=a_spec() if spec is None else spec,
        bindings=all_bound() if bindings is None else bindings,
        **extra,
    )


def stored_rows(databases: Databases) -> list[dict[str, Any]]:
    databases.record_store.row_factory = sqlite3.Row
    try:
        rows = databases.record_store.execute("SELECT * FROM record ORDER BY record_id").fetchall()
    finally:
        databases.record_store.row_factory = None
    return [dict(row) for row in rows]


def evidence_of(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(row["answer_json"])
    return payload


def spec_of(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(row["spec_json"])
    return payload


# --------------------------------------------------- exactly one record per request


def test_a_finished_answer_produces_exactly_one_record(
    recorder: Recorder, databases: Databases
) -> None:
    recorder.record(a_record())
    assert len(stored_rows(databases)) == 1


def test_a_recorder_refuses_to_write_twice(recorder: Recorder, databases: Databases) -> None:
    """AD-16: one record per request, so a second call is a defect, not an update."""
    recorder.record(a_record())
    with pytest.raises(RecordAlreadyWritten) as excinfo:
        recorder.record(a_record(record_id="r-0002"))
    assert "r-0001" in str(excinfo.value)
    assert len(stored_rows(databases)) == 1


def test_the_store_refuses_a_second_record_for_the_same_request(
    store: SqliteRecordStore, databases: Databases
) -> None:
    """Belt and braces: a fresh recorder cannot get round the one-record rule either."""
    Recorder(store).record(a_record())
    with pytest.raises(DuplicateRecord):
        Recorder(store).record(a_record())
    assert len(stored_rows(databases)) == 1


def test_a_malformed_row_is_not_reported_as_a_duplicate(store: SqliteRecordStore) -> None:
    row = RecordRow(
        record_id="r-bad",
        recorded_at=NOW.isoformat(),
        caller_id=None,
        identity_asserted=False,
        language="fr",
        question="q",
        spec_version=1,
        spec_json="{}",
        answer_json="{}",
        data_as_of=None,
        conversation_id=None,
        turn=None,
    )
    with pytest.raises(RecordWriteError) as excinfo:
        store.write(row)
    assert not isinstance(excinfo.value, DuplicateRecord)


def test_the_record_is_written_after_the_package_is_final(recorder: Recorder) -> None:
    """"Final" is a property of the value, not a moment anyone must remember.

    The record is frozen and the port offers only ``write`` -- there is no shape in
    which a record is written early and completed later.
    """
    record = a_record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.row_ids = ("late",)  # type: ignore[misc]
    amendable = {"update", "amend", "append", "finish"}
    amendments = [name for name in dir(RecordPort) if name in amendable]
    assert amendments == []
    recorder.record(record)


def test_no_module_but_the_store_adapter_writes_the_record_tables() -> None:
    """The acceptance criterion's "asserted by exclusive table ownership and a test"."""
    assert {TABLE_OWNERS[table] for table in RECORD_STORE_TABLES} == {"askai.adapters.store"}
    writers = {
        table: sorted(modules) for table, modules in _writers_under_src().items()
    }
    for table in RECORD_STORE_TABLES:
        for module in writers.get(table, []):
            assert module.startswith("askai.adapters.store"), f"{module} writes {table}"
    assert writers.get("record") == ["askai.adapters.store.records"]


def test_the_writer_scan_would_catch_an_offender() -> None:
    source = 'SQL = "INSERT INTO record (record_id) VALUES (?)"\n'
    assert _tables_written_in(source) == {"record"}


# ------------------------------------------------------- what one record must contain


def test_the_record_carries_everything_ad_16_requires(
    recorder: Recorder, databases: Databases
) -> None:
    record = a_record(
        identity=Asserted("u-114"),
        row_ids=("datapoint:d-inflation-headline|2025-Q2|national",),
        rules_fired=(RuleFired("R-DISPLAY-ROUNDING", outcome="1 decimal"),),
        degradations=(Degradation(kind="analysis_absent", where="execute", detail="no P04 row"),),
        prompts=(PromptUse(prompt_id="narrate", version="3", prompt_hash="ab12cd"),),
        elements=(Element("2.5%", ElementClass.MEASURED, "datapoint:d-inflation-headline"),),
        data_as_of="2026-09-01",
    )
    recorder.record(record)

    (row,) = stored_rows(databases)
    spec = spec_of(row)
    evidence = evidence_of(row)

    assert row["spec_version"] == record.spec.spec_version
    assert spec["today"] == "2026-09-15"
    assert spec["detail"]["state"] == {"bound": "d-inflation-headline"}
    assert spec["period"]["state"] == {"bound": {"exact": "2025-Q2"}}
    assert spec["country_scope"]["state"] == {"bound": {"national": True}}
    assert spec["measure"]["state"] == {"bound": "actual"}
    assert spec["operation"]["state"] == {"bound": "value"}

    # The binding mechanism, per field -- not one mechanism for the whole spec.
    assert {name: spec[name]["binding"] for name in SPEC_FIELDS} == {
        name: "named-in-question" for name in SPEC_FIELDS
    }

    assert evidence["row_ids"] == ["datapoint:d-inflation-headline|2025-Q2|national"]
    assert evidence["rules_fired"] == [
        {"rule_id": "R-DISPLAY-ROUNDING", "outcome": "1 decimal"}
    ]
    assert evidence["degradations"] == [
        {"kind": "analysis_absent", "where": "execute", "detail": "no P04 row"}
    ]
    assert evidence["prompts"] == [{"prompt_id": "narrate", "version": "3", "hash": "ab12cd"}]
    assert evidence["data_as_of"] == "2026-09-01"
    assert row["caller_id"] == "u-114"
    assert row["identity_asserted"] == 1
    assert row["question"] == "what is headline inflation"
    assert row["language"] == "en"
    assert row["recorded_at"] == NOW.isoformat()


def test_a_deferred_field_records_what_it_resolved_to(
    recorder: Recorder, databases: Databases
) -> None:
    """"Latest" months later is unanswerable unless the record says which period it was."""
    bindings = tuple(
        FieldBinding(
            field=name,
            mechanism=BindingMechanism.NAMED_IN_QUESTION,
            note="resolved to 2025-Q2" if name == "period" else "",
        )
        for name in SPEC_FIELDS
    )
    recorder.record(
        a_record(spec=a_spec(period=period_field(Latest())), bindings=bindings),
    )
    spec = spec_of(stored_rows(databases)[0])
    assert spec["period"]["state"] == {"deferred": {"latest": True}}
    assert spec["period"]["note"] == "resolved to 2025-Q2"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (period_field(Exact(Period("2025"))), {"bound": {"exact": "2025"}}),
        (
            period_field(Range(Period("2022"), Period("2025"))),
            {"bound": {"range": {"start": "2022", "end": "2025"}}},
        ),
        (period_field(Latest()), {"deferred": {"latest": True}}),
        (
            period_field(LastN(5, Grain.YEARLY)),
            {"deferred": {"last_n": {"n": 5, "grain": "yearly"}}},
        ),
    ],
)
def test_every_period_request_shape_is_recorded_as_itself(
    recorder: Recorder, databases: Databases, value: object, expected: dict[str, Any]
) -> None:
    recorder.record(a_record(spec=a_spec(period=value)))
    assert spec_of(stored_rows(databases)[0])["period"]["state"] == expected


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (Bound(National()), {"bound": {"national": True}}),
        (Bound(DeclaredBenchmarks()), {"bound": {"declared_benchmarks": True}}),
        (
            Bound(Named(frozenset({"BH", "KW"}))),
            {"bound": {"named": {"countries": ["BH", "KW"], "dropped": 0}}},
        ),
        (Unbound("no country named"), {"unbound": "no country named"}),
    ],
)
def test_every_country_scope_shape_is_recorded_as_itself(
    recorder: Recorder, databases: Databases, scope: object, expected: dict[str, Any]
) -> None:
    bindings = tuple(
        FieldBinding(
            field=name,
            mechanism=(
                BindingMechanism.UNBOUND
                if name == "country_scope" and isinstance(scope, Unbound)
                else BindingMechanism.NAMED_IN_QUESTION
            ),
        )
        for name in SPEC_FIELDS
    )
    recorder.record(a_record(spec=a_spec(country_scope=scope), bindings=bindings))
    assert spec_of(stored_rows(databases)[0])["country_scope"]["state"] == expected


def test_a_record_must_say_how_every_spec_field_was_bound() -> None:
    incomplete = tuple(binding for binding in all_bound() if binding.field != "measure")
    with pytest.raises(RecordError) as excinfo:
        a_record(bindings=incomplete)
    assert "measure" in str(excinfo.value)


def test_a_field_may_not_be_bound_twice_in_one_record() -> None:
    doubled = (*all_bound(), FieldBinding("measure", BindingMechanism.RULE_DEFAULT))
    with pytest.raises(RecordError):
        a_record(bindings=doubled)


def test_a_binding_mechanism_may_not_disagree_with_the_spec(recorder: Recorder) -> None:
    """A record claiming a rule default for a field the spec left unbound is worse than none."""
    with pytest.raises(RecordError) as excinfo:
        a_record(
            spec=a_spec(detail=Unbound("two indicators match")),
            bindings=all_bound(),
        )
    assert "detail" in str(excinfo.value)


def test_an_unbound_field_is_recorded_as_unbound(recorder: Recorder, databases: Databases) -> None:
    bindings = tuple(
        FieldBinding(
            field=name,
            mechanism=(
                BindingMechanism.UNBOUND
                if name == "detail"
                else BindingMechanism.INHERITED_FROM_HISTORY
            ),
        )
        for name in SPEC_FIELDS
    )
    unbound_detail = a_spec(detail=Unbound("two indicators match"))
    recorder.record(a_record(spec=unbound_detail, bindings=bindings))
    spec = spec_of(stored_rows(databases)[0])
    assert spec["detail"] == {"binding": "unbound", "state": {"unbound": "two indicators match"}}


def test_a_field_binding_must_name_a_real_spec_field() -> None:
    with pytest.raises(RecordError):
        FieldBinding("grain", BindingMechanism.RULE_DEFAULT)


def test_the_bindable_fields_are_derived_from_the_spec() -> None:
    """A field added to ``QuerySpec`` makes every record incomplete until it is bound."""
    assert set(SPEC_FIELDS) == {
        field.name
        for field in dataclasses.fields(QuerySpec)
        if field.name not in {"today", "spec_version"}
    }


# ------------------------------------------------------------ the caller identity (AD-24)


def test_an_asserted_identity_is_recorded(recorder: Recorder, databases: Databases) -> None:
    recorder.record(a_record(identity=Asserted("u-114")))
    row = stored_rows(databases)[0]
    assert (row["caller_id"], row["identity_asserted"]) == ("u-114", 1)
    assert evidence_of(row)["identity"] == {"asserted": True, "caller_id": "u-114"}


def test_an_unasserted_identity_is_recorded_as_anonymous_and_so_is_that_fact(
    recorder: Recorder, databases: Databases
) -> None:
    recorder.record(a_record(identity=caller_identity(None)))
    row = stored_rows(databases)[0]
    assert (row["caller_id"], row["identity_asserted"]) == (None, 0)
    identity = evidence_of(row)["identity"]
    assert identity["asserted"] is False
    assert identity["anonymous"] is True
    assert "no identity asserted" in identity["reason"]


@pytest.mark.parametrize(
    ("asserted", "fragment"),
    [
        (None, "no identity asserted"),
        ("", "blank"),
        ("   ", "blank"),
        ("u" * (MAX_ID_CHARS + 1), "longer than"),
    ],
)
def test_every_way_an_identity_can_be_absent_is_distinguishable(
    asserted: str | None, fragment: str
) -> None:
    identity = caller_identity(asserted)
    assert isinstance(identity, Anonymous)
    assert fragment in identity.reason


def test_an_asserted_identity_survives_the_round_trip() -> None:
    assert caller_identity("u-114") == Asserted("u-114")


def test_an_identity_cannot_be_blank_by_construction() -> None:
    with pytest.raises(IdentityError):
        Asserted("   ")


def test_the_engine_never_authenticates_the_caller(recorder: Recorder) -> None:
    """AD-24: the engine consumes an asserted identity; it has no way to verify one.

    Asserted by absence: nothing in the record path validates, decodes or checks an
    identity, so no such call site can be pointed at.
    """
    sources = "\n".join(
        (PACKAGE_ROOT / "observability" / name).read_text(encoding="utf-8")
        for name in ("identity.py", "record.py", "recorder.py")
    )
    for forbidden in ("jwt", "verify", "authenticate", "authorize", "authorise", "password"):
        assert forbidden not in sources.lower(), forbidden


# ------------------------------------------------------------------- the size bound (NFR-9)


def oversized_record() -> AnswerRecord:
    """An answer no bound would survive by accident: a long question, thousands of row
    ids, hundreds of rules, degradations carrying pages of detail, and a named scope
    listing every country twice over."""
    return a_record(
        question="why " * 4_000,
        spec=a_spec(
            detail=Bound("d-" + "x" * 5_000),
            country_scope=Bound(Named(frozenset(f"C{index:04d}" for index in range(900)))),
        ),
        row_ids=tuple(f"datapoint:d-{index}|2025-Q2|national" for index in range(5_000)),
        rules_fired=tuple(
            RuleFired(f"R-AREA-{index}", outcome="fired " * 100) for index in range(500)
        ),
        degradations=tuple(
            Degradation(kind=f"k{index}", where="execute", detail="detail " * 500)
            for index in range(300)
        ),
        elements=tuple(
            Element("value " * 200, ElementClass.MEASURED, f"datapoint:d-{index}")
            for index in range(400)
        ),
    )


def test_an_oversized_answer_still_produces_a_record_within_the_bound(
    recorder: Recorder, databases: Databases
) -> None:
    row = recorder.record(oversized_record())
    assert row_size_bytes(row) <= MAX_RECORD_BYTES

    stored = stored_rows(databases)[0]
    stored_bytes = sum(
        len(str(value).encode("utf-8")) for value in stored.values() if value is not None
    )
    assert stored_bytes <= MAX_RECORD_BYTES


@pytest.mark.parametrize("scale", [0, 1, 10, 100, 1_000, 10_000])
def test_the_bound_holds_however_many_rows_the_answer_touched(scale: int) -> None:
    """The defect would be a record that grows with the answer. It does not."""
    row = to_row(
        a_record(
            row_ids=tuple(f"datapoint:d-{index}|2025|national" for index in range(scale)),
            degradations=tuple(
                Degradation(kind="k", where="execute", detail="d" * 200) for _ in range(scale)
            ),
        )
    )
    assert row_size_bytes(row) <= MAX_RECORD_BYTES


def test_nothing_is_dropped_silently(recorder: Recorder, databases: Databases) -> None:
    """Every reduction names its field and says how many survived and how many did not."""
    recorder.record(oversized_record())
    evidence = evidence_of(stored_rows(databases)[0])

    truncated = {entry["field"]: entry for entry in evidence["truncated"]}
    assert "row_ids" in truncated
    assert "question" in truncated
    assert all(entry["kept"] + entry["dropped"] > entry["kept"] for entry in truncated.values())
    assert all(entry["dropped"] > 0 for entry in truncated.values())

    # The counts survive even where the items do not, so a short list is never mistaken
    # for a shortened one.
    assert evidence["row_id_count"] == 5_000
    assert evidence["degradation_count"] == 300
    assert evidence["element_count"] == 400
    assert len(evidence["row_ids"]) < evidence["row_id_count"]


def test_a_truncated_value_never_reads_as_a_whole_one(
    recorder: Recorder, databases: Databases
) -> None:
    recorder.record(a_record(question="q" * 50_000))
    row = stored_rows(databases)[0]
    assert row["question"].endswith("...")
    assert len(row["question"]) < 50_000
    entries = {entry["field"]: entry for entry in evidence_of(row)["truncated"]}
    assert entries["question"]["kept"] + entries["question"]["dropped"] == 50_000


def test_a_record_within_the_bound_is_stored_whole(
    recorder: Recorder, databases: Databases
) -> None:
    """Truncation is the exception; an ordinary answer is recorded unreduced."""
    recorder.record(
        a_record(
            row_ids=tuple(f"datapoint:d-{index}|2025|national" for index in range(20)),
            rules_fired=(RuleFired("R-PERIOD-DEFAULT", outcome="yearly"),),
        )
    )
    evidence = evidence_of(stored_rows(databases)[0])
    assert "truncated" not in evidence
    assert len(evidence["row_ids"]) == 20


def test_element_content_is_not_copied_into_the_record(
    recorder: Recorder, databases: Databases
) -> None:
    """Provenance, not prose: the record must not grow with the answer's text."""
    recorder.record(
        a_record(elements=(Element("2.5% in Q2 2025", ElementClass.MEASURED, "datapoint:d1"),))
    )
    evidence = evidence_of(stored_rows(databases)[0])
    assert evidence["elements"] == [{"class": "measured", "source_ref": "datapoint:d1"}]
    assert "2.5% in Q2 2025" not in json.dumps(evidence)


@pytest.mark.parametrize("field", ["record_id", "conversation_id", "data_as_of"])
def test_an_unbounded_identifier_is_refused_rather_than_stored(field: str) -> None:
    """The one part of a record that cannot be truncated is the one that cannot be long."""
    extra: dict[str, Any] = {field: "x" * (MAX_ID_CHARS + 1)}
    if field == "conversation_id":
        extra["turn"] = 1
    with pytest.raises(RecordError) as excinfo:
        a_record(**extra)
    assert field in str(excinfo.value)


# ------------------------------------------------------------------- the rest of the shape


def test_a_record_needs_the_question_it_answered() -> None:
    with pytest.raises(RecordError):
        a_record(question="   ")


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 9, 15, 10, 0),  # noqa: DTZ001 -- naive is the thing being refused
        datetime(2026, 9, 15, 10, 0, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_the_timestamp_must_be_utc_and_carry_its_zone(moment: datetime) -> None:
    with pytest.raises(RecordError):
        AnswerRecord(
            record_id="r-1",
            recorded_at=moment,
            identity=Anonymous(),
            language=Lang.EN,
            question="q",
            spec=a_spec(),
            bindings=all_bound(),
        )


def test_a_turn_is_recorded_with_its_conversation_or_not_at_all() -> None:
    with pytest.raises(RecordError):
        a_record(turn=2)
    with pytest.raises(RecordError):
        a_record(conversation_id="c-1")
    with pytest.raises(RecordError):
        a_record(conversation_id="c-1", turn=0)


def test_a_conversation_turn_is_recorded_on_the_answer(
    recorder: Recorder, databases: Databases
) -> None:
    recorder.record(a_record(conversation_id="c-1", turn=3))
    row = stored_rows(databases)[0]
    assert (row["conversation_id"], row["turn"]) == ("c-1", 3)


def test_the_answer_path_writes_no_conversation_turn_row(
    recorder: Recorder, databases: Databases
) -> None:
    """``conversation_turn`` belongs to the conversation story, not to the recorder."""
    recorder.record(a_record(conversation_id="c-1", turn=1))
    count = databases.record_store.execute("SELECT count(*) FROM conversation_turn").fetchone()
    assert count[0] == 0


def test_a_fired_rule_must_name_its_rule() -> None:
    with pytest.raises(RecordError):
        RuleFired("  ")


@pytest.mark.parametrize(
    "prompt", [("", "3", "h"), ("narrate", "", "h"), ("narrate", "3", "")]
)
def test_a_recorded_prompt_carries_id_version_and_hash(prompt: tuple[str, str, str]) -> None:
    """AD-29: a card questioned months later traces to exactly what the model was told."""
    with pytest.raises(RecordError):
        PromptUse(*prompt)


def test_an_epic_1_answer_records_no_prompt_at_all(
    recorder: Recorder, databases: Databases
) -> None:
    """"Where one applies" -- nothing in this epic calls a model, and the record says so."""
    recorder.record(a_record())
    assert evidence_of(stored_rows(databases)[0])["prompts"] == []


# --------------------------------------------------------- separate files, no shared state


def test_records_live_in_their_own_file_away_from_the_semantic_index(tmp_path: Path) -> None:
    """AD-20: an index rebuild can never block a live write, because it is another file."""
    from askai.config.database import DatabasePaths

    paths = DatabasePaths.beneath(tmp_path / "data")
    with provision(paths) as databases:
        Recorder(SqliteRecordStore(databases.record_store)).record(a_record())

    assert paths.record_store != paths.semantic_index
    assert paths.record_store != paths.read_model

    written = sqlite3.connect(str(paths.record_store))
    try:
        assert written.execute("SELECT count(*) FROM record").fetchone()[0] == 1
    finally:
        written.close()

    index = sqlite3.connect(str(paths.semantic_index))
    try:
        tables = {
            str(row[0])
            for row in index.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        index.close()
    assert "record" not in tables


def test_two_recorders_on_two_estates_share_nothing(
    recorder: Recorder, databases: Databases
) -> None:
    """NFR-6: no directory, no service and no module state between two tests."""
    recorder.record(a_record())
    with provision() as other:
        other_store = SqliteRecordStore(other.record_store)
        Recorder(other_store).record(a_record())
        assert len(stored_rows(other)) == 1
    assert len(stored_rows(databases)) == 1


def test_the_record_path_reads_no_environment_variable() -> None:
    for name in ("identity.py", "record.py", "recorder.py"):
        source = (PACKAGE_ROOT / "observability" / name).read_text(encoding="utf-8")
        assert "os.environ" not in source and "os.getenv" not in source
    assert "os.environ" not in (PACKAGE_ROOT / "adapters" / "store" / "records.py").read_text(
        encoding="utf-8"
    )


# ------------------------------------------------------------------ the ownership scanner

_DML: Final = re.compile(
    r"(?:insert\s+or\s+\w+\s+into|insert\s+into|replace\s+into|delete\s+from|(?<!do )\bupdate)"
    r"\s+[\"'`\[]?(?P<table>\w+)",
    re.IGNORECASE,
)


def _sql_literals(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
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
    parts = list(path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _writers_under_src() -> dict[str, set[str]]:
    writers: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for table in _tables_written_in(path.read_text(encoding="utf-8")):
            writers.setdefault(table, set()).add(_module_name(path))
    return writers
