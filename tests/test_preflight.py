"""Story 1.7 -- the preflight check, and the faults it exists to catch.

The story is titled *"on the target VM"*, and the last mile genuinely needs that machine:
nothing here can prove the VM's disk keeps a write. But the check itself is not
VM-specific, and neither is most of its behaviour -- so it is written and driven here,
against real files on a real filesystem, and running it there becomes one command.

**Every mutating test uses ``tmp_path``.** The checks are about a directory, so a test
that faked the filesystem would assert the fake. Where a fault cannot be produced on this
machine -- a full disk, a filesystem that refuses a rename under an open handle -- the
test drives the *reporting* of that fault instead and says so, rather than skipping and
leaving the branch unproven.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from askai.adapters.store.cli import main
from askai.adapters.store.preflight import (
    MINIMUM_FREE_BYTES,
    Check,
    CheckOutcome,
    PreflightFailed,
    ensure_ready,
    preflight,
)
from askai.config.database import DATABASE_DIR_ENV, DatabasePaths

HUGE = 1 << 62
"""A free-space floor no machine satisfies, so the failing branch is driven rather than
described. Not a mocked ``disk_usage``: the point is that the real reading is compared."""


@pytest.fixture
def paths(tmp_path: Path) -> DatabasePaths:
    return DatabasePaths.beneath(tmp_path)


# ------------------------------------------------------------------ the happy path


def test_every_check_passes_on_an_ordinary_writable_directory(paths: DatabasePaths) -> None:
    report = preflight(paths)
    assert report.ok, report.render()
    assert {outcome.check for outcome in report.outcomes} == set(Check), (
        "every declared check must run; one that is declared and never run is the "
        "declared-but-unwired defect wearing an operational hat"
    )


def test_the_checks_run_in_the_declared_order(paths: DatabasePaths) -> None:
    """Order is load-bearing: a later check on an unusable directory names the wrong fault."""
    assert [outcome.check for outcome in preflight(paths).outcomes] == list(Check)


def test_the_report_names_the_resolved_absolute_paths(paths: DatabasePaths) -> None:
    """The AC's *"a misconfigured path is visible rather than silently creating files
    somewhere else"* -- which is the fault that hides best, because everything passes."""
    rendered = preflight(paths).render()
    for path in (paths.read_model, paths.record_store, paths.semantic_index):
        assert path.is_absolute()
        assert str(path) in rendered


def test_the_checks_leave_nothing_behind(paths: DatabasePaths) -> None:
    """A check that littered the estate's directory would be one nobody runs twice."""
    directory = paths.read_model.parent
    before = set(directory.iterdir())
    assert preflight(paths).ok
    assert set(directory.iterdir()) == before


def test_the_checks_never_touch_the_estate_s_own_files(paths: DatabasePaths) -> None:
    """The whole design: probe files beside the databases, never the databases.

    This is what makes the command safe to run on a live VM, so it is asserted rather
    than left to the reader of the module docstring.
    """
    assert preflight(paths).ok
    for path in (paths.read_model, paths.record_store, paths.semantic_index):
        assert not path.exists(), f"preflight created {path.name}; it must only probe"


# ------------------------------------------------------------------ the faults


def test_a_missing_directory_fails_and_says_so(tmp_path: Path) -> None:
    report = preflight(DatabasePaths.beneath(tmp_path / "nowhere"))
    assert not report.ok
    outcome = _outcome(report.outcomes, Check.DIRECTORY_EXISTS)
    assert not outcome.passed
    assert "does not exist" in outcome.detail


def test_a_path_that_is_a_file_rather_than_a_directory_is_distinguished(tmp_path: Path) -> None:
    """Two different operator problems, so two different messages."""
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    outcome = _outcome(
        preflight(DatabasePaths.beneath(occupied)).outcomes, Check.DIRECTORY_EXISTS
    )
    assert not outcome.passed
    assert "not a directory" in outcome.detail


def test_the_checks_that_depend_on_a_missing_directory_say_they_did_not_run(
    tmp_path: Path,
) -> None:
    """A "reader is blocked" failure on a directory that does not exist points at the
    wrong fault, and an operator would chase the filesystem instead of the config."""
    report = preflight(DatabasePaths.beneath(tmp_path / "nowhere"))
    for check in (Check.WAL_SIDECARS, Check.READER_NOT_BLOCKED, Check.DURABILITY):
        outcome = _outcome(report.outcomes, check)
        assert not outcome.passed
        assert outcome.detail.startswith("not run:")
    assert len(report.outcomes) == len(Check), "a skipped check is still reported"


