"""``CommentaryPort`` over the local read model. Reads only; writes nothing, ever.

Purity: IO.

The fetch behind an ``attributed`` element. It is the same shape as the datapoint fetch
and for the same reasons: one statement, the complete ``(detail, period, country)`` key,
``IS NULL`` for the national scope, and ``sqlite3.Error`` caught by name at the boundary
so a store that stopped answering arrives as a typed failure rather than as "no
commentary is published" (AD-15).

**It reads.** Every statement here is a ``SELECT``. AD-20 gives ``analysis`` one owning
writer -- the ingest -- and a fetch that wrote it would be the second.

**It does not search.** There is no ordering, no scoring and no nearest-period fallback,
because a note explains the row it was written about: attributing an analyst's paragraph
about March to April's figure would be the engine putting words in a named person's
mouth. Finding *which* passage is relevant across the corpus is a semantic question asked
of the index file, in Epic 6, and it is a different question from this one.

**A miss is the ordinary answer.** 1,031 of 8,127 datapoints carry commentary, so nine
calls in ten return ``None``. That is the published state of the data and it is not an
error, which is why nothing here raises on an empty result.
"""

from __future__ import annotations

import sqlite3

from askai.domain.period import Period
from askai.ports.commentary import Commentary, CommentaryUnavailable

__all__ = ["ReadModelCommentary"]

_SQL: str = """
    SELECT source_datapoint_id, summary_en, summary_ar, detailed_en, detailed_ar
    FROM analysis
    WHERE detail_id = ? AND period = ? AND {scope}
"""


class ReadModelCommentary:
    """The published analyst notes, as an answer is allowed to see them.

    Holds the connection the caller opened and sets no connection policy of its own --
    WAL and the schema version are set and verified once by the schema step.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def note(
        self, detail_id: str, period: Period, country_id: str | None
    ) -> Commentary | None:
        """The note at this exact key, or ``None`` when none is published."""
        scope, parameters = _scope(country_id)
        sql = _SQL.format(scope=scope)
        try:
            found = self._connection.execute(
                sql, (detail_id, period.value, *parameters)
            ).fetchone()
        except sqlite3.Error as error:
            raise CommentaryUnavailable(
                f"the read model refused {sql!r}: {error}"
            ) from error
        if found is None:
            return None
        source_datapoint_id, summary_en, summary_ar, detailed_en, detailed_ar = found
        return Commentary(
            detail_id=detail_id,
            period=period,
            country_id=country_id,
            source_datapoint_id=str(source_datapoint_id),
            summary=(_text(summary_en), _text(summary_ar)),
            detailed=(_text(detailed_en), _text(detailed_ar)),
        )


def _scope(country_id: str | None) -> tuple[str, tuple[str, ...]]:
    """The country half of the key, as SQL.

    ``IS NULL`` rather than ``= ?`` for the national rows: two NULLs do not compare equal
    in SQL, so the parameterised form would select nothing and every national answer
    would silently lose its commentary while the query looked entirely correct (AD-5).
    """
    if country_id is None:
        return "country_id IS NULL", ()
    return "country_id = ?", (country_id,)


def _text(value: object) -> str | None:
    """A stored prose cell, or ``None``. Decoded at ingest; nothing is decoded here."""
    return None if value is None else str(value)
