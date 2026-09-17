"""Stories 1.9 and 1.10: refresh is explicit, out of band, atomic, and says what it refused.

Two stories, one report object, one test file. Everything runs in memory or in a
temporary directory -- no service, no network, no environment variable, nothing left
behind. The counts asserted against the shipped export are measurements of that export,
so a disagreement here is evidence about the data rather than an expectation to relax.

The concurrency test is the load-bearing one. FR-109's claim is that a question in flight
sees the old content or the new and never a mixture, and an atomicity claim with no
concurrent reader is a comment. So a reader thread takes its own connection to the same
file and reads the whole read model, repeatedly, across a real refresh -- and every
reading it takes has to be one of exactly two versions.
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.export import CMS_SUBDIRECTORY, CmsExport
from askai.adapters.readmodel.schema import READ_MODEL
from askai.adapters.store.database import connect_database
from askai.adapters.store.provision import TABLE_OWNERS, Databases, provision
from askai.config.database import DatabasePaths
from askai.ports.freshness import Freshness, FreshnessPort
from askai.refresh import cli
from askai.refresh.freshness import (
    NEVER_REFRESHED,
    STALE_AFTER_RULE,
    StateFileFreshness,
    freshness_of,
    stale_after,
)
from askai.refresh.rejections import (
    EXAMPLES_RULE,
    RefreshSourceError,
    Rejection,
    RejectionClass,
    RejectionExample,
    counts_by_class,
    example_budget,
    survey_rejections,
)
from askai.refresh.report import (
    RefreshOutcome,
    RefreshReport,
    ReportFormatError,
    ServedVersion,
    TableRows,
    read_served_version,
)
from askai.refresh.run import RefreshFailed, run_refresh
from askai.refresh.state import (
    STATE_FILENAME,
    STATE_VERSION,
    RefreshState,
    StateError,
    read_state,
    state_path_for,
)
from askai.rules.loader import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

# The shipped export's measured defects. Story 1.10 names the last three by hand; the
# first is the base layer the read model deliberately does not carry.
WITHHELD_BY_PUBLICATION: Final = 342
ORPHANED_DETAILS: Final = 61
UNRESOLVABLE_AUTHORS: Final = 32
PLACEHOLDER_AUTHOR_ROWS: Final = 10
EMPTY_DEFINITION_CELLS: Final = 237
EMPTY_ANALYSES: Final = 14
DUPLICATED_COUNTRY_CODES: Final = 5

#: What the shipped export puts in each read-model table. The version a reader sees.
REAL_ROWS: Final = {
    "catalogue": 189,
    "detail": 289,
    "datapoint": 8_127,
    "ref_country": 235,
    "ref_lookup": 145,
    "analysis": 1_031,
}

#: The duplicate the story names. Both spellings are published under one ISO code.
KOREA_CODE: Final = "KR"

_FIXED_NOW: Final = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def export() -> CmsExport:
    return CmsExport.rooted(EXPORT_ROOT)


@pytest.fixture
def in_memory() -> Iterator[Databases]:
    with provision() as created:
        yield created


@pytest.fixture
def paths(tmp_path: Path) -> DatabasePaths:
    return DatabasePaths.beneath(tmp_path / "data")


@pytest.fixture
def report(export: CmsExport, in_memory: Databases) -> RefreshReport:
    return run_refresh(in_memory.read_model, export, clock=_ticking())


def _ticking(start: datetime = _FIXED_NOW) -> Callable[[], datetime]:
    """A clock that advances one second per reading, so a test never depends on a race."""
    moments = iter(start + timedelta(seconds=step) for step in range(1_000))

    def tick() -> datetime:
        return next(moments)

    return tick


# ------------------------------------------------------- Story 1.9: what a refresh says


def test_a_refresh_reports_what_changed_and_what_is_now_served(report: RefreshReport) -> None:
    assert report.outcome is RefreshOutcome.SUCCEEDED
    assert report.failure is None
    assert report.served.rows == REAL_ROWS
    assert {change.table: change.after for change in report.changed} == REAL_ROWS
    assert all(change.before == 0 for change in report.changed)


def test_the_served_version_is_read_back_from_the_tables(
    report: RefreshReport, in_memory: Databases
) -> None:
    """Counted from the file afterwards, not tallied by the writer."""
    assert read_served_version(in_memory.read_model) == report.served
    assert report.served.total_rows == sum(REAL_ROWS.values())
    assert not report.served.is_empty


def test_a_second_refresh_of_the_same_export_reports_no_change(
    export: CmsExport, in_memory: Databases
) -> None:
    run_refresh(in_memory.read_model, export, clock=_ticking())
    again = run_refresh(in_memory.read_model, export, clock=_ticking())
    assert again.succeeded
    assert again.changed == ()
    assert again.served.rows == REAL_ROWS


def test_the_summary_line_names_the_outcome_first(report: RefreshReport) -> None:
    assert report.summary().startswith("refresh succeeded")
    assert "refused" in report.summary()


def test_a_report_cannot_claim_success_and_a_failure_at_once(report: RefreshReport) -> None:
    with pytest.raises(ValueError, match="stated reason"):
        RefreshReport(
            started_at=report.started_at,
            finished_at=report.finished_at,
            outcome=RefreshOutcome.SUCCEEDED,
            failure="something went wrong",
            changed=(),
            served=report.served,
            rejections=(),
        )


def test_a_failed_report_may_not_claim_a_change(report: RefreshReport) -> None:
    with pytest.raises(ValueError, match="one transaction"):
        RefreshReport(
            started_at=report.started_at,
            finished_at=report.finished_at,
            outcome=RefreshOutcome.FAILED,
            failure="it did not land",
            changed=report.changed,
            served=report.served,
            rejections=(),
        )


# --------------------------------------------------------- Story 1.9: failure is stated


def test_a_failed_refresh_reports_the_failure_and_leaves_the_previous_contents(
    export: CmsExport, in_memory: Databases, tmp_path: Path
) -> None:
    """The ingest is one transaction, so a refusal leaves the read model exactly as it was."""
    good = run_refresh(in_memory.read_model, export, clock=_ticking())
    broken = _synthetic_export(tmp_path, period="not-a-period")

    failed = run_refresh(in_memory.read_model, CmsExport.rooted(broken), clock=_ticking())

    assert failed.outcome is RefreshOutcome.FAILED
    assert failed.failure is not None
    assert "not-a-period" in failed.failure
    assert failed.changed == ()
    assert failed.served == good.served
    assert read_served_version(in_memory.read_model).rows == REAL_ROWS


def test_an_unreadable_export_is_not_attempted_at_all(in_memory: Databases, tmp_path: Path) -> None:
    """Nothing to report on is different from a refresh that reported a refusal."""
    (tmp_path / CMS_SUBDIRECTORY).mkdir()
    with pytest.raises(RefreshFailed) as excinfo:
        run_refresh(in_memory.read_model, CmsExport.rooted(tmp_path), clock=_ticking())
    assert "no refresh was attempted" in str(excinfo.value)


# ------------------------------------------------------------- Story 1.9: the atomicity


def test_a_reader_across_a_refresh_never_sees_a_mixture(paths: DatabasePaths) -> None:
    """FR-109, driven rather than asserted.

    A second connection to the same file reads every read-model table, inside its own
    read transaction, in a tight loop while a real refresh replaces all five of them.
    Every reading it takes must be one whole version or the other -- in particular it
    must never see the emptied tables the refresh passes through, which is what a
    non-transactional swap would show.
    """
    with provision(paths) as databases:
        seeded = _synthetic_export(paths.read_model.parent.parent / "v1")
        first = run_refresh(databases.read_model, CmsExport.rooted(seeded), clock=_ticking())
        assert first.succeeded

        observed: set[tuple[tuple[str, int], ...]] = set()
        readings = 0
        stop = threading.Event()
        failures: list[str] = []

        def read_continuously() -> None:
            nonlocal readings
            reader = connect_database(READ_MODEL, paths.read_model)
            try:
                while not stop.is_set():
                    observed.add(_version_of(read_served_version(reader)))
                    readings += 1
            except sqlite3.Error as error:
                failures.append(str(error))
            finally:
                reader.close()

        thread = threading.Thread(target=read_continuously)
        thread.start()
        try:
            second = run_refresh(
                databases.read_model, CmsExport.rooted(EXPORT_ROOT), clock=_ticking()
            )
            # Let the reader keep going until it has certainly crossed the commit.
            deadline = time.monotonic() + 30
            while _version_of(second.served) not in observed and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            stop.set()
            thread.join(timeout=30)

    assert not failures, failures
    assert second.succeeded
    permitted = {_version_of(first.served), _version_of(second.served)}
    assert observed <= permitted, (
        "a reader saw a version of the read model that never existed: "
        f"{sorted(observed - permitted)}"
    )
    assert observed == permitted, "the reader never crossed the refresh; the test proved nothing"
    assert readings > 1


def _version_of(served: ServedVersion) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(served.rows.items()))


def test_a_mixture_would_not_be_in_the_permitted_set() -> None:
    """The concurrency assertion is only worth its green while a half-load is detectable.

    An emptied read model -- what the ingest passes through between its DELETEs and its
    INSERTs, and what a non-transactional swap would expose -- is neither version.
    """
    whole = ServedVersion(tables=tuple(_rows(REAL_ROWS)))
    emptied = ServedVersion(tables=tuple(_rows(dict.fromkeys(REAL_ROWS, 0))))
    half = ServedVersion(tables=tuple(_rows({**REAL_ROWS, "datapoint": 1})))
    permitted = {_version_of(whole)}
    assert _version_of(emptied) not in permitted
    assert _version_of(half) not in permitted


def _rows(counts: Mapping[str, int]) -> list[TableRows]:
    return [TableRows(table=table, rows=rows) for table, rows in counts.items()]


def test_a_reader_on_another_connection_sees_the_old_rows_until_the_commit(
    paths: DatabasePaths,
) -> None:
    """The mechanism, stated on its own: uncommitted pages are not visible anywhere else."""
    with provision(paths) as databases:
        seeded = _synthetic_export(paths.read_model.parent.parent / "v1")
        run_refresh(databases.read_model, CmsExport.rooted(seeded), clock=_ticking())
        reader = connect_database(READ_MODEL, paths.read_model)
        try:
            before = read_served_version(reader)
            # A write transaction left open: the reader must be untouched by it.
            databases.read_model.execute("BEGIN")
            # Children first, which is the ingest's own clear order: `analysis`
            # references `datapoint`, so emptying the parent on its own is refused by a
            # foreign key rather than by anything this test is about.
            databases.read_model.execute("DELETE FROM analysis")
            databases.read_model.execute("DELETE FROM datapoint")
            assert read_served_version(reader) == before
            databases.read_model.rollback()
            assert read_served_version(reader) == before
        finally:
            reader.close()


# ------------------------------------------------- Story 1.9: the recorded state on disk


def test_the_state_file_records_when_the_refresh_last_ran(
    export: CmsExport, paths: DatabasePaths
) -> None:
    state_path = state_path_for(paths)
    with provision(paths) as databases:
        finished = run_refresh(databases.read_model, export, state_path, clock=_ticking())
    state = read_state(state_path)
    assert state is not None
    assert state.refreshed_at == finished.finished_at
    assert state.last_attempt_at == finished.finished_at
    assert state.last_attempt_succeeded
    assert state.last_report.served.rows == REAL_ROWS


def test_the_state_file_sits_beside_the_databases_it_describes(paths: DatabasePaths) -> None:
    assert state_path_for(paths).name == STATE_FILENAME
    assert state_path_for(paths).parent == paths.read_model.parent


def test_a_failed_refresh_records_itself_without_moving_the_mark(
    export: CmsExport, paths: DatabasePaths, tmp_path: Path
) -> None:
    """The engine is still serving the last good copy, so that is the moment reported."""
    state_path = state_path_for(paths)
    broken = _synthetic_export(tmp_path / "broken", period="not-a-period")
    with provision(paths) as databases:
        good = run_refresh(databases.read_model, export, state_path, clock=_ticking())
        failed = run_refresh(
            databases.read_model, CmsExport.rooted(broken), state_path, clock=_ticking()
        )

    state = read_state(state_path)
    assert state is not None
    assert not failed.succeeded
    assert state.refreshed_at == good.finished_at
    assert state.last_attempt_at == failed.finished_at
    assert not state.last_attempt_succeeded
    assert state.last_report.failure is not None


def test_the_state_file_is_replaced_whole_and_leaves_no_scratch_file(
    export: CmsExport, paths: DatabasePaths
) -> None:
    state_path = state_path_for(paths)
    with provision(paths) as databases:
        run_refresh(databases.read_model, export, state_path, clock=_ticking())
        run_refresh(databases.read_model, export, state_path, clock=_ticking())
    assert [path.name for path in sorted(state_path.parent.glob("refresh_state*"))] == [
        STATE_FILENAME
    ]
    assert json.loads(state_path.read_text(encoding="utf-8"))["state_version"] == STATE_VERSION


def test_a_dry_run_records_nothing(export: CmsExport, paths: DatabasePaths) -> None:
    with provision(paths) as databases:
        run_refresh(databases.read_model, export, None, clock=_ticking())
    assert read_state(state_path_for(paths)) is None


def test_a_state_file_at_another_version_is_refused_rather_than_adopted(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text(json.dumps({"state_version": 99}), encoding="utf-8")
    with pytest.raises(StateError) as excinfo:
        read_state(path)
    assert "version 99" in str(excinfo.value)


def test_a_malformed_state_file_raises_rather_than_reading_as_never_refreshed(
    tmp_path: Path,
) -> None:
    """The distinction matters: "never refreshed" is a fact, not a parse failure."""
    path = tmp_path / STATE_FILENAME
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(StateError):
        read_state(path)
    assert read_state(tmp_path / "nothing-here.json") is None


def test_the_report_round_trips_through_the_state_file(
    export: CmsExport, paths: DatabasePaths
) -> None:
    state_path = state_path_for(paths)
    with provision(paths) as databases:
        written = run_refresh(databases.read_model, export, state_path, clock=_ticking())
    state = read_state(state_path)
    assert state is not None
    assert state.last_report == written


def test_a_report_this_build_cannot_read_is_named(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text(
        json.dumps(
            {
                "state_version": STATE_VERSION,
                "refreshed_at": None,
                "last_attempt_at": _FIXED_NOW.isoformat(),
                "last_report": {"outcome": "succeeded"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StateError) as excinfo:
        read_state(path)
    assert "cannot read" in str(excinfo.value)


def test_a_report_mapping_missing_a_field_is_refused(report: RefreshReport) -> None:
    document = dict(report.as_mapping())
    del document["served"]
    with pytest.raises(ReportFormatError) as excinfo:
        RefreshReport.from_mapping(document)
    assert "served" in str(excinfo.value)


# ----------------------------------------------------------- Story 1.9: visible staleness


def test_the_staleness_threshold_is_a_rule_and_not_a_literal() -> None:
    assert stale_after() == timedelta(hours=26)
    assert rules().value(STALE_AFTER_RULE, "stale_after_hours") == 26


def test_a_read_model_never_refreshed_is_stale() -> None:
    assert freshness_of(None, _FIXED_NOW) == NEVER_REFRESHED
    assert NEVER_REFRESHED.stale
    assert NEVER_REFRESHED.refreshed_at is None
    assert NEVER_REFRESHED.age_seconds is None


def test_freshness_carries_the_moment_the_age_and_the_flag(report: RefreshReport) -> None:
    state = RefreshState.first(report)
    fresh = freshness_of(state, report.finished_at + timedelta(hours=1))
    assert fresh.refreshed_at == report.finished_at
    assert fresh.age_seconds == pytest.approx(3600.0)
    assert not fresh.stale


@pytest.mark.parametrize(
    ("elapsed", "stale"),
    [
        (timedelta(hours=1), False),
        (timedelta(hours=26), False),
        (timedelta(hours=26, seconds=1), True),
        (timedelta(days=3), True),
    ],
)
def test_staleness_flips_at_the_threshold_and_nowhere_else(
    report: RefreshReport, elapsed: timedelta, stale: bool
) -> None:
    state = RefreshState.first(report)
    assert freshness_of(state, report.finished_at + elapsed).stale is stale


def test_a_failed_refresh_keeps_the_copy_ageing_from_the_last_good_one(
    report: RefreshReport,
) -> None:
    """Staleness measures the data, not the attempt: a failed run must not look like work."""
    good = RefreshState.first(report)
    failed = RefreshReport(
        started_at=report.finished_at + timedelta(days=2),
        finished_at=report.finished_at + timedelta(days=2),
        outcome=RefreshOutcome.FAILED,
        failure="the export was refused",
        changed=(),
        served=report.served,
        rejections=(),
    )
    after = good.after(failed)
    assert after.refreshed_at == report.finished_at
    assert freshness_of(after, report.finished_at + timedelta(days=2)).stale


def test_freshness_cannot_carry_an_age_without_a_moment() -> None:
    with pytest.raises(ValueError, match="age is measured"):
        Freshness(refreshed_at=None, stale=True, age_seconds=10.0)
    with pytest.raises(ValueError, match="never been refreshed is stale"):
        Freshness(refreshed_at=None, stale=False, age_seconds=None)


def test_the_state_file_reader_satisfies_the_freshness_port(
    export: CmsExport, paths: DatabasePaths
) -> None:
    state_path = state_path_for(paths)
    source = StateFileFreshness(state_path)
    assert isinstance(source, FreshnessPort)
    assert source.freshness(_FIXED_NOW) == NEVER_REFRESHED

    with provision(paths) as databases:
        written = run_refresh(databases.read_model, export, state_path, clock=_ticking())
    assert source.freshness(written.finished_at).refreshed_at == written.finished_at


def test_republished_content_reaches_a_reader_with_no_code_change(paths: DatabasePaths) -> None:
    """NFR-7, in the only form it can be tested: the same process, the same code, new data.

    Nothing is imported again, no connection is reopened and no setting changes -- the
    export on disk is republished and the next scheduled refresh carries it through to a
    reader that is already holding its connection.
    """
    state_path = state_path_for(paths)
    root = paths.read_model.parent.parent / "export"
    _synthetic_export(root, indicator_name="As first published")
    with provision(paths) as databases:
        reader = connect_database(READ_MODEL, paths.read_model)
        try:
            first = run_refresh(
                databases.read_model, CmsExport.rooted(root), state_path, clock=_ticking()
            )
            assert _names(reader) == ["As first published"]

            _synthetic_export(root, indicator_name="As republished")
            second = run_refresh(
                databases.read_model, CmsExport.rooted(root), state_path, clock=_ticking()
            )
            assert _names(reader) == ["As republished"]
        finally:
            reader.close()

    assert first.succeeded and second.succeeded
    fresh = StateFileFreshness(state_path).freshness(second.finished_at)
    assert fresh.refreshed_at == second.finished_at
    assert not fresh.stale


def _names(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute("SELECT name_en FROM catalogue")]


# --------------------------------------------------- Story 1.9: out of band, not a route


def _in_project_imports(path: Path) -> set[str]:
    module = _module_name(path)
    # Relative levels are resolved against the *containing package*, not the module.
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    return _imports_in(path.read_text(encoding="utf-8"), package)


def _imports_in(source: str, package: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.update(_resolved(node, package))
    return {name for name in found if name.split(".")[0] == "askai"}


def _resolved(node: ast.ImportFrom, package: str) -> list[str]:
    if not node.level:
        return [node.module] if node.module else []
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    if node.module:
        return [f"{base}.{node.module}"]
    return [f"{base}.{alias.name}" for alias in node.names]


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _reachable_from(root: Path) -> set[str]:
    """Every in-project module reachable by following imports out of *root*."""
    frontier = sorted(root.rglob("*.py"))
    seen: set[str] = set()
    reached: set[str] = set()
    while frontier:
        path = frontier.pop()
        name = _module_name(path)
        if name in seen:
            continue
        seen.add(name)
        for imported in _in_project_imports(path):
            reached.add(imported)
            candidates = [
                PACKAGE_ROOT.parent.joinpath(*imported.split(".")).with_suffix(".py"),
                PACKAGE_ROOT.parent.joinpath(*imported.split(".")) / "__init__.py",
            ]
            frontier.extend(candidate for candidate in candidates if candidate.is_file())
    return reached


def test_no_route_reaches_the_refresh_mechanism() -> None:
    """AD-21: refresh is a job or a command, never something a request can trigger."""
    reached = _reachable_from(PACKAGE_ROOT / "api")
    offenders = sorted(name for name in reached if name.split(".")[:2] == ["askai", "refresh"])
    assert offenders == [], f"api/ reaches the refresh mechanism through {offenders}"


@pytest.mark.parametrize(
    "source",
    [
        "from askai.refresh.run import run_refresh\n",
        "import askai.refresh.run\n",
        "from ..refresh.run import run_refresh\n",
        "from askai.refresh import run\n",
    ],
)
def test_the_reachability_scan_would_catch_a_route_that_did(source: str) -> None:
    """Otherwise the empty ``api/`` of Epic 1 proves nothing, in any import spelling."""
    found = _imports_in(source, "askai.api")
    assert any(name.split(".")[:2] == ["askai", "refresh"] for name in found), found


def test_refresh_is_invokable_as_a_standalone_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "askai.refresh", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "export" in result.stdout


def test_the_command_refreshes_and_reports_zero(
    paths: DatabasePaths, capsys: pytest.CaptureFixture[str]
) -> None:
    provision(paths).close()
    code = cli.main([str(EXPORT_ROOT), "--database-dir", str(paths.read_model.parent)])
    captured = capsys.readouterr().out
    assert code == 0, captured
    assert "refresh succeeded" in captured
    assert "refused" in captured
    assert read_state(state_path_for(paths)) is not None


def test_the_command_reports_one_when_the_refresh_failed(
    paths: DatabasePaths, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provision(paths).close()
    broken = _synthetic_export(tmp_path / "broken", period="not-a-period")
    code = cli.main([str(broken), "--database-dir", str(paths.read_model.parent)])
    assert code == 1
    assert "refresh failed" in capsys.readouterr().out


def test_a_dry_run_from_the_command_leaves_no_state(
    paths: DatabasePaths, capsys: pytest.CaptureFixture[str]
) -> None:
    provision(paths).close()
    code = cli.main(
        [str(EXPORT_ROOT), "--database-dir", str(paths.read_model.parent), "--dry-run"]
    )
    assert code == 0, capsys.readouterr().out
    assert read_state(state_path_for(paths)) is None


# ------------------------------------------ Story 1.10: counts and examples, never a drop


def test_every_rejection_carries_a_class_a_reason_a_count_and_a_source(
    report: RefreshReport,
) -> None:
    assert report.rejections
    for rejection in report.rejections:
        assert isinstance(rejection.rejection_class, RejectionClass)
        assert len(rejection.reason) > 20, rejection.reason
        assert rejection.source
        assert rejection.count >= len(rejection.examples)


def test_the_three_classes_the_story_names_are_all_reported(report: RefreshReport) -> None:
    required = {
        RejectionClass.PUBLICATION_STATE,
        RejectionClass.UNRESOLVABLE_REFERENCE,
        RejectionClass.MALFORMED_CONTENT,
    }
    assert required <= {rejection.rejection_class for rejection in report.rejections}


def test_no_class_vanishes_when_it_matched_nothing(report: RefreshReport) -> None:
    """A clean export and an unsurveyed one must not produce the same report."""
    assert set(counts_by_class(report.rejections)) == set(RejectionClass)
    empty = [rejection for rejection in report.rejections if rejection.count == 0]
    assert empty, "every class matched something; the empty-class shape is untested"
    assert all(rejection.examples == () for rejection in empty)


def test_the_known_defects_of_this_export_are_surfaced_with_counts(
    report: RefreshReport,
) -> None:
    """The three defects Story 1.10 names by hand, plus the layer they sit behind."""
    by_source = {rejection.source: rejection for rejection in report.rejections}
    assert by_source["Item_4_IndicatorDetails"].count == ORPHANED_DETAILS
    assert by_source["Item_2_Indicators_Catalog"].count == WITHHELD_BY_PUBLICATION

    authors = _only(report, RejectionClass.UNRESOLVABLE_REFERENCE, "Articles.csv")
    assert authors.count == UNRESOLVABLE_AUTHORS

    countries = _only(report, RejectionClass.AMBIGUOUS_IDENTITY, "P14_Ref_Countries")
    assert countries.count == DUPLICATED_COUNTRY_CODES
    korea = next(example for example in countries.examples if example.identifier == KOREA_CODE)
    assert "Korea" in korea.detail and "South Korea" in korea.detail


def test_the_malformed_content_class_counts_every_shape_of_it(report: RefreshReport) -> None:
    malformed = {
        rejection.source: rejection.count
        for rejection in report.rejections_in(RejectionClass.MALFORMED_CONTENT)
    }
    assert malformed["P02_Published_IndicatorDetails"] == EMPTY_DEFINITION_CELLS
    assert malformed["P04_Published_DataPointAnalysis"] == EMPTY_ANALYSES
    assert malformed["Articles.csv"] == PLACEHOLDER_AUTHOR_ROWS


def test_a_placeholder_is_malformed_content_and_not_an_unresolvable_reference(
    report: RefreshReport,
) -> None:
    """Both are author columns; only one names something that could have existed."""
    placeholder = _only(report, RejectionClass.MALFORMED_CONTENT, "Articles.csv")
    assert all("not an identifier" in example.detail for example in placeholder.examples)
    unresolved = _only(report, RejectionClass.UNRESOLVABLE_REFERENCE, "Articles.csv")
    assert all("no register entry" in example.detail for example in unresolved.examples)


def test_every_rejection_with_rows_carries_worked_examples(report: RefreshReport) -> None:
    for rejection in report.rejections:
        if rejection.count:
            assert rejection.examples, rejection.reason
            for example in rejection.examples:
                assert example.identifier
                assert example.detail


def test_the_example_budget_is_a_rule_and_caps_examples_but_never_the_count(
    export: CmsExport,
) -> None:
    assert example_budget() == rules().value(EXAMPLES_RULE, "examples_per_rejection")
    surveyed = survey_rejections(export, 2)
    orphans = next(item for item in surveyed if item.source == "Item_4_IndicatorDetails")
    assert orphans.count == ORPHANED_DETAILS
    assert len(orphans.examples) == 2
    assert orphans.examples_are_truncated


def test_the_budget_shows_every_duplicated_country_code(export: CmsExport) -> None:
    """Five codes and a budget of five: the defect is shown whole, not sampled."""
    countries = next(
        item for item in survey_rejections(export) if item.source == "P14_Ref_Countries"
    )
    assert len(countries.examples) == DUPLICATED_COUNTRY_CODES
    assert not countries.examples_are_truncated


def test_a_rejection_may_not_carry_more_examples_than_it_counted() -> None:
    with pytest.raises(ValueError, match="never the other way round"):
        Rejection(
            rejection_class=RejectionClass.MALFORMED_CONTENT,
            reason="a reason long enough to be a reason",
            count=0,
            examples=(RejectionExample(identifier="x", detail="y"),),
            source="somewhere",
        )


def test_the_total_refused_is_the_sum_of_the_counts(report: RefreshReport) -> None:
    assert report.rejected_rows == sum(counts_by_class(report.rejections).values())
    assert report.rejected_rows >= ORPHANED_DETAILS + UNRESOLVABLE_AUTHORS


def test_rejections_survive_the_state_file(export: CmsExport, paths: DatabasePaths) -> None:
    """FR-110: a rejection is written down *and* retrievable, not only logged."""
    state_path = state_path_for(paths)
    with provision(paths) as databases:
        written = run_refresh(databases.read_model, export, state_path, clock=_ticking())
    recovered = read_state(state_path)
    assert recovered is not None
    assert recovered.last_report.rejections == written.rejections


def test_a_missing_census_source_stops_the_refresh_rather_than_reporting_a_clean_export(
    in_memory: Databases, tmp_path: Path
) -> None:
    root = _synthetic_export(tmp_path)
    (root / "Champions.csv").unlink()
    with pytest.raises(RefreshFailed) as excinfo:
        run_refresh(in_memory.read_model, CmsExport.rooted(root), clock=_ticking())
    assert "Champions.csv" in str(excinfo.value)


def test_the_census_names_the_file_it_could_not_read(tmp_path: Path) -> None:
    root = _synthetic_export(tmp_path)
    (root / CMS_SUBDIRECTORY / "Item_4_IndicatorDetails-20260811.csv").unlink()
    with pytest.raises(RefreshSourceError) as excinfo:
        survey_rejections(CmsExport.rooted(root))
    assert "Item_4_IndicatorDetails" in str(excinfo.value)


def test_an_unreadable_period_is_counted_as_well_as_refused(
    in_memory: Databases, tmp_path: Path
) -> None:
    """The row is refused by the ingest and named by the census; neither is silent."""
    root = _synthetic_export(tmp_path, period="not-a-period")
    surveyed = survey_rejections(CmsExport.rooted(root))
    periods = next(
        item
        for item in surveyed
        if item.source == "P03_Published_DataPoints" and item.count
    )
    assert periods.rejection_class is RejectionClass.MALFORMED_CONTENT
    assert "not-a-period" in periods.examples[0].detail

    failed = run_refresh(in_memory.read_model, CmsExport.rooted(root), clock=_ticking())
    assert not failed.succeeded


def test_a_confidential_indicator_is_counted_by_the_census_and_by_the_ingest(
    in_memory: Databases, tmp_path: Path
) -> None:
    """The one number both sides compute. A disagreement fails the refresh (see ``run``)."""
    root = _synthetic_export(tmp_path, priority_id="3")
    done = run_refresh(in_memory.read_model, CmsExport.rooted(root), clock=_ticking())
    assert done.succeeded, done.failure
    confidential = next(
        item
        for item in done.rejections
        if item.source == "P01_Published_Indicators"
        and item.rejection_class is RejectionClass.PUBLICATION_STATE
    )
    assert confidential.count == 1
    assert done.served.rows["catalogue"] == 0


# -------------------------------------------------------------------- the house rules


def test_no_broad_exception_handler_lives_outside_an_adapter() -> None:
    """AD-15, over the source. The lint gate below is the build's copy of the same rule."""
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.is_relative_to(PACKAGE_ROOT / "adapters"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = node.type
            if caught is None or (
                isinstance(caught, ast.Name) and caught.id in {"Exception", "BaseException"}
            ):
                offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}")
    assert offenders == [], "a broad handler makes a rule that stopped firing invisible: " + str(
        offenders
    )


