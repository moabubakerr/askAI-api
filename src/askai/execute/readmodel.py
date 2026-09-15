"""``DatapointsPort`` over the local read model. Reads only; writes nothing, ever.

Purity: IO, via ports only.

AD-9a: the engine answers from its own copy of the published layer, so the answer path
opens no socket -- this is the whole of what an answer touches, a local sqlite file the
refresh built out of band.

Three properties are structural rather than careful:

**It reads.** Every statement here is a ``SELECT``. AD-20 gives every table exactly one
owning module and ``datapoint`` belongs to the ingest; a fetch that wrote it would be the
second writer, and ``tests/test_execute.py`` asserts no INSERT, UPDATE or DELETE exists in
this package.

**The national marker stays absent.** A national row carries no country, so it is
selected with ``country_id IS NULL`` and never with a name or a code. The home country
appears in none of the 8,127 published rows, so the alternative would match nothing while
looking entirely correct (AD-5, FR-10).

**A period is parsed, not trusted.** The stored spelling becomes a ``Period``, which owns
its grain -- so nothing downstream reads a grain off a column, because there is no grain
column to read.

It lives here rather than under ``adapters/`` because ``execute/`` is the layer the spine
makes responsible for IO on the answer path, and because the port it implements has no
other implementation to share. If the estate later grows a read-model adapter package for
the answer path, this moves there unchanged -- everything above it depends on
``DatapointsPort``, never on this class.
"""

from __future__ import annotations

import sqlite3

from askai.domain.period import Period, PeriodFormatError
from askai.ports.datapoints import DatapointRow, DatapointsUnavailable

__all__ = ["ReadModelDatapoints", "UnreadablePeriod"]


class UnreadablePeriod(DatapointsUnavailable):
    """The read model holds a period spelling the engine cannot classify.

    Raised rather than skipped. The ingest refuses such a row, and the table's own CHECK
    refuses it again, so reaching this means the file was written by something else --
    and silently dropping the row would answer "latest" from a series with a hole in it.

    A subclass of the port's own failure, so the layer above catches one named thing.
    """


class ReadModelDatapoints:
    """The published datapoints, as the fetch is allowed to see them.

    Holds the connection the caller opened; it sets no connection policy of its own --
    WAL and the schema version are set and verified once by the schema step.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def publishes(self, detail_id: str) -> bool:
        """Does this detail have any published row at all? (28 of 289 do not.)"""
        sql = "SELECT EXISTS (SELECT 1 FROM datapoint WHERE detail_id = ?)"
        found = self._first(sql, (detail_id,))
        if found is None:  # pragma: no cover -- EXISTS always returns a row
            raise DatapointsUnavailable(f"{sql!r} returned no row")
        return bool(found[0])

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        """The series' calendar in this scope. No value column is selected at all."""
        scope, parameters = _scope(country_id)
        sql = f"SELECT period FROM datapoint WHERE detail_id = ? AND {scope} ORDER BY period"
        return tuple(
            _period(str(value), detail_id) for (value,) in self._all(sql, (detail_id, *parameters))
        )

    def row(self, detail_id: str, period: Period, country_id: str | None) -> DatapointRow | None:
        """The one row at this exact key, or ``None``. The complete key, every time."""
        scope, parameters = _scope(country_id)
        sql = (
            "SELECT source_datapoint_id, actual, target, baseline FROM datapoint "
            f"WHERE detail_id = ? AND period = ? AND {scope}"
        )
        found = self._first(sql, (detail_id, period.value, *parameters))
        if found is None:
            return None
        source_datapoint_id, actual, target, baseline = found
        return DatapointRow(
            detail_id=detail_id,
            period=period,
            country_id=country_id,
            source_datapoint_id=str(source_datapoint_id),
            actual=_text(actual),
            target=_text(target),
            baseline=_text(baseline),
        )

    def _all(self, sql: str, parameters: tuple[object, ...]) -> tuple[tuple[object, ...], ...]:
        """Run *sql*, converting the driver's failure into the port's own.

        The one place a foreign error is turned into a value the layer above can act on:
        ``sqlite3.Error`` is caught by name rather than by ``except Exception``, because
        a broad handler here is how a store that stopped answering becomes a detail that
        publishes nothing (AD-15).
        """
        try:
            return tuple(tuple(row) for row in self._connection.execute(sql, parameters))
        except sqlite3.Error as error:
            raise DatapointsUnavailable(
                f"the read model refused {sql!r}: {error}"
            ) from error

    def _first(self, sql: str, parameters: tuple[object, ...]) -> tuple[object, ...] | None:
        found = self._all(sql, parameters)
        return found[0] if found else None


def _scope(country_id: str | None) -> tuple[str, tuple[str, ...]]:
    """The country half of the key, as SQL.

    ``IS NULL`` rather than ``= ?`` for the national rows: in SQL two NULLs do not
    compare equal, so the parameterised form would silently select nothing -- the
    national series disappearing from its own answer, which is AD-5's failure arriving
    through the query language instead of through a name.
    """
    if country_id is None:
        return "country_id IS NULL", ()
    return "country_id = ?", (country_id,)


def _text(value: object) -> str | None:
    """A published cell as text, or ``None``. Values are stored as the published digits."""
    return None if value is None else str(value)


def _period(value: str, detail_id: str) -> Period:
    try:
        return Period(value)
    except PeriodFormatError as error:
        raise UnreadablePeriod(
            f"the read model holds period {value!r} for detail {detail_id}, whose grain "
            "cannot be read; the ingest refuses such a row, so this file was written by "
            "something else"
        ) from error
