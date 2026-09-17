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
from enum import StrEnum
from pathlib import Path

from askai.adapters.index.generation import load_generation
from askai.adapters.index.location import (
    configured_source,
    generations_dir,
    latest_generation,
)
from askai.adapters.index.resolution import IndexCandidates
from askai.adapters.model.chat import ChatModelClient
from askai.adapters.readmodel.catalogue import (
    ReadModelPresentation,
    ReadModelSources,
    read_model_snapshot,
)
from askai.adapters.readmodel.groups import (
    EitherSource,
    ReadModelCatalogueSources,
    ReadModelGroups,
)
from askai.adapters.readmodel.reachability import SqliteStoreHealth
from askai.adapters.store.provision import Databases
from askai.adapters.store.records import SqliteRecordStore
from askai.api.engine import READ_MODEL_STORE, RECORD_STORE, Engine
from askai.config.database import ConfigError, DatabasePaths
from askai.config.model import ChatModelSettings
from askai.execute.readmodel import ReadModelDatapoints
from askai.messages import load_catalogue
from askai.ports.model import ModelPort
from askai.ports.resolution import CandidatePort
from askai.refresh.freshness import StateFileFreshness
from askai.refresh.state import state_path_for
from askai.rules import rules

__all__ = ["IndexMissing", "IndexPolicy", "candidates_for", "engine_at", "engine_for"]


class IndexPolicy(StrEnum):
    """Whether this deployment must have an index generation to serve at all.

    The *named setting* that replaces a ``None`` nobody chose. Serving with
    ``candidates=None`` was the silent state that let AD-25's whole ladder reach a VM
    unreached: exact published names bound, which is what a smoke test types, and every
    paraphrase — most readers — got ``no-such-indicator``. So the absence of an index is
    now a thing a composition root has to say out loud.

    ``REQUIRED`` is the default and what ``askai.asgi`` passes. It follows the argument
    at ``api/app.py``'s prompt verification: a deployment that cannot produce the
    reviewed prompt does not start and answer, and a deployment that cannot resolve a
    paraphrase should not quietly answer "no such indicator" to most of its readers.
    The failure is at startup, naming the directory, rather than weeks later in a
    question nobody ran.

    ``ABSENT`` keeps an index-less deployment legal, and it is a real decision rather
    than a hedge: Epic 1's path — exact normalised-name lookup alone — is a correct,
    tested answer path, it is what every test that scripts no index exercises, and a
    deployment that has deliberately not built a generation yet (a fresh estate between
    ``provision`` and the first ``refresh``) is a state an operator can be in. What is
    no longer legal is reaching it by accident.
    """

    REQUIRED = "required"
    ABSENT = "absent"


class IndexMissing(ConfigError):
    """This deployment was told to require an index generation and has none.

    A ``ConfigError`` rather than a new kind of failure: from the operator's side it is
    the same class of thing as an unset ``ASKAI_DATABASE_DIR`` — a deployment step that
    has not been run — and it is fixed the same way, by running one command.
    """


def candidates_for(
    paths: DatabasePaths,
    policy: IndexPolicy = IndexPolicy.REQUIRED,
    environ: Mapping[str, str] | None = None,
) -> CandidatePort | None:
    """AD-25's candidate port over this estate's published generation.

    Loaded once, here, at startup: a generation read per request would put a file open
    on the answer path and would let the same question resolve differently depending on
    what a concurrent refresh had published, which is AD-13's "a request can never
    observe a mixture" given away for nothing.

    Every way this can fail, fails here. A generation built by another vector source, a
    truncated embedding, a file of another schema version — ``load_generation`` refuses
    all of them, and it refuses them at startup rather than at the first question.
    """
    if policy is IndexPolicy.ABSENT:
        return None
    directory = generations_dir(paths)
    path = latest_generation(directory)
    if path is None:
        raise IndexMissing(
            f"no index generation in {directory}, and this deployment requires one. "
            "Without it only an exactly typed published name can bind, and every "
            "paraphrase is refused as no such indicator. Build one with "
            "`python -m askai.refresh <export> --index-only`, which a plain "
            "`python -m askai.refresh <export>` also does; an index-less deployment is "
            "legal only where a "
            f"composition root names {IndexPolicy.ABSENT.value!r}."
        )
    return IndexCandidates.over(load_generation(path, configured_source(environ)))


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
    candidates: CandidatePort | None = None,
) -> Engine:
    """The engine over already-provisioned databases and the refresh state at *state_path*.

    The message catalogue, the rule set and the name snapshot are read here, once per
    process. A snapshot rebuilt per request would make the same question bind differently
    depending on what a concurrent refresh had committed -- AD-17's determinism lost to a
    convenience -- and a catalogue loaded per request would read two files per answer.

    ``now`` is threaded through rather than read inside the engine so that a test states
    the moment it means; ``today`` is an input to compiling (AD-17), and a clock read
    deeper down would make every staleness assertion a race.

    *candidates* is AD-25's ladder, and it is an argument rather than something built
    here because this constructor takes already-opened databases and knows nothing about
    where generations live. ``engine_at`` is the form that knows, and it is the form a
    deployment uses; ``None`` here is Epic 1's exact-name path, which is what the tests
    that pass no index mean and get.
    """
    return Engine(
        messages=load_catalogue(),
        rule_set=rules(),
        names=read_model_snapshot(databases.read_model),
        datapoints=ReadModelDatapoints(databases.read_model),
        presentation=ReadModelPresentation(connection=databases.read_model),
        # Both reference shapes, because an answer carries both. A datapoint element
        # names `detail|period|country|source` and a catalogue element -- a quoted
        # definition, a group's count, a capability statement -- names
        # `catalogue|kind|key`. Wired with the datapoint resolver alone, every
        # catalogue element failed admission, every element of a definition answer was
        # refused, and the empty result was reported as `data-could-not-be-reached`:
        # the one refusal that means *a fault in the engine* spent on a composer that
        # had worked. AD-7's closed world has to cover what the composers actually
        # build, or it rejects the engine's own output.
        sources=EitherSource(
            datapoints=ReadModelSources(connection=databases.read_model),
            catalogue=ReadModelCatalogueSources(connection=databases.read_model),
        ),
        groups=ReadModelGroups(connection=databases.read_model),
        candidates=candidates,
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
    databases: Databases,
    paths: DatabasePaths,
    now: Callable[[], datetime] = _utc_now,
    index: IndexPolicy = IndexPolicy.REQUIRED,
) -> Engine:
    """The engine for an estate: state file and index generation located from *paths*.

    The short form exists so nobody has to remember where the estate's other two things
    live. The state file is beside the read model it describes and ``state_path_for`` is
    the one place that says so; the index generation is in a directory beside them and
    ``generations_dir`` is the one place that says that. A deployment wiring either of
    them separately would be describing some other deployment's data.

    *index* defaults to ``REQUIRED``, so the failure this session was called in to fix —
    a server that starts, answers exact names, and refuses every paraphrase — is not
    reachable by omission any more.
    """
    return engine_for(
        databases,
        state_path_for(paths),
        now,
        candidates=candidates_for(paths, index),
    )