def test_insufficient_free_space_fails_against_the_real_reading(paths: DatabasePaths) -> None:
    report = preflight(paths, minimum_free_bytes=HUGE)
    outcome = _outcome(report.outcomes, Check.FREE_SPACE)
    assert not outcome.passed
    assert "not enough" in outcome.detail
    assert not report.ok


def test_sufficient_free_space_reports_what_it_measured(paths: DatabasePaths) -> None:
    """A passing check that says what it saw is what an operator reads before trouble."""
    outcome = _outcome(preflight(paths).outcomes, Check.FREE_SPACE)
    assert outcome.passed
    assert "free" in outcome.detail and "required" in outcome.detail


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not apply on Windows")
def test_a_read_only_directory_fails_the_writable_check(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        report = preflight(DatabasePaths.beneath(locked))
        outcome = _outcome(report.outcomes, Check.DIRECTORY_WRITABLE)
        assert not outcome.passed
        assert "cannot create a file" in outcome.detail
        for check in (Check.WAL_SIDECARS, Check.READER_NOT_BLOCKED, Check.DURABILITY):
            assert _outcome(report.outcomes, check).detail.startswith("not run:")
    finally:
        locked.chmod(0o700)


# ------------------------------------------------------- the four real-world faults


def test_the_wal_sidecars_are_actually_created_where_the_databases_go(
    paths: DatabasePaths,
) -> None:
    """The check passes only if ``-wal`` and ``-shm`` appeared, so this asserts the
    mechanism rather than the verdict -- a check that looked only at ``journal_mode``
    would pass on a filesystem that refuses the shared-memory file."""
    outcome = _outcome(preflight(paths).outcomes, Check.WAL_SIDECARS)
    assert outcome.passed
    assert "-wal" in outcome.detail and "-shm" in outcome.detail


def test_a_reader_is_not_blocked_by_an_open_writer(paths: DatabasePaths) -> None:
    outcome = _outcome(preflight(paths).outcomes, Check.READER_NOT_BLOCKED)
    assert outcome.passed, outcome.detail


def test_the_blocked_reader_check_can_actually_fail(tmp_path: Path) -> None:
    """The check is only worth having if a blocked reader would be caught.

    Driven directly rather than through ``preflight``: a rollback journal is the
    condition WAL exists to remove, so a database left in ``delete`` mode reproduces
    exactly the filesystem this check is a proxy for.
    """
    path = tmp_path / "rollback.sqlite3"
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode = delete")
    writer.execute("CREATE TABLE probe (value TEXT)")
    writer.commit()
    # EXCLUSIVE, not IMMEDIATE: in rollback mode an IMMEDIATE transaction takes only a
    # RESERVED lock, which still admits readers until the writer spills to the journal --
    # so an IMMEDIATE canary would prove nothing and pass for the wrong reason.
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("INSERT INTO probe VALUES ('held')")
    reader = sqlite3.connect(path, timeout=0.1)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            reader.execute("SELECT COUNT(*) FROM probe").fetchone()
    finally:
        reader.close()
        writer.rollback()
        writer.close()


def test_a_superseded_index_file_can_be_retired_while_its_generation_serves(
    paths: DatabasePaths,
) -> None:
    """AD-13's swap as the engine actually performs it.

    Not a rename: ``adapters/index/generation.py`` reads a generation whole into memory
    and closes its connection, and ``adapters/index/swap.py:103`` unlinks the superseded
    file when the caller retires it. The filesystem operation that can fail is that
    unlink, and checking a rename instead would report a fault on Windows -- where the
    real swap works -- because Windows refuses ``os.replace`` over an open handle.
    """
    outcome = _outcome(preflight(paths).outcomes, Check.INDEX_RETIREMENT)
    assert outcome.passed, outcome.detail
    assert "generation-1" in outcome.detail, (
        "the retired generation must still be readable from memory after its file is "
        "gone; that is the property that lets retirement be an explicit call"
    )


def test_the_retirement_check_matches_what_the_index_actually_does() -> None:
    """The check is only faithful while the swap stays a rebinding rather than a rename.

    Asserted against the source, so a future change to a rename-based swap makes this
    fail rather than leaving a preflight check quietly testing the wrong mechanism.
    """
    swap = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "askai"
        / "adapters"
        / "index"
        / "swap.py"
    ).read_text(encoding="utf-8")
    assert "unlink" in swap, "the swap no longer unlinks; the retirement check is now wrong"
    assert "os.replace" not in swap and "os.rename" not in swap, (
        "the swap now renames, so preflight must check a rename under an open handle "
        "instead of an unlink"
    )


