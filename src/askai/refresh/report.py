"""What a refresh did: what changed, what failed, when it ran, and what is served now.

Purity: IO, never on the answer path.

Stories 1.9 and 1.10 share one report object, because they are one question asked from
two sides. FR-108 wants a refresh to state its outcome so that a silent refresh is never
mistaken for a working one; FR-110 wants everything it refused named with counts and
examples. A report that carried the first and not the second would say "succeeded" over
a read model that dropped sixty-one rows.

Three properties are deliberate:

**What is served is read back from the database, not tallied from the writer.** The
counts on :class:`ServedVersion` come from the tables after the commit, on the same
connection, inside one read transaction -- so they are a statement about the file rather
than about what the loop meant to do.

**A failure still produces a report.** ``outcome`` is ``failed``, ``changed`` is empty,
and ``served`` is the version that survived, which is the whole content of the answer to
"what is the engine serving now". A refresh that raised and wrote nothing down is the
silent refresh the story is about.

**The report round-trips through JSON.** It is persisted by :mod:`askai.refresh.state`
so ``when it last ran`` outlives the process that ran it, and it is bounded by
construction: the example budget in ``rules/data/refresh-freshness.yaml`` caps the
examples, and nothing else in the report grows with the size of the export.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from askai.adapters.readmodel.schema import READ_MODEL
from askai.refresh.rejections import Rejection, RejectionClass, RejectionExample

__all__ = [
    "RefreshOutcome",
    "RefreshReport",
    "ReportFormatError",
    "ServedVersion",
    "TableChange",
    "TableRows",
    "read_served_version",
]

#: The read model's tables, in a fixed order, read from the schema rather than listed.
#: A table added to the read model is counted here without this module being edited.
_COUNTED_TABLES: Final = tuple(table.name for table in READ_MODEL.tables)


class ReportFormatError(RuntimeError):
    """A persisted report is not in the shape this build writes, so it is not adopted."""


class RefreshOutcome(StrEnum):
    """Did the refresh replace the contents, or leave the previous ones in place?

    Two members and no third. "Partially succeeded" is unrepresentable because it is
    unreachable: the ingest is one transaction, so either the new contents committed or
    the old ones are still there.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TableRows:
    """One table and how many rows it holds."""

    table: str
    rows: int


@dataclass(frozen=True, slots=True)
class ServedVersion:
    """What the read model holds, counted after the commit. "What we are serving now."

    The counts are the version. Two refreshes of the same export produce the same
    :class:`ServedVersion`, which is what makes "did anything change" answerable without
    keeping a copy of the previous export.
    """

    tables: tuple[TableRows, ...]

    @property
    def rows(self) -> Mapping[str, int]:
        return {entry.table: entry.rows for entry in self.tables}

    @property
    def total_rows(self) -> int:
        return sum(entry.rows for entry in self.tables)

    @property
    def is_empty(self) -> bool:
        """An empty read model answers nothing; a refresh that produced one says so."""
        return self.total_rows == 0

    def changes_from(self, previous: ServedVersion) -> tuple[TableChange, ...]:
        """Only the tables whose row count moved. "What changed", with no noise."""
        before = previous.rows
        return tuple(
            TableChange(table=entry.table, before=before.get(entry.table, 0), after=entry.rows)
            for entry in self.tables
            if before.get(entry.table, 0) != entry.rows
        )


@dataclass(frozen=True, slots=True)
class TableChange:
    """One table's row count, before and after."""

    table: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before


def read_served_version(connection: sqlite3.Connection) -> ServedVersion:
    """Count every read-model table inside one read transaction.

    The transaction is the point, not the counting. Under WAL a reader that issues five
    separate statements can straddle a writer's commit and see two of them on one side
    of it -- which is exactly the mixture FR-109 forbids. Holding one snapshot open for
    all five makes the five counts a description of a single version of the file.
    """
    connection.execute("BEGIN")
    try:
        counted = tuple(
            TableRows(table=table, rows=_count(connection, table)) for table in _COUNTED_TABLES
        )
    finally:
        connection.rollback()
    return ServedVersion(tables=counted)


