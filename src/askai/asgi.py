"""The ASGI entry point: ``uvicorn askai.asgi:build --factory``.

Purity: composition root; imports every layer and belongs to none.

``api/app.py`` deliberately exposes ``create_app(engine)`` and no module-level ``app``,
so a test drives the real routes over a real provisioned database with no environment
variable set and no process-wide state to reset between cases. That decision is right and
it leaves one gap: a server needs *something* importable to serve.

This module is that something, and nothing else. It is the composition root for the
server process — it reads the typed settings, opens the already-provisioned estate, builds
the engine and hands it to ``create_app``. It is the only place in the tree where those
steps happen at import time, which is why it is a module of its own rather than a few
lines at the bottom of ``app.py``.

**It sits above ``api/`` rather than inside it, and that is load-bearing.** Building
the engine means reaching the refresh state, and ``tests/test_refresh.py`` scans
everything reachable from ``api/`` *transitively* for the refresh mechanism: AD-21
makes refresh a scheduled command and never reader-reachable, because a route that
could reach it is a route that could change the data under another reader's question.
A composition root inside ``api/`` puts that machinery one import away from a handler.
Here, the wiring is above the edge and the edge stays unable to reach it.

**The databases must already exist.** ``open_databases`` opens and refuses to create, so a
process pointed at an unprovisioned directory fails here, at startup, naming the file —
rather than serving a 500 on the first question. Provision first::

    python -m askai.adapters.store provision
    python -m askai.refresh /data
    uvicorn askai.asgi:build --factory --host 0.0.0.0 --port 8000

**The connections live as long as the process.** They are opened here and never closed,
because the process holding them *is* the server: a shutdown hook that closed them would
run after the last request either way, and SQLite releases them on exit. The refresh is a
separate process against the same files, which is what WAL is for and what the preflight
proves works on the target filesystem.
"""

from __future__ import annotations

from fastapi import FastAPI

from askai.adapters.readmodel.startup import engine_at
from askai.adapters.store.provision import open_databases
from askai.api.app import create_app
from askai.config.database import DatabasePaths

__all__ = ["build"]


def build() -> FastAPI:
    """Read the settings, open the estate, and build the app around the engine.

    A factory rather than a module-level ``app``, because building at import time makes
    importing this module require a provisioned estate — and the tree-wide invariant scans
    import every module under ``askai`` to check them. ``--factory`` keeps the failure
    where it belongs: at server start, naming the missing setting, rather than at the
    first reader's question or in an unrelated test run.
    """
    paths = DatabasePaths.from_env()
    databases = open_databases(paths).__enter__()
    return create_app(engine_at(databases, paths))