def test_a_committed_row_survives_closing_and_reopening(paths: DatabasePaths) -> None:
    outcome = _outcome(preflight(paths).outcomes, Check.DURABILITY)
    assert outcome.passed, outcome.detail


# ------------------------------------------------------------ the startup precondition


def test_a_good_directory_passes_the_startup_precondition(paths: DatabasePaths) -> None:
    assert ensure_ready(paths).ok


def test_startup_refuses_and_names_the_specific_check_that_failed(
    paths: DatabasePaths,
) -> None:
    """The AC in one assertion: *"failing startup with a message naming the specific
    problem -- not a generic connection error"*."""
    with pytest.raises(PreflightFailed) as raised:
        ensure_ready(paths, minimum_free_bytes=HUGE)
    assert Check.FREE_SPACE.value in str(raised.value)
    assert str(paths.read_model.parent) in str(raised.value)


def test_the_failure_carries_the_whole_report_not_just_the_message(
    paths: DatabasePaths,
) -> None:
    """So a caller can print every fault rather than the first one."""
    with pytest.raises(PreflightFailed) as raised:
        ensure_ready(paths, minimum_free_bytes=HUGE)
    report = raised.value.report
    assert not report.ok
    assert len(report.outcomes) == len(Check)
    assert Check.FREE_SPACE in {outcome.check for outcome in report.failures}


# ---------------------------------------------------------------- the command


def test_the_command_exits_zero_and_prints_every_check(
    paths: DatabasePaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(paths.read_model.parent)]) == 0
    printed = capsys.readouterr().out
    for check in Check:
        assert check.value in printed, f"{check.value} is not in the operator's output"
    assert "all checks passed" in printed


def test_the_command_exits_one_when_the_machine_is_unfit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "nowhere")]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_command_exits_two_when_it_was_never_told_where_to_look(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three exit codes, because "unfit machine" and "unconfigured" are different
    problems for whoever reads the output, and only one of them is worth retrying."""
    monkeypatch.delenv(DATABASE_DIR_ENV, raising=False)
    assert main([]) == 2
    assert DATABASE_DIR_ENV in capsys.readouterr().err


def test_the_command_reads_the_directory_from_the_typed_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The AC's last clause, and the house rule: no ``os.getenv`` outside ``config/``."""
    monkeypatch.setenv(DATABASE_DIR_ENV, str(tmp_path))
    assert main([]) == 0
    assert str(tmp_path.resolve()) in capsys.readouterr().out


def test_the_command_rejects_more_than_one_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["one", "two"]) == 2
    assert "usage" in capsys.readouterr().err


def test_help_exits_zero_without_running_anything(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "ASKAI_DATABASE_DIR" in capsys.readouterr().out


def test_the_module_is_runnable_as_a_command(tmp_path: Path) -> None:
    """``python -m askai.adapters.store`` -- asserted by running it, because an entry
    point that only exists in a docstring is one nobody can invoke."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "askai.adapters.store", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout


# ---------------------------------------------------------------- the report type


def test_an_outcome_must_say_what_it_observed() -> None:
    """An outcome with no detail is one an operator cannot act on."""
    with pytest.raises(ValueError, match="no detail"):
        CheckOutcome(check=Check.FREE_SPACE, passed=True, detail="   ")


def test_the_default_floor_is_stated_rather_than_implied(paths: DatabasePaths) -> None:
    """It is an operational threshold and deliberately not a rule (AD-11 wants rules to
    be data about a ``QuerySpec``); what it must not be is a number nobody can see.

    Driven against ``tmp_path`` like every other test here. An earlier version of this
    one probed ``Path.cwd()`` -- the repository -- and left two probe files in the root
    when a connection was not closed. A check that writes into the working tree is one
    nobody should run from the working tree, and the test should not model that.
    """
    assert MINIMUM_FREE_BYTES > 0
    assert preflight(paths, minimum_free_bytes=1).ok


def test_no_probe_file_is_ever_written_outside_the_directory_under_test(
    paths: DatabasePaths,
) -> None:
    """The regression guard for the litter this test file once produced.

    ``preflight`` must confine itself to the directory it was handed, so running it can
    never leave anything in whatever happens to be the current working directory.
    """
    root = Path(__file__).resolve().parent.parent
    before = {path.name for path in root.iterdir()}
    assert preflight(paths).ok
    strays = sorted(name for name in {p.name for p in root.iterdir()} - before)
    assert not strays, f"preflight wrote into the repository root: {strays}"


def _outcome(outcomes: tuple[CheckOutcome, ...], check: Check) -> CheckOutcome:
    found = next((outcome for outcome in outcomes if outcome.check is check), None)
    assert found is not None, f"{check.value} was not reported at all"
    return found
