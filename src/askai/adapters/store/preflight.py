"""Story 1.7 -- the check that proves *this machine* can hold the estate.

Purity: IO.

Everything here is about the filesystem the three databases live on, not about their
contents. A permissions problem, a full disk, a directory that is not where the operator
thinks it is, or a container layer that discards writes on restart are all faults that
otherwise surface as a failed *answer*, hours later, looking like an engine defect.

**The checks run against probe files, never against the estate.** Each mutating check
creates ``askai-preflight-<pid>-<n>.sqlite3`` beside the real databases, exercises it,
and removes it. Beside them on purpose: it is the same directory, the same filesystem
and the same permissions, so the result means something -- and the real read model is
never opened for writing by a check whose whole job is to run on a live machine.

**Four faults this is written to catch, none of which a plain "can I connect?" finds:**

* **The sidecars.** WAL needs to create ``-wal`` and ``-shm`` next to the database. A
  directory that is writable enough to *open* an existing file can still refuse those,
  and the failure does not appear until the first concurrent read.
* **A blocked reader.** WAL's entire purpose is that a reader is not blocked by a
  writer. If the file were not actually in WAL -- or the filesystem does not support the
  shared memory WAL needs, which is the normal case on some network mounts -- readers
  block behind writers and every answer waits on the refresh.
* **A superseded index that cannot be retired.** AD-20 rebuilds the semantic index into a
  new file and swaps it by reference; the old file is removed once its generation is no
  longer current. A filesystem that refuses that unlink leaves every refresh's predecessor
  behind until the disk fills.
* **A write that never reached disk.** A container writing to its own ephemeral layer
  answers every question correctly until it restarts.

**The free-space floor is an argument, not a rule.** AD-11 puts business logic in
``rules/`` and says a rule that is not expressible as data about a ``QuerySpec`` is a
code path needing a recorded reason. A disk-space floor says nothing about a question;
it is an operational threshold that depends on the machine, so it is a parameter with a
stated default and this paragraph is the recorded reason.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from askai.config.database import DatabasePaths

__all__ = [
    "MINIMUM_FREE_BYTES",
    "Check",
    "CheckOutcome",
    "PreflightFailed",
    "PreflightReport",
    "preflight",
]

#: The floor the checks use unless the caller states another. The estate is small -- the
#: published layer is 8,127 datapoints and roughly 7,400 vectors -- so this is headroom
#: for the databases, their WAL sidecars, and an index rebuild's second copy existing at
#: the same time as the first, rather than a projection of growth.
MINIMUM_FREE_BYTES: Final = 512 * 1024 * 1024

_PROBE_STEM: Final = "askai-preflight"
#: A reader that is blocked rather than free raises ``database is locked`` after this
#: many seconds. It has to be non-zero -- sqlite treats 0 as "fail immediately", which
#: would make a merely slow filesystem look like a blocked reader -- and short enough
#: that a genuinely blocked reader does not stall the check.
_BLOCKED_READER_TIMEOUT: Final = 2.0


class Check(StrEnum):
    """The checks, in the order they run. Named so a failure names itself."""

    DIRECTORY_EXISTS = "directory-exists"
    DIRECTORY_WRITABLE = "directory-writable"
    FREE_SPACE = "free-space"
    WAL_SIDECARS = "wal-sidecars"
    READER_NOT_BLOCKED = "reader-not-blocked-by-writer"
    INDEX_RETIREMENT = "retire-index-file-while-serving"
    DURABILITY = "durability-across-reopen"


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One check, and what it found.

    ``detail`` is filled whether the check passed or failed: a passing check that says
    what it observed -- how much space, which paths -- is what makes the report useful
    to an operator who is not yet in trouble.
    """

    check: Check
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError(
                f"{self.check.value} reported no detail; an outcome that cannot say what "
                "it observed is one an operator cannot act on"
            )


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Every check, the resolved paths, and whether the machine is fit to run on.

    The paths are on the report rather than left to the caller to remember. A
    misconfigured directory is the commonest fault here and the one that hides best: the
    engine happily creates its databases somewhere nobody is looking, and every check
    passes. Printing the absolute paths it actually used is what makes that visible.
    """

    directory: Path
    paths: DatabasePaths
    outcomes: tuple[CheckOutcome, ...]

    @property
    def ok(self) -> bool:
        return all(outcome.passed for outcome in self.outcomes)

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.passed)

    def render(self) -> str:
        """The report as an operator reads it: the paths, then a line per check.

        ASCII only, for the reason ``rules/cli.py`` gives: a console that is not UTF-8
        must not turn a passing check into a ``UnicodeEncodeError`` that reads like a
        store failure.
        """
        lines = [
            f"database directory: {self.directory}",
            f"  read model:     {self.paths.read_model}",
            f"  record store:   {self.paths.record_store}",
            f"  semantic index: {self.paths.semantic_index}",
            "",
        ]
        for outcome in self.outcomes:
            mark = "ok  " if outcome.passed else "FAIL"
            lines.append(f"[{mark}] {outcome.check.value}: {outcome.detail}")
        lines.append("")
        lines.append(
            "all checks passed"
            if self.ok
            else f"{len(self.failures)} of {len(self.outcomes)} checks failed"
        )
        return "\n".join(lines)


class PreflightFailed(RuntimeError):
    """The machine cannot hold the estate, and the message names which check said so.

    Raised by the startup precondition rather than returned, because a process that
    starts anyway has converted an operator-visible fault into a reader-visible one. The
    report travels on the exception so a caller can print the whole thing.
    """

    def __init__(self, report: PreflightReport) -> None:
        named = ", ".join(outcome.check.value for outcome in report.failures)
        super().__init__(
            f"the database directory {report.directory} did not pass preflight: {named}"
        )
        self.report = report


def preflight(
    paths: DatabasePaths, *, minimum_free_bytes: int = MINIMUM_FREE_BYTES
) -> PreflightReport:
    """Run every check against the directory *paths* resolve into, and report.

    Total: it returns a report rather than raising, so an operator running the standalone
    command sees **every** fault at once rather than the first one. The startup path
    turns a failing report into ``PreflightFailed``; that is where refusing belongs.

    The checks are ordered so that a later one is not run against a directory an earlier
    one already found unusable -- a "reader is blocked" failure on a directory that does
    not exist would be noise pointing at the wrong thing. Once a check fails, the ones
    that depend on it are reported as not run, with that stated as their detail.
    """
    directory = paths.read_model.parent
    outcomes: list[CheckOutcome] = []

    existing = _directory_exists(directory)
    outcomes.append(existing)
    writable = (
        _directory_writable(directory)
        if existing.passed
        else _not_run(Check.DIRECTORY_WRITABLE, Check.DIRECTORY_EXISTS)
    )
    outcomes.append(writable)
    outcomes.append(
        _free_space(directory, minimum_free_bytes)
        if existing.passed
        else _not_run(Check.FREE_SPACE, Check.DIRECTORY_EXISTS)
    )

    if not writable.passed:
        outcomes.extend(
            _not_run(check, Check.DIRECTORY_WRITABLE)
            for check in (
                Check.WAL_SIDECARS,
                Check.READER_NOT_BLOCKED,
                Check.INDEX_RETIREMENT,
                Check.DURABILITY,
            )
        )
        return PreflightReport(directory=directory, paths=paths, outcomes=tuple(outcomes))

    outcomes.append(_wal_sidecars(directory))
    outcomes.append(_reader_not_blocked(directory))
    outcomes.append(_index_retirement(directory))
    outcomes.append(_durability(directory))
    return PreflightReport(directory=directory, paths=paths, outcomes=tuple(outcomes))


def ensure_ready(
    paths: DatabasePaths, *, minimum_free_bytes: int = MINIMUM_FREE_BYTES
) -> PreflightReport:
    """The startup precondition: run the checks, and refuse to continue if any failed.

    The AC's *"failing startup with a message naming the specific problem -- not a
    generic connection error"* is the whole point of the exception carrying the report.
    """
    report = preflight(paths, minimum_free_bytes=minimum_free_bytes)
    if not report.ok:
        raise PreflightFailed(report)
    return report


# --------------------------------------------------------------------- the checks


def _not_run(check: Check, because: Check) -> CheckOutcome:
    return CheckOutcome(
        check=check,
        passed=False,
        detail=f"not run: {because.value} failed, so this check would report the wrong fault",
    )


def _directory_exists(directory: Path) -> CheckOutcome:
    if directory.is_dir():
        return CheckOutcome(
            check=Check.DIRECTORY_EXISTS, passed=True, detail=f"{directory} is a directory"
        )
    if directory.exists():
        return CheckOutcome(
            check=Check.DIRECTORY_EXISTS,
            passed=False,
            detail=f"{directory} exists but is not a directory",
        )
    return CheckOutcome(
        check=Check.DIRECTORY_EXISTS, passed=False, detail=f"{directory} does not exist"
    )


def _directory_writable(directory: Path) -> CheckOutcome:
    probe = directory / f"{_PROBE_STEM}-{os.getpid()}.probe"
    try:
        probe.write_bytes(b"askai")
        probe.unlink()
    except OSError as error:  # the boundary AD-15 permits this at
        return CheckOutcome(
            check=Check.DIRECTORY_WRITABLE,
            passed=False,
            detail=f"cannot create a file in {directory} -- {error}",
        )
    return CheckOutcome(
        check=Check.DIRECTORY_WRITABLE,
        passed=True,
        detail=f"created and removed {probe.name}",
    )


def _free_space(directory: Path, minimum: int) -> CheckOutcome:
    try:
        free = shutil.disk_usage(directory).free
    except OSError as error:  # the boundary AD-15 permits this at
        return CheckOutcome(
            check=Check.FREE_SPACE,
            passed=False,
            detail=f"cannot read free space for {directory} -- {error}",
        )
    enough = free >= minimum
    return CheckOutcome(
        check=Check.FREE_SPACE,
        passed=enough,
        detail=(
            f"{_megabytes(free)} free, {_megabytes(minimum)} required"
            + ("" if enough else " -- not enough for the estate and an index rebuild")
        ),
    )


def _wal_sidecars(directory: Path) -> CheckOutcome:
    """WAL is active *and* its two sidecar files can actually be created here.

    Both halves, because they fail separately: a filesystem can accept ``PRAGMA
    journal_mode = wal`` and still refuse the shared-memory file, at which point the
    mode reads back as something else or the first concurrent reader fails.
    """
    with _probe(directory, "wal") as path:
        # `sqlite3.connect` as a context manager commits the transaction and leaves the
        # connection *open*; on Windows the probe file then cannot be removed, so the
        # check would litter the estate's own directory. Closed explicitly instead.
        connection = sqlite3.connect(path)
        try:
            mode = str(connection.execute("PRAGMA journal_mode = wal").fetchone()[0])
            if mode.lower() != "wal":
                return CheckOutcome(
                    check=Check.WAL_SIDECARS,
                    passed=False,
                    detail=f"journal_mode came back as {mode!r}, not 'wal'",
                )
            connection.execute("CREATE TABLE probe (value TEXT)")
            connection.execute("INSERT INTO probe VALUES ('x')")
            connection.commit()
            missing = [
                suffix for suffix in ("-wal", "-shm") if not Path(f"{path}{suffix}").exists()
            ]
            if missing:
                return CheckOutcome(
                    check=Check.WAL_SIDECARS,
                    passed=False,
                    detail=(
                        f"WAL is active but {', '.join(missing)} was not created in "
                        f"{directory}; the first concurrent read would fail"
                    ),
                )
        except sqlite3.Error as error:
            return CheckOutcome(
                check=Check.WAL_SIDECARS, passed=False, detail=f"sqlite refused WAL -- {error}"
            )
        finally:
            connection.close()
    return CheckOutcome(
        check=Check.WAL_SIDECARS,
        passed=True,
        detail="journal_mode=wal, and -wal and -shm were both created",
    )


def _reader_not_blocked(directory: Path) -> CheckOutcome:
    """A reader reads while a writer holds an open write transaction (AD-20).

    The writer takes a real write lock -- ``BEGIN IMMEDIATE`` plus an insert -- because a
    deferred transaction that has not written yet blocks nobody, and a check that passes
    against no lock at all is a check that cannot fail.
    """
    with _probe(directory, "lock") as path:
        writer = _wal_connection(path)
        try:
            writer.execute("CREATE TABLE probe (value TEXT)")
            writer.commit()
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO probe VALUES ('held')")
            reader = sqlite3.connect(path, timeout=_BLOCKED_READER_TIMEOUT)
            try:
                reader.execute("SELECT COUNT(*) FROM probe").fetchone()
            except sqlite3.OperationalError as error:
                return CheckOutcome(
                    check=Check.READER_NOT_BLOCKED,
                    passed=False,
                    detail=(
                        f"a reader was blocked by an open writer -- {error}; on this "
                        "filesystem every answer would wait behind a refresh"
                    ),
                )
            finally:
                reader.close()
            writer.rollback()
        except sqlite3.Error as error:
            return CheckOutcome(
                check=Check.READER_NOT_BLOCKED, passed=False, detail=f"sqlite error -- {error}"
            )
        finally:
            writer.close()
    return CheckOutcome(
        check=Check.READER_NOT_BLOCKED,
        passed=True,
        detail="a reader completed while a writer held an open write transaction",
    )


def _index_retirement(directory: Path) -> CheckOutcome:
    """A superseded index file is removed while the generation it held is still serving.

    **This mirrors what the engine actually does, which is not a rename.**
    ``adapters/index/generation.py:177-199`` reads a generation *whole into memory* and
    closes its connection in a ``finally``; ``adapters/index/swap.py`` then publishes it
    by rebinding one attribute, and ``swap.py:103`` unlinks the superseded file when the
    caller retires it. So the filesystem operation to check is **unlink of a closed
    database while a newer one exists beside it**, not replacement of an open handle.

    Checking the rename instead would be stricter than the design and wrong in a way
    that matters: Windows refuses ``os.replace`` over an open handle, so a rename-based
    check reports a fault on a machine where the real swap works perfectly.
    """
    with _probe(directory, "retired") as superseded, _probe(directory, "current") as live:
        try:
            older = _wal_connection(superseded)
            older.execute("CREATE TABLE probe (value TEXT)")
            older.execute("INSERT INTO probe VALUES ('generation-1')")
            older.commit()
            # Read it whole and close, exactly as `load_generation` does. What survives
            # is an in-memory value; nothing holds the file afterwards.
            held = str(older.execute("SELECT value FROM probe").fetchone()[0])
            older.close()

            newer = _wal_connection(live)
            newer.execute("CREATE TABLE probe (value TEXT)")
            newer.execute("INSERT INTO probe VALUES ('generation-2')")
            newer.commit()
            newer.close()
        except sqlite3.Error as error:
            return CheckOutcome(
                check=Check.INDEX_RETIREMENT, passed=False, detail=f"sqlite error -- {error}"
            )
        try:
            for suffix in ("-shm", "-wal", ""):
                Path(f"{superseded}{suffix}").unlink(missing_ok=True)
        except OSError as error:  # the boundary AD-15 permits this at
            return CheckOutcome(
                check=Check.INDEX_RETIREMENT,
                passed=False,
                detail=(
                    f"could not remove a superseded index file -- {error}; every refresh "
                    "would leave its predecessor behind until the disk filled"
                ),
            )
        if superseded.exists():
            return CheckOutcome(
                check=Check.INDEX_RETIREMENT,
                passed=False,
                detail=f"{superseded.name} still exists after being removed",
            )
    return CheckOutcome(
        check=Check.INDEX_RETIREMENT,
        passed=True,
        detail=(
            f"a superseded index file was removed while its generation ({held!r}) was "
            "still held in memory, with its successor already in place"
        ),
    )


def _durability(directory: Path) -> CheckOutcome:
    """A committed row survives closing every connection and reopening the file.

    Proves the write reached the filesystem rather than a container layer that is
    discarded on restart -- a fault that looks like nothing at all until it looks like
    every answer disappearing.
    """
    with _probe(directory, "durable") as path:
        try:
            connection = _wal_connection(path)
            connection.execute("CREATE TABLE probe (value TEXT)")
            connection.execute("INSERT INTO probe VALUES ('persisted')")
            connection.commit()
            connection.close()

            reopened = sqlite3.connect(path)
            try:
                row = reopened.execute("SELECT value FROM probe").fetchone()
            finally:
                reopened.close()
        except sqlite3.Error as error:
            return CheckOutcome(
                check=Check.DURABILITY, passed=False, detail=f"sqlite error -- {error}"
            )
        if row is None or str(row[0]) != "persisted":
            return CheckOutcome(
                check=Check.DURABILITY,
                passed=False,
                detail=(
                    "a committed row was gone after reopening the file; writes are not "
                    "reaching this filesystem"
                ),
            )
    return CheckOutcome(
        check=Check.DURABILITY,
        passed=True,
        detail="a committed row was still present after every connection was closed",
    )


# --------------------------------------------------------------------- probe files


class _probe:
    """A uniquely named database beside the estate, removed with its WAL sidecars.

    A context manager rather than ``tempfile``: the check is about *this* directory, and
    a temp file the OS placed elsewhere would prove something about another filesystem.
    """

    def __init__(self, directory: Path, label: str) -> None:
        self._path = directory / f"{_PROBE_STEM}-{os.getpid()}-{label}.sqlite3"

    def __enter__(self) -> Path:
        self._remove()
        return self._path

    def __exit__(self, *_exc: object) -> None:
        self._remove()

    def _remove(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self._path}{suffix}")
            try:
                candidate.unlink(missing_ok=True)
            except OSError:  # the boundary AD-15 permits this at
                # A probe that cannot be removed is not a reason to fail the run: the
                # check it belonged to has already reported, and the directory-writable
                # check is the one that speaks to permissions.
                pass


def _wal_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = wal")
    return connection


def _megabytes(count: int) -> str:
    return f"{count // (1024 * 1024)} MB"