def _count(connection: sqlite3.Connection, table: str) -> int:
    # The table name is one of this module's own constants, read off the schema; it is
    # never caller input, and sqlite takes no parameter binding in this position.
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    if row is None:
        raise ReportFormatError(f"counting {table} returned no row")
    value: object = row[0]
    if not isinstance(value, int):
        raise ReportFormatError(f"counting {table} returned {value!r}, expected a count")
    return value


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """One refresh, stated: when, what changed, what failed, what is served, what was refused."""

    started_at: datetime
    finished_at: datetime
    outcome: RefreshOutcome
    #: Why it failed, in the words of the failure itself. ``None`` exactly when it did not.
    failure: str | None
    changed: tuple[TableChange, ...]
    served: ServedVersion
    rejections: tuple[Rejection, ...]

    def __post_init__(self) -> None:
        if (self.outcome is RefreshOutcome.FAILED) != (self.failure is not None):
            raise ValueError(
                "a refresh report is failed with a stated reason or succeeded with "
                "none; an outcome and a reason that disagree is the silent failure "
                "FR-108 exists to end"
            )
        if self.outcome is RefreshOutcome.FAILED and self.changed:
            raise ValueError(
                "a failed refresh reports no change: the ingest is one transaction, so "
                "a failure leaves the previous contents exactly as they were"
            )

    @property
    def succeeded(self) -> bool:
        return self.outcome is RefreshOutcome.SUCCEEDED

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def rejected_rows(self) -> int:
        """Every row any class refused. Never a sample -- the counts are whole."""
        return sum(rejection.count for rejection in self.rejections)

    def rejections_in(self, rejection_class: RejectionClass) -> tuple[Rejection, ...]:
        return tuple(
            rejection
            for rejection in self.rejections
            if rejection.rejection_class is rejection_class
        )

    def summary(self) -> str:
        """One line for a scheduled job's log. Says the outcome first, then the damage."""
        head = f"refresh {self.outcome.value} in {self.duration_seconds:.2f}s"
        if self.failure is not None:
            return f"{head}: {self.failure}"
        moved = ", ".join(f"{change.table} {change.delta:+d}" for change in self.changed)
        return (
            f"{head}; serving {self.served.total_rows} rows"
            f"; changed: {moved or 'nothing'}"
            f"; refused {self.rejected_rows} rows in {len(self.rejections)} classes"
        )

    # ------------------------------------------------------------------ serialisation

    def as_mapping(self) -> Mapping[str, object]:
        """The report as plain JSON-able data, for the state file."""
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "outcome": self.outcome.value,
            "failure": self.failure,
            "changed": [
                {"table": change.table, "before": change.before, "after": change.after}
                for change in self.changed
            ],
            "served": [
                {"table": entry.table, "rows": entry.rows} for entry in self.served.tables
            ],
            "rejections": [
                {
                    "class": rejection.rejection_class.value,
                    "reason": rejection.reason,
                    "source": rejection.source,
                    "count": rejection.count,
                    "truncated": rejection.examples_are_truncated,
                    "examples": [
                        {"identifier": example.identifier, "detail": example.detail}
                        for example in rejection.examples
                    ],
                }
                for rejection in self.rejections
            ],
        }

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> RefreshReport:
        """Rebuild a report written by :meth:`as_mapping`, or refuse it by name."""
        return cls(
            started_at=_time(document, "started_at"),
            finished_at=_time(document, "finished_at"),
            outcome=RefreshOutcome(_text(document, "outcome")),
            failure=_optional_text(document, "failure"),
            changed=tuple(
                TableChange(
                    table=_text(item, "table"),
                    before=_number(item, "before"),
                    after=_number(item, "after"),
                )
                for item in _items(document, "changed")
            ),
            served=ServedVersion(
                tables=tuple(
                    TableRows(table=_text(item, "table"), rows=_number(item, "rows"))
                    for item in _items(document, "served")
                )
            ),
            rejections=tuple(
                Rejection(
                    rejection_class=RejectionClass(_text(item, "class")),
                    reason=_text(item, "reason"),
                    source=_text(item, "source"),
                    count=_number(item, "count"),
                    examples=tuple(
                        RejectionExample(
                            identifier=_text(example, "identifier"),
                            detail=_text(example, "detail"),
                        )
                        for example in _items(item, "examples")
                    ),
                )
                for item in _items(document, "rejections")
            ),
        )


def _field(document: Mapping[str, object], key: str) -> object:
    if key not in document:
        raise ReportFormatError(f"the persisted refresh report has no `{key}` field")
    return document[key]


def _text(document: Mapping[str, object], key: str) -> str:
    value = _field(document, key)
    if not isinstance(value, str):
        raise ReportFormatError(f"`{key}` is {value!r}, expected text")
    return value


def _optional_text(document: Mapping[str, object], key: str) -> str | None:
    value = _field(document, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReportFormatError(f"`{key}` is {value!r}, expected text or nothing")
    return value


def _number(document: Mapping[str, object], key: str) -> int:
    value = _field(document, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReportFormatError(f"`{key}` is {value!r}, expected a count")
    return value


def _items(document: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    value = _field(document, key)
    if not isinstance(value, list):
        raise ReportFormatError(f"`{key}` is {value!r}, expected a list")
    for item in value:
        if not isinstance(item, dict):
            raise ReportFormatError(f"`{key}` holds {item!r}, expected a mapping")
    return [item for item in value if isinstance(item, dict)]


def _time(document: Mapping[str, object], key: str) -> datetime:
    raw = _text(document, key)
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise ReportFormatError(f"`{key}` is {raw!r}, which is not a recorded moment") from error
