"""Running a refresh: one transaction, one report, one replaced state file.

Purity: IO, never on the answer path.

Story 1.9. Refresh is an operation someone starts -- a scheduled job or a command -- and
it is never reachable from the reader path. There is no function here that takes a
question, and nothing in ``api/`` imports this module; ``tests/test_refresh.py`` walks
the import graph out of ``api/`` and asserts it.

**Atomicity is sqlite's, and it is used rather than re-implemented.** The ingest of
Story 1.8 empties and reloads the read model inside a single transaction on a single
connection. Under WAL -- set once by the schema step and read back by every opener -- a
reader on any other connection continues to see the previous contents for the whole of
that transaction and the new contents afterwards. There is no instant at which a third
connection can observe the tables half-loaded, because the pages are not visible until
the commit. A reader that takes its own read transaction for the several statements of
one question therefore answers wholly from one version of the file, which is FR-109.

Three alternatives were available and are not used. Swapping a file under the databases
fails on Windows, where the open reader handles prevent the replace. A generation column
would need a table, and AD-20 gives the read model's tables one owner and this build one
schema version. Copying into a second database and re-pointing the process would make
the answer path's connection a mutable global. The transaction is the mechanism that
needs nothing added to be correct.

**What the report says is measured, not intended.** The row counts before and after come
from the tables themselves, so "what changed" is a difference between two readings of
the file rather than a tally kept by the loop that wrote it. The one number computed
twice -- how many indicators the confidentiality flag removed -- is cross-checked
between the census and the ingest, and a disagreement fails the refresh: two independent
counts of one thing exist so that they can be compared.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from askai.adapters.readmodel.export import CmsExport, ExportError
from askai.adapters.readmodel.ingest import IngestError, IngestReport, ingest_published_layer
from askai.refresh.rejections import (
    RefreshSourceError,
    Rejection,
    RejectionClass,
    survey_rejections,
)
from askai.refresh.report import RefreshOutcome, RefreshReport, read_served_version
from askai.refresh.state import RefreshState, read_state, write_state

__all__ = ["RefreshFailed", "run_refresh"]

#: The reason the census and the ingest both count confidential indicators.
_CONFIDENTIAL_REASON: Final = "the indicator is flagged confidential"


class RefreshFailed(RuntimeError):
    """The refresh could not be attempted at all, so there is no report to write.

    Distinct from a failed refresh, which *does* produce a report: this is the export
    being unreadable or the census being unable to run, which happens before anything
    the report could describe.
    """


def run_refresh(
    connection: sqlite3.Connection,
    export: CmsExport,
    state_path: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    budget: int | None = None,
) -> RefreshReport:
    """Replace the read model's contents from *export*, and state what happened.

    *state_path* of ``None`` runs without persisting anything, which is how a dry run and
    every in-memory test work. When it is given, the state file is replaced after the
    ingest commits -- never before, so the recorded moment can lag the data it describes
    but can never run ahead of it.

    *clock* is injectable, and is read exactly twice: once before the work and once
    after. *budget* caps the worked examples per rejection class; ``None`` reads the rule.

    Never raises for a bad export's *contents*: a refusal is an outcome, and an outcome
    is a report. It raises only when there is nothing to report on -- an export that
    cannot be read at all.
    """
    tick = _utc_now if clock is None else clock
    started_at = tick()

    try:
        rejections = survey_rejections(export, budget)
    except (ExportError, RefreshSourceError) as error:
        raise RefreshFailed(
            f"the export cannot be surveyed, so no refresh was attempted -- {error}"
        ) from error

    before = read_served_version(connection)
    failure: str | None = None
    ingested: IngestReport | None = None
    try:
        ingested = ingest_published_layer(connection, export)
    except IngestError as error:
        failure = str(error)
    except ExportError as error:
        failure = f"the export is incomplete: {error}"

    if ingested is not None:
        failure = _disagreement(ingested, rejections)

    after = read_served_version(connection)
    succeeded = failure is None
    report = RefreshReport(
        started_at=started_at,
        finished_at=tick(),
        outcome=RefreshOutcome.SUCCEEDED if succeeded else RefreshOutcome.FAILED,
        failure=failure,
        changed=after.changes_from(before) if succeeded else (),
        served=after,
        rejections=rejections,
    )
    if state_path is not None:
        _record(state_path, report)
    return report


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _disagreement(ingested: IngestReport, rejections: tuple[Rejection, ...]) -> str | None:
    """The one number both sides count, compared. ``None`` when they agree.

    The ingest excluded confidential indicators as it wrote; the census counted them off
    the export without writing anything. If the two disagree, one of them is reading the
    export wrongly and the read model is not what either of them believes -- which is
    worth failing the refresh over, rather than reporting a count nobody can trust.
    """
    surveyed = sum(
        rejection.count
        for rejection in rejections
        if rejection.rejection_class is RejectionClass.PUBLICATION_STATE
        and rejection.reason.startswith(_CONFIDENTIAL_REASON)
    )
    if surveyed == ingested.confidential_indicators_excluded:
        return None
    return (
        f"the rejection census counted {surveyed} confidential indicators and the "
        f"ingest excluded {ingested.confidential_indicators_excluded}; the two read the "
        "same export and must agree before the read model is trusted"
    )


def _record(state_path: Path, report: RefreshReport) -> None:
    """Advance the persisted state. Written after the commit -- see ``state``'s docstring."""
    previous = read_state(state_path)
    state = RefreshState.first(report) if previous is None else previous.after(report)
    write_state(state_path, state)
