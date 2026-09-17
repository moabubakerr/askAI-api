"""Session M: AD-25's ladder is reachable from a deployment, or the deployment refuses.

The ladder was built by Sessions A and J and executed nowhere. ``engine_for`` never
passed ``candidates``, ``api/engine.py`` defaulted it to ``None``, and
``compile/binder.py:_resolve`` returned on its first line -- so only exact
normalised-name lookup ever ran, on every deployment including the VM. Exact published
names bound, which is what a smoke test types, and every paraphrase was refused as *no
such indicator*.

The tests here are about the join, not about retrieval quality. Retrieval is measured by
``python -m askai.adapters.index`` and by ``tests/test_retrieval_quality.py``; what is
asserted below is that a deployment has a generation, that a refresh publishes one, that
the engine is handed a port over it, and that a deployment which cannot do those things
says so at startup instead of answering badly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.index.build import GENERATION_PREFIX, GENERATION_SUFFIX
from askai.adapters.index.generation import IndexLoadError, load_generation
from askai.adapters.index.location import (
    GENERATIONS_DIRNAME,
    configured_source,
    generations_dir,
    latest_generation,
    published_generations,
)
from askai.adapters.index.publication import publish_generation
from askai.adapters.index.resolution import IndexCandidates
from askai.adapters.index.vectors import TrigramVectorSource
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.readmodel.startup import (
    IndexMissing,
    IndexPolicy,
    candidates_for,
    engine_at,
    engine_for,
)
from askai.adapters.store.provision import Databases, provision
from askai.compile.binder import CompileInput, compile_question
from askai.config.database import DatabasePaths
from askai.ports.index import Collection
from askai.refresh.indexing import rebuild_index

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: The moment these tests compile at. Fixed, because ``today`` is an input to compiling.
MOMENT: Final = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
TODAY: Final = date(2026, 9, 30)

#: A subject no published name spells, so the exact rung cannot bind it and only the
#: ladder can reach anything at all. What it resolves *to* is a quality question and is
#: measured elsewhere; that it is considered is this file's business.
PARAPHRASE: Final = "how fast are prices rising"


@pytest.fixture(scope="module")
def source() -> TrigramVectorSource:
    """The shipped vector source. No runtime, no weights, nothing to reach (NFR-6)."""
    return TrigramVectorSource()


@pytest.fixture(scope="module")
def export() -> CmsExport:
    return CmsExport.rooted(EXPORT_ROOT)


@pytest.fixture(scope="module")
def estate(tmp_path_factory: pytest.TempPathFactory) -> DatabasePaths:
    return DatabasePaths.beneath(tmp_path_factory.mktemp("estate"))


@pytest.fixture(scope="module")
def generation(
    estate: DatabasePaths, export: CmsExport, source: TrigramVectorSource
) -> Path:
    """One published generation for the estate, built the way a deployment builds it."""
    return publish_generation(export, source, generations_dir(estate)).path


# ------------------------------------------------------- where a generation lives


def test_generations_live_in_one_place_beside_the_databases(estate: DatabasePaths) -> None:
    directory = generations_dir(estate)
    assert directory.parent == estate.read_model.parent
    assert directory.name == GENERATIONS_DIRNAME
    # Not the store-shaped build target of AD-20: that is a provisioned database, and a
    # generation is a file published by rename into a directory.
    assert directory != estate.semantic_index


def test_a_published_generation_is_the_one_a_deployment_finds(
    generation: Path, estate: DatabasePaths
) -> None:
    directory = generations_dir(estate)
    assert generation.name.startswith(GENERATION_PREFIX)
    assert generation.suffix == GENERATION_SUFFIX
    assert latest_generation(directory) == generation


def test_a_generation_holds_the_export_it_was_built_from(
    generation: Path, source: TrigramVectorSource
) -> None:
    loaded = load_generation(generation, source)
    assert loaded.size(Collection.NAMES) > 0
    assert loaded.source_identity == source.identity


def test_an_estate_with_no_generation_has_none(tmp_path: Path) -> None:
    assert published_generations(tmp_path / GENERATIONS_DIRNAME) == ()
    assert latest_generation(tmp_path / GENERATIONS_DIRNAME) is None


# ------------------------------------------------------------------ publication


def test_publishing_retires_the_generation_it_supersedes(
    tmp_path: Path, export: CmsExport, source: TrigramVectorSource
) -> None:
    first = publish_generation(export, source, tmp_path)
    second = publish_generation(export, source, tmp_path)

    assert second.retired == (first.path,)
    assert not first.path.exists()
    assert published_generations(tmp_path) == (second.path,)


@dataclass(frozen=True, slots=True)
class _WrongWidth:
    """A source that vectorises to a width it does not declare. Fails the build."""

    identity: str = "wrong-width"
    dimensions: int = 8

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        return (1.0,) * (self.dimensions + 1)


def test_a_failed_build_leaves_the_generation_in_force_untouched(
    tmp_path: Path, export: CmsExport, source: TrigramVectorSource
) -> None:
    """Built, then loaded, then retired -- so one bad build is not an estate with no index."""
    good = publish_generation(export, source, tmp_path)

    with pytest.raises(RuntimeError):
        publish_generation(export, _WrongWidth(), tmp_path)

    assert good.path.exists()
    assert latest_generation(tmp_path) == good.path
    # And no working file was left behind under any name.
    assert [path.name for path in tmp_path.iterdir()] == [good.path.name]


def test_a_generation_refuses_a_source_that_did_not_build_it(
    generation: Path, source: TrigramVectorSource
) -> None:
    """The reason the trigram fallback in ``configured_source`` is safe."""
    other = TrigramVectorSource(dimensions=source.dimensions + 1)
    with pytest.raises(IndexLoadError):
        load_generation(generation, other)


# ---------------------------------------------------------- the composition root


def test_a_deployment_that_requires_an_index_and_has_none_refuses_to_start(
    tmp_path: Path,
) -> None:
    paths = DatabasePaths.beneath(tmp_path)
    with pytest.raises(IndexMissing) as raised:
        candidates_for(paths)
    message = str(raised.value)
    assert GENERATIONS_DIRNAME in message
    assert "python -m askai.refresh" in message


def test_an_index_less_deployment_is_legal_only_when_it_is_named(
    estate: DatabasePaths, generation: Path
) -> None:
    assert candidates_for(estate, IndexPolicy.ABSENT) is None


def test_the_port_is_built_over_the_published_generation(
    estate: DatabasePaths, generation: Path
) -> None:
    port = candidates_for(estate, environ={})
    assert isinstance(port, IndexCandidates)
    assert port.candidates(PARAPHRASE)


def test_engine_at_hands_the_engine_the_ladder(
    estate: DatabasePaths, generation: Path, export: CmsExport
) -> None:
    """The wiring the whole session is about: ``engine_at`` passes ``candidates=``."""
    with _databases(estate, export) as databases:
        engine = engine_at(databases, paths=estate, now=lambda: MOMENT)
        assert engine.candidates is not None

        absent = engine_at(
            databases, paths=estate, now=lambda: MOMENT, index=IndexPolicy.ABSENT
        )
        assert absent.candidates is None


def test_engine_for_still_defaults_to_epic_ones_path(
    estate: DatabasePaths, export: CmsExport
) -> None:
    """Every existing caller keeps the behaviour it had; nothing binds differently by surprise."""
    with _databases(estate, export) as databases:
        engine = engine_for(databases, estate.read_model.parent / "state.json")
        assert engine.candidates is None


# ------------------------------------------------------------ what the wiring buys


def test_a_paraphrase_reaches_the_ladder_only_when_the_port_is_wired(
    estate: DatabasePaths, generation: Path, export: CmsExport
) -> None:
    """The measured finding, as a test: without ``candidates`` nothing but exact names runs."""
    port = candidates_for(estate)
    with _databases(estate, export) as databases:
        catalogue = engine_for(databases, estate.read_model.parent / "state.json").names

    unwired = compile_question(CompileInput(question=PARAPHRASE, today=TODAY), catalogue)
    assert unwired.resolution is None

    # Wired, the ladder runs and decides. *What* it decides with the shipped trigram
    # source is a retrieval-quality question measured by the harness, not a wiring one:
    # the claim here is that the rung executes at all, which on every deployment
    # including the VM it did not.
    wired = compile_question(
        CompileInput(question=PARAPHRASE, today=TODAY), catalogue, port
    )
    assert wired.resolution is not None


def test_an_exactly_typed_name_skips_the_ladder_even_when_it_is_shared(
    estate: DatabasePaths, generation: Path, export: CmsExport
) -> None:
    """Where the UUID leak actually lives, measured with the ladder wired.

    Session M's brief expected wiring the ladder to fix the three UUIDs a reader sees for
    *Number of Jobs in the Sector*: ``narrate/structured.py`` prefers
    ``Disambiguation.candidates`` and falls back to the ``Unbound`` particulars, which
    ``compile/binder.py`` builds out of detail ids. It does not, and this is why.

    ``_resolve`` skips the ladder whenever any span names published details exactly --
    including when it names *several*, which is exactly the shared-name case. So the
    resolution is ``None`` for this question however well the index is wired, and the
    particulars are still all ``narrate/`` has. The leak is real and its cause is one
    condition in ``compile/binder.py`` outside this session's files; it is recorded here
    rather than silently left, so the next session starts from the measurement.
    """
    port = candidates_for(estate)
    with _databases(estate, export) as databases:
        catalogue = engine_for(databases, estate.read_model.parent / "state.json").names

    shared = compile_question(
        CompileInput(question="number of jobs in the sector", today=TODAY), catalogue, port
    )
    assert shared.resolution is None

    # And the deliberate half of the same rule: a uniquely published name binds on the
    # cheapest rung and pays for no search.
    exact = compile_question(CompileInput(question="inflation", today=TODAY), catalogue, port)
    assert exact.resolution is None


# ----------------------------------------------------------------- refresh's half


def test_a_refresh_publishes_the_generation_it_just_reloaded(
    tmp_path: Path, export: CmsExport, source: TrigramVectorSource
) -> None:
    paths = DatabasePaths.beneath(tmp_path)
    rebuilt = rebuild_index(paths, export, source)

    assert rebuilt.succeeded, rebuilt.failure
    assert rebuilt.published is not None
    assert latest_generation(generations_dir(paths)) == rebuilt.published.path
    assert "published" in rebuilt.summary()


def test_a_refresh_reports_an_index_it_could_not_build_rather_than_raising(
    tmp_path: Path, export: CmsExport
) -> None:
    """The read model is already committed by then; a report and an exit code, not a traceback."""
    rebuilt = rebuild_index(DatabasePaths.beneath(tmp_path), export, _WrongWidth())

    assert not rebuilt.succeeded
    assert rebuilt.published is None
    assert "NOT rebuilt" in rebuilt.summary()


def test_the_configured_source_needs_no_runtime(source: TrigramVectorSource) -> None:
    """Off the VM nothing is set, and the shipped source is what builds and loads."""
    assert configured_source(environ={}).identity == source.identity


def _databases(paths: DatabasePaths, export: CmsExport) -> _Estate:
    return _Estate(paths, export)


class _Estate:
    """The three databases at *paths*, provisioned once and loaded from *export*."""

    def __init__(self, paths: DatabasePaths, export: CmsExport) -> None:
        self._paths = paths
        self._export = export
        self._databases: Databases | None = None

    def __enter__(self) -> Databases:
        databases = provision(self._paths)
        if not _already_loaded(databases):
            ingest_published_layer(databases.read_model, self._export)
        self._databases = databases
        return databases

    def __exit__(self, *_: object) -> None:
        if self._databases is not None:
            self._databases.close()


def _already_loaded(databases: Databases) -> bool:
    row = databases.read_model.execute("SELECT count(*) FROM detail").fetchone()
    return bool(row is not None and row[0])
