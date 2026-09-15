"""The one recorder: one request, one record, written after the package is final.

Purity: IO at the edge -- it builds a value and calls a port, and knows no SQL.

AD-16's "exactly one record per request" is enforced by the object's lifetime rather
than by a rule anyone has to remember. A ``Recorder`` is made for one request and is
spent by the write: a second call raises, naming the record already written. There is no
``update``, no ``flush`` and no ``close``, so there is no shape in which a record gets
finished later or in two parts -- the partial-record failure the decision exists to
prevent.

"After the package is final" is structural too, in the only way it can be: the recorder
takes a finished ``AnswerRecord``, which is frozen and complete by construction, and the
port it hands it to accepts nothing else. A caller holding a half-built answer has
nothing to pass.
"""

from __future__ import annotations

from askai.observability.record import AnswerRecord, RecordError, to_row
from askai.ports.record import RecordPort, RecordRow

__all__ = ["RecordAlreadyWritten", "Recorder"]


class RecordAlreadyWritten(RecordError):
    """A second record was offered for a request that already has one."""


class Recorder:
    """Writes one record, once. Construct it per request, not per process."""

    __slots__ = ("_port", "_written")

    def __init__(self, port: RecordPort) -> None:
        self._port = port
        # Instance state, deliberately: a module-level set would be the ambient
        # collector AD-15 forbids, shared between concurrent requests, and would make
        # this untestable in isolation.
        self._written: str | None = None

    @property
    def written(self) -> str | None:
        """The id of the record this recorder wrote, or ``None`` while it is unspent."""
        return self._written

    def record(self, record: AnswerRecord) -> RecordRow:
        """Bound *record*, write it through the port, and return the row as written.

        The row is returned rather than discarded because it is what the audit holds:
        a caller that wants to log or assert on what was stored reads the same value
        the store received, not a second rendering of it.
        """
        if self._written is not None:
            raise RecordAlreadyWritten(
                f"this recorder already wrote {self._written}; AD-16 allows exactly one "
                "record per request, written once from the finished package"
            )
        row = to_row(record)
        self._port.write(row)
        self._written = row.record_id
        return row
