"""Is this sqlite store there? The cheapest question, asked at the health boundary.

Purity: IO.

AD-21 puts store reachability and read-model freshness side by side on ``GET
/api/health``, and the two must stay separable: a store that cannot be opened and a copy
that is a week old are different incidents with different people to call.

The question asked is ``SELECT 1``. Not a count, not a table read: a count grows with the
data and would turn the health check into the slowest request the service serves, and a
table read would report a store *reachable* only while the schema also happened to match
-- which is the schema step's job, done once at startup, and already loud when it fails.

This is an adapter, which is the one place AD-15 permits a broad handler, and it uses
one. A health check that raises is a health check that cannot report, so every failure a
driver can produce is converted here into the value the port declares.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from askai.ports.store_health import StoreHealth

__all__ = ["SqliteStoreHealth"]

_PING = "SELECT 1"


@dataclass(frozen=True, slots=True)
class SqliteStoreHealth:
    """``StoreHealthPort`` over one already-opened sqlite connection."""

    name: str
    connection: sqlite3.Connection

    def health(self) -> StoreHealth:
        try:
            answered = self.connection.execute(_PING).fetchone()
        # The broad handler AD-15 permits at an adapter boundary, and only there: the
        # point of a health check is that nothing it touches can stop it reporting.
        except Exception as error:
            return StoreHealth(
                name=self.name,
                reachable=False,
                detail=f"{type(error).__name__}: {error}",
            )
        if answered is None:  # pragma: no cover -- SELECT 1 always returns a row
            return StoreHealth(
                name=self.name, reachable=False, detail=f"{_PING} returned no row"
            )
        return StoreHealth(name=self.name, reachable=True)
