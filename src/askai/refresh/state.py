"""When the read model was last refreshed, and what that refresh said. Replaced whole.

Purity: IO, never on the answer path.

AD-21 asks for staleness to be *visible*, which means the answer to "when did this last
work" has to outlive the process that ran the job. The read model itself cannot hold it:
AD-20 gives every table exactly one owning module, the read model's tables are owned by
the ingest, and this build's schema version is fixed -- so a refresh-state table would be
a schema change wearing a story's clothes. It lives beside the databases instead, in one
small JSON file.

Two things make it safe to read while a refresh is running:

**It is replaced, never edited.** The new state is written to a temporary file in the
same directory and moved over the old one with :func:`os.replace`, which is atomic on
every platform this runs on. A reader either opens the previous file or the next one;
there is no moment at which it holds half a document.

**The clock never runs ahead of the data.** ``refreshed_at`` is written *after* the
ingest transaction commits, so during the gap between the two a reader is told the copy
is slightly older than it is. That asymmetry is deliberate and is the only one that is
safe: a stamp written first would advertise content that had not landed, and a monitor
would report fresh over a read model that was still the old one.

``refreshed_at`` moves only on success. A failed attempt records itself -- its moment and
its reason -- without touching the mark, because the engine is still serving what the
last successful refresh left and that is what a reader must be told.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from askai.config.database import DatabasePaths
from askai.refresh.report import RefreshOutcome, RefreshReport, ReportFormatError

__all__ = [
    "STATE_FILENAME",
    "RefreshState",
    "StateError",
    "read_state",
    "state_path_for",
    "write_state",
]

#: Beside the three databases, named so an operator listing the directory knows what it
#: is without opening it.
STATE_FILENAME: Final = "refresh_state.json"

#: The document's own version key. Moments in this file are ISO 8601 with the offset
#: the caller gave, round-tripped rather than reformatted.
_VERSION_KEY: Final = "state_version"

#: The shape of this file. Bumped when the document changes shape; a file at another
#: version is refused rather than adopted, exactly as the database schema version is.
STATE_VERSION: Final = 1


class StateError(RuntimeError):
    """The refresh state file cannot be read, written, or is not in this build's shape."""


@dataclass(frozen=True, slots=True)
class RefreshState:
    """What is known about refreshes of this read model, as of the last attempt.

    ``refreshed_at`` and ``last_report`` are not the same fact and are stored apart on
    purpose: the report describes the *last attempt*, success or failure, while the mark
    describes the last one whose contents are what a reader is being served.
    """

    #: The moment the last successful refresh committed. ``None`` before the first one.
    refreshed_at: datetime | None
    #: The moment the last attempt finished, whatever it did.
    last_attempt_at: datetime
    last_report: RefreshReport

    @property
    def last_attempt_succeeded(self) -> bool:
        return self.last_report.outcome is RefreshOutcome.SUCCEEDED

    def after(self, report: RefreshReport) -> RefreshState:
        """This state, advanced by *report*. The mark moves only when the report did."""
        return RefreshState(
            refreshed_at=report.finished_at if report.succeeded else self.refreshed_at,
            last_attempt_at=report.finished_at,
            last_report=report,
        )

    @classmethod
    def first(cls, report: RefreshReport) -> RefreshState:
        """The state a read model with no history reaches after its first attempt."""
        return cls(
            refreshed_at=report.finished_at if report.succeeded else None,
            last_attempt_at=report.finished_at,
            last_report=report,
        )


def state_path_for(paths: DatabasePaths) -> Path:
    """Where the state file sits for a given estate: beside the read model it describes."""
    return paths.read_model.parent / STATE_FILENAME


def write_state(path: Path, state: RefreshState) -> None:
    """Replace the file at *path* with *state*, atomically.

    The temporary file is created in the same directory, because :func:`os.replace` is
    only atomic within one filesystem and a temporary directory elsewhere on the machine
    is not guaranteed to be on the same one.
    """
    document: dict[str, object] = {
        _VERSION_KEY: STATE_VERSION,
        "refreshed_at": None if state.refreshed_at is None else state.refreshed_at.isoformat(),
        "last_attempt_at": state.last_attempt_at.isoformat(),
        "last_report": state.last_report.as_mapping(),
    }
    scratch = path.with_name(f"{path.name}.{os.getpid()}.partial")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(scratch, path)
    except OSError as error:
        scratch.unlink(missing_ok=True)
        raise StateError(f"the refresh state at {path} could not be written -- {error}") from error


def read_state(path: Path) -> RefreshState | None:
    """The state at *path*, or ``None`` if no refresh has ever been recorded there.

    ``None`` means "never refreshed", which the freshness block reports as stale. A
    malformed or foreign-versioned file is *not* ``None``: it raises, because adopting it
    as "never refreshed" would hide a real state file behind a parse error.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise StateError(f"the refresh state at {path} cannot be read -- {error}") from error
    try:
        document: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StateError(f"the refresh state at {path} is not readable JSON -- {error}") from error
    if not isinstance(document, dict):
        raise StateError(f"the refresh state at {path} is not a document, it is {document!r}")

    version = document.get(_VERSION_KEY)
    if version != STATE_VERSION:
        raise StateError(
            f"the refresh state at {path} is at version {version!r}, this build writes "
            f"{STATE_VERSION}; it is not read at a version it was not written for"
        )
    report = document.get("last_report")
    if not isinstance(report, dict):
        raise StateError(f"the refresh state at {path} carries no report of its last attempt")
    try:
        return RefreshState(
            refreshed_at=_moment(document.get("refreshed_at"), path, "refreshed_at"),
            last_attempt_at=_required_moment(document.get("last_attempt_at"), path),
            last_report=RefreshReport.from_mapping(report),
        )
    except ReportFormatError as error:
        raise StateError(
            f"the refresh state at {path} holds a report this build cannot read: {error}"
        ) from error


def _moment(value: object, path: Path, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StateError(f"the refresh state at {path} spells `{field}` as {value!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise StateError(
            f"the refresh state at {path} spells `{field}` as {value!r}, which is not a "
            "recorded moment"
        ) from error


def _required_moment(value: object, path: Path) -> datetime:
    moment = _moment(value, path, "last_attempt_at")
    if moment is None:
        raise StateError(
            f"the refresh state at {path} records no moment for its last attempt; a "
            "state file exists because an attempt was made"
        )
    return moment