def test_the_broad_handler_rule_is_a_lint_gate_and_not_only_a_test() -> None:
    """AD-15 asks for a lint rule that fails the build, scoped to adapter boundaries."""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]
    assert "BLE" in lint["extend-select"]
    assert "E722" in lint["extend-select"]
    assert lint["per-file-ignores"]["src/askai/adapters/**/*.py"] == ["BLE001"]


def test_refresh_writes_no_table_at_all() -> None:
    """AD-20: the read model's tables have one owner, and it is the ingest, not this job."""
    written = {
        table
        for path in sorted((PACKAGE_ROOT / "refresh").rglob("*.py"))
        for table in _tables_written_in(path.read_text(encoding="utf-8"))
    }
    assert written == set(), f"refresh/ writes {sorted(written)}; it owns no table"
    assert TABLE_OWNERS["datapoint"] == "askai.adapters.readmodel"


_DML: Final = re.compile(
    r"(?:insert\s+or\s+\w+\s+into|insert\s+into|replace\s+into|delete\s+from|(?<!do )\bupdate)"
    r"\s+[\"'`\[]?(?P<table>\w+)",
    re.IGNORECASE,
)


def _tables_written_in(source: str) -> set[str]:
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
    return {
        match.group("table").lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        for match in _DML.finditer(node.value)
    }


