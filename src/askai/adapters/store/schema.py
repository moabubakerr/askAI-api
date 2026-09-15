"""The record store's tables -- one answer record per request, and conversation turns.

Purity: IO.

The second of AD-20's three files. It is separate from the read model because it is the
one live *writer* on the answer path: a refresh rewriting the read model and an answer
being recorded must never contend for the same single-writer lock.

The third file, the semantic index build target, declares no tables at all in Epic 1.
That is not an omission -- AD-13 swaps the index by reference, and the collection tables
are created by the story that fills them (Epic 2's `names`, Epic 6's article content).
The file is still provisioned here so the swap has a target and so "three distinct
database files" is true from the first run rather than from whenever Epic 2 lands.

Both tables are owned by ``askai.adapters.store``; nothing else writes them.
"""

from __future__ import annotations

from typing import Final

from askai.adapters.store.database import DatabaseSchema, Table

__all__ = ["CONVERSATION_TURN", "OWNER", "RECORD", "RECORD_STORE", "SEMANTIC_INDEX"]

#: The one module AD-20 permits to write these tables.
OWNER: Final = "askai.adapters.store"

RECORD: Final = Table(
    name="record",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS record (
        record_id               TEXT    NOT NULL PRIMARY KEY,
        recorded_at             TEXT    NOT NULL,
        -- The engine authenticates nobody (AD-24). It records the identity the
        -- platform asserted, and when none was asserted it records *that* -- which is
        -- why the flag exists beside the nullable id rather than a NULL standing in
        -- for both "anonymous" and "we forgot to look".
        caller_id               TEXT,
        identity_asserted       INTEGER NOT NULL CHECK (identity_asserted IN (0, 1)),
        language                TEXT    NOT NULL CHECK (language IN ('en', 'ar')),
        question                TEXT    NOT NULL,
        -- The spec as served, with the version it was serialised at, so a record
        -- written against an older shape is readable as that shape instead of being
        -- reinterpreted by whatever the current build expects.
        spec_version            INTEGER NOT NULL,
        spec_json               TEXT    NOT NULL,
        answer_json             TEXT    NOT NULL,
        -- What the answer was computed from: the read model's freshness at the time.
        -- Without it the record cannot be defended months later, only repeated.
        data_as_of              TEXT,
        conversation_id         TEXT,
        turn                    INTEGER CHECK (turn IS NULL OR turn >= 1)
    ) STRICT
    """,
    indexes=(
        "CREATE INDEX IF NOT EXISTS record_by_time ON record(recorded_at)",
        """
        CREATE INDEX IF NOT EXISTS record_by_conversation
            ON record(conversation_id, turn) WHERE conversation_id IS NOT NULL
        """,
    ),
)

CONVERSATION_TURN: Final = Table(
    name="conversation_turn",
    owner=OWNER,
    ddl="""
    CREATE TABLE IF NOT EXISTS conversation_turn (
        conversation_id         TEXT    NOT NULL,
        -- Turns are numbered, not timestamped, because inheritance from history is
        -- ordered: "and for Bahrain?" binds against the turn before it, and two turns
        -- recorded in the same clock tick would have no order at all.
        turn                    INTEGER NOT NULL CHECK (turn >= 1),
        asked_at                TEXT    NOT NULL,
        question                TEXT    NOT NULL,
        spec_json               TEXT    NOT NULL,
        record_id               TEXT             REFERENCES record(record_id),
        PRIMARY KEY (conversation_id, turn)
    ) STRICT
    """,
)

RECORD_STORE: Final = DatabaseSchema(
    name="record store",
    tables=(RECORD, CONVERSATION_TURN),
)

#: Empty by decision, not by oversight -- see the module docstring.
SEMANTIC_INDEX: Final = DatabaseSchema(name="semantic index", tables=())
