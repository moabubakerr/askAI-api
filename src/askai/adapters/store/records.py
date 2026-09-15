"""The record store's writer -- the only module that writes the ``record`` table.

Purity: IO.

AD-20 gives each table exactly one owning module and ``tests/test_schema.py`` checks the
claim against the source, so this file is where an ``INSERT INTO record`` may appear and
the only one. ``observability/`` decides what a record contains and how large it may be
(AD-16); this decides nothing at all. It binds parameters.

Two things it deliberately does not do:

**It does not write ``conversation_turn``.** That table is the conversation's, filled by
the story that owns history. A record carries ``conversation_id`` and ``turn`` as the
answer's own coordinates, and writing a second table from the answer path would be the
one-writer-per-table rule broken from the inside.

**It does not retry, upsert or ignore a duplicate.** A second record for a request is a
defect in the caller, not a race to absorb: the primary key refuses it and this turns
that refusal into a typed error at the adapter boundary, which is where the spine allows
exceptions to live.
"""

from __future__ import annotations

import sqlite3

from askai.ports.record import RecordRow

__all__ = ["DuplicateRecord", "RecordWriteError", "SqliteRecordStore"]

#: One statement, every column the record table declares. Written out rather than
#: generated from the row, so a column added to the schema is a visible change here
#: rather than a silently absent value.
_INSERT = """
INSERT INTO record (
    record_id, recorded_at, caller_id, identity_asserted, language, question,
    spec_version, spec_json, answer_json, data_as_of, conversation_id, turn
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class RecordWriteError(RuntimeError):
    """The record could not be stored."""


class DuplicateRecord(RecordWriteError):
    """A record with this id is already stored -- one answer, one record (AD-16)."""


class SqliteRecordStore:
    """``RecordPort`` over the record store connection provisioned at startup."""

    __slots__ = ("_connection",)

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def write(self, row: RecordRow) -> None:
        """Insert *row* in its own transaction, committed before the call returns.

        The record is the answer's audit trail, so it is durable at the point the
        request is answered rather than at whatever later moment something else commits.
        """
        try:
            with self._connection:
                self._connection.execute(
                    _INSERT,
                    (
                        row.record_id,
                        row.recorded_at,
                        row.caller_id,
                        int(row.identity_asserted),
                        row.language,
                        row.question,
                        row.spec_version,
                        row.spec_json,
                        row.answer_json,
                        row.data_as_of,
                        row.conversation_id,
                        row.turn,
                    ),
                )
        except sqlite3.IntegrityError as error:
            # A constraint failure is either "this request already has a record" or
            # "this row is not a record at all" -- a language outside the closed set,
            # an identity flag that is neither asserted nor not. Collapsing the two
            # would report a malformed row as a duplicate and send whoever reads the
            # error looking for a write that never happened.
            message = str(error).lower()
            if "unique" in message or "primary key" in message:
                raise DuplicateRecord(
                    f"a record with id {row.record_id!r} is already stored: {error}"
                ) from error
            raise RecordWriteError(
                f"the record for {row.record_id!r} violates the record store's "
                f"constraints: {error}"
            ) from error
