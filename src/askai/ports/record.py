"""``RecordPort`` -- the one door the answer record leaves by.

Purity: declaration only.

AD-16 gives ``observability/`` the job of writing exactly one record per request, and
AD-20 gives the ``record`` table exactly one writing module (``askai.adapters.store``).
Those two rules meet here: the recorder builds the record and hands it to this port, and
the store adapter behind the port is the only thing that speaks SQL.

Two properties are deliberate and are asserted by ``tests/test_records.py``:

**The port takes a row that is already flat, already serialised and already bounded.**
The adapter behind it makes no decision about what a record contains or how large it may
grow -- it binds parameters. A port that accepted the rich value would put the size
bound behind an interface anyone could implement differently.

**The port offers ``write`` and nothing else.** There is no ``update``, ``amend``,
``append`` or ``finish``. A record is written once from a finished package (AD-16); an
interface that allowed a second pass would be the "partial records assembled from
several call sites" the decision exists to prevent -- and unlike a convention, a method
that does not exist cannot be called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["RecordPort", "RecordRow"]


@dataclass(frozen=True, slots=True)
class RecordRow:
    """One answer record, flattened to the columns the record store declares.

    Primitives only, on purpose: this is the value that crosses the port, so it carries
    no ``QuerySpec``, no ``Degradation`` and no ``Element``. Everything typed has already
    been serialised by the recorder, which is also where the size bound was applied --
    so what arrives here is final in both senses.
    """

    record_id: str
    recorded_at: str
    caller_id: str | None
    identity_asserted: bool
    language: str
    question: str
    spec_version: int
    spec_json: str
    answer_json: str
    data_as_of: str | None
    conversation_id: str | None
    turn: int | None


@runtime_checkable
class RecordPort(Protocol):
    """Write one finished record. Raises if that record id has already been written."""

    def write(self, row: RecordRow) -> None: ...