def test_the_refresh_package_declares_its_purity() -> None:
    source = (PACKAGE_ROOT / "refresh" / "__init__.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(source))
    assert doc is not None
    assert "never on the answer path" in doc


# ------------------------------------------------------------------- the synthetic export


def _only(report: RefreshReport, rejection_class: RejectionClass, source: str) -> Rejection:
    matches = [
        rejection
        for rejection in report.rejections_in(rejection_class)
        if rejection.source == source
    ]
    assert len(matches) == 1, f"{rejection_class} x {source} matched {len(matches)}"
    return matches[0]


def _write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    columns = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _synthetic_export(
    root: Path,
    period: str = "2025",
    priority_id: str = "2",
    indicator_name: str = "A published indicator",
) -> Path:
    """A one-indicator export in the real export's shape, plus the census's own sources.

    Written fresh each call, so republishing is a second call with different content --
    which is exactly what NFR-7's "no code change and no deployment" means on disk.
    """
    cms = root / CMS_SUBDIRECTORY
    cms.mkdir(parents=True, exist_ok=True)
    tables: Mapping[str, Sequence[Mapping[str, str]]] = {
        "P01_Published_Indicators": [
            {
                "PublishedIndicatorId": "ind-1",
                "SourceIndicatorId": "base-1",
                "NameEN": indicator_name,
                "NameAR": "مؤشر منشور",
                "IndicatorPriorityTypeId": priority_id,
                "IndicatorEntityTypeId": "ENT-1",
                "EntityClassificationName": "Sectors",
                "PublishingStatusName": "Amended",
            }
        ],
        "P02_Published_IndicatorDetails": [
            {
                "PublishedIndicatorDetailId": "det-1",
                "PublishedIndicatorId": "ind-1",
                "SourceIndicatorDetailId": "base-det-1",
                "IsMain": "True",
                "NameEN": "A detail",
                "NameAR": "تفصيل",
                "DefinationEN": "<p>What it measures</p>",
                "DefinationAR": "<p>ما يقيسه</p>",
                "Format": "0.0",
                "UnitId": "look-1",
                "PolarityId": "look-1",
                "ValueTypeId": "look-1",
                "DataSourceId": "look-1",
                "AggregationTypeId": "look-1",
            }
        ],
        "P03_Published_DataPoints": [
            {
                "PublishedDataPointId": "dp-1",
                "PublishedIndicatorDetailId": "det-1",
                "Period": period,
                "CountryId": "",
                "CountryEN": "",
                "Actual": "1",
                "YearlyYoYPercent": "3.5",
            }
        ],
        "P04_Published_DataPointAnalysis": [
            {
                "PublishedDataPointAnalysisId": "an-1",
                "PublishedDataPointId": "dp-1",
                "SummaryEN": "<p>It went up</p>",
                "SummaryAR": "<p>ارتفع</p>",
            }
        ],
        "P12_Ref_Lookups_Common": [
            {"LookupType": "Units", "Id": "look-1", "NameEN": "Per cent", "NameAR": "نسبة"}
        ],
        "P13_Ref_IndicatorPriorityTypes": [
            {"Id": "1", "NameEN": "Non-Priority", "NameAR": "غير ذات أولوية"},
            {"Id": "2", "NameEN": "Priority", "NameAR": "ذات أولوية"},
            {"Id": "3", "NameEN": "Confidential", "NameAR": "سري"},
        ],
        "P14_Ref_Countries": [
            {"Id": "c-1", "NameEN": "Somewhere", "NameAR": "مكان", "Code": "SW"},
        ],
        "Item_2_Indicators_Catalog": [
            {"Id": "base-1", "NameEN": indicator_name, "NameAR": "مؤشر منشور"},
            {"Id": "base-2", "NameEN": "An indicator nobody approved", "NameAR": "مؤشر غير معتمد"},
        ],
        "Item_4_IndicatorDetails": [
            {"IndicatorDetailId": "base-det-1", "IndicatorId": "base-1", "NameEN": "A detail"},
        ],
    }
    for prefix, rows in tables.items():
        _write_csv(cms / f"{prefix}-20260811.csv", rows)

    loose: Mapping[str, Sequence[Mapping[str, str]]] = {
        "Sectors.csv": [{"Id": "ent-1", "NameEN": "A sector", "NameAR": "قطاع"}],
        "General Entities.csv": [{"Id": "ent-2", "NameEN": "An entity", "NameAR": "جهة"}],
        "Articles.csv": [
            {
                "Id": "art-1",
                "TitleEN": "A piece",
                "AuthorId": "11111111-1111-1111-1111-111111111111",
            }
        ],
        "Champions.csv": [
            {"Id": "11111111-1111-1111-1111-111111111111", "NameEN": "An author", "NameAR": "كاتب"}
        ],
    }
    for filename, rows in loose.items():
        _write_csv(root / filename, rows)
    return root


def test_the_synthetic_export_is_the_same_shape_as_the_real_one(
    tmp_path: Path, export: CmsExport
) -> None:
    """Otherwise every failure test above proves something about a fixture."""
    synthetic = CmsExport.rooted(_synthetic_export(tmp_path))
    for reader in ("published_indicators", "published_details", "published_datapoints"):
        assert set(getattr(synthetic, reader)()[0]) <= set(getattr(export, reader)()[0]), reader


def test_the_synthetic_export_surveys_clean(tmp_path: Path) -> None:
    """A clean export reports every class with a count of zero -- not an absent class."""
    surveyed = survey_rejections(CmsExport.rooted(_synthetic_export(tmp_path)))
    totals = counts_by_class(surveyed)
    assert set(totals) == set(RejectionClass)
    assert totals[RejectionClass.UNRESOLVABLE_REFERENCE] == 0
    assert totals[RejectionClass.MALFORMED_CONTENT] == 0
    assert totals[RejectionClass.AMBIGUOUS_IDENTITY] == 0
    # The one thing the synthetic export deliberately withholds from publication.
    assert totals[RejectionClass.PUBLICATION_STATE] == 1
