"""The composition root: concrete adapters chosen once, and handed to the engine.

Purity: IO.

Somewhere has to pick the implementations. Every layer below takes ports and values, and
nothing anywhere reaches for a collaborator; that discipline is only worth something if
exactly one module does the picking, in the open, where the whole graph is one function
long. This is that module.

**It is deliberately not part of ``api/``.** AD-21 makes refresh an out-of-band job that
**no route may reach**, and ``tests/test_refresh.py`` asserts it as a reachability scan
over everything ``api/`` imports, transitively. The freshness producer lives in
``refresh/`` -- which is why ``FreshnessPort`` and the ``Freshness`` block are declared in
``ports/`` in the first place, so health and every answer can carry the block without the
answer path importing the job. A composition root inside ``api/`` would import
``refresh/`` for one constructor call and put the whole refresh mechanism back inside the
request's import graph, which is the thing the scan exists to catch. So the wiring sits
here, beside the read-model adapters it assembles, and the engine receives a
``FreshnessPort`` it cannot trace back to a job.

**Story 1.9 left this on purpose.** The state file lives beside the databases;
``state_path_for`` derives its path from the same ``DatabasePaths`` the databases were
opened from, so ``GET /api/health`` and every answer package report the freshness of the
file that actually feeds them rather than of one somebody configured separately.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from askai.adapters.model.chat import ChatModelClient
from askai.adapters.readmodel.catalogue import (
    ReadModelPresentation,
    ReadModelSources,
    read_model_snapshot,
)
from askai.adapters.readmodel.groups import ReadModelGroups
from askai.adapters.readmodel.reachability import SqliteStoreHealth
from askai.adapters.store.provision import Databases
from askai.adapters.store.records import SqliteRecordStore
from askai.api.engine import READ_MODEL_STORE, RECORD_STORE, Engine
from askai.config.database import ConfigError, DatabasePaths
from askai.config.model import ChatModelSettings
from askai.execute.readmodel import ReadModelDatapoints
from askai.messages import load_catalogue
from askai.ports.model import ModelPort
from askai.refresh.freshness import StateFileFreshness
from askai.refresh.state import state_path_for
from askai.rules import rules

__all__ = ["engine_at", "engine_for"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def chat_model(environ: Mapping[str, str] | None = None) -> ModelPort | None:
    """The chat runtime, or ``None`` when this deployment was not told about one.

    The settings are required with no default, because a process that guessed a model
    endpoint would start, answer, and be wrong. But the *port* is optional, because
    NFR-6 makes "no model reachable" the state the whole answer path must work in — so
    an unconfigured process boots, answers, and simply never reaches the tie-break rung
    (AD-22) rather than failing to start.

    Those two rules only look contradictory. "No default endpoint" and "no endpoint at
    all" are different states: the first would answer against a runtime nobody meant,
    the second answers without one and records that it did.
    """
    try:
        settings = ChatModelSettings.from_env(environ)
    except ConfigError:
        return None
    return ChatModelClient(settings)


def engine_for(
    databases: Databases,
    state_path: Path,
    now: Callable[[], datetime] = _utc_now,
) -> Engine:
    """The engine over already-provisioned databases and the refresh state at *state_path*.

    The message catalogue, the rule set and the name snapshot are read here, once per
    process. A snapshot rebuilt per request would make the same question bind differently
    depending on what a concurrent refresh had committed -- AD-17's determinism lost to a
    convenience -- and a catalogue loaded per request would read two files per answer.

    ``now`` is threaded through rather than read inside the engine so that a test states
    the moment it means; ``today`` is an input to compiling (AD-17), and a clock read
    deeper down would make every staleness assertion a race.
    """
    return Engine(
        messages=load_catalogue(),
        rule_set=rules(),
        names=read_model_snapshot(databases.read_model),
        datapoints=ReadModelDatapoints(databases.read_model),
        presentation=ReadModelPresentation(connection=databases.read_model),
        sources=ReadModelSources(connection=databases.read_model),
        groups=ReadModelGroups(connection=databases.read_model),
        model=chat_model(),
        freshness=StateFileFreshness(path=state_path),
        records=SqliteRecordStore(databases.record_store),
        stores=(
            SqliteStoreHealth(name=READ_MODEL_STORE, connection=databases.read_model),
            SqliteStoreHealth(name=RECORD_STORE, connection=databases.record_store),
        ),
        now=now,
    )


def engine_at(
    databases: Databases, paths: DatabasePaths, now: Callable[[], datetime] = _utc_now
) -> Engine:
    """The engine for an estate, with the state file located from the estate's own paths.

    The two-argument form exists so nobody has to remember where the state file goes: it
    is beside the read model it describes, and ``state_path_for`` is the one place that
    says so.
    """
    return engine_for(databases, state_path_for(paths), now)
