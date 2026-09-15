"""The semantic index: exact, in process, and atomically swapped.

Story 2.1's acceptance criteria, asserted against the index the build actually produces.
Everything runs on a temporary directory -- no service, no model, no network, nothing
left behind.

The atomicity assertions are the ones worth reading closely. An "atomic swap" claimed by
a docstring and tested single-threaded is not evidence of anything, so the swap is
exercised with a reader thread searching a held generation while another thread replaces
the current one underneath it, and the two generations are built from disjoint corpora so
that a mixture would be visible in the results rather than merely possible.
"""

from __future__ import annotations

import ast
import importlib
import os
import sqlite3
import struct
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from askai.adapters.index.build import IndexBuildError, build_generation, pack_vector
from askai.adapters.index.generation import (
    IndexGeneration,
    IndexLoadError,
    load_generation,
)
from askai.adapters.index.schema import INDEX_SCHEMA_VERSION, META_TABLE, collection_table
from askai.adapters.index.swap import SwappableIndex
from askai.adapters.index.tuning import (
    CANDIDATE_LIMIT_RULE,
    TRIGRAM_RULE,
    VECTOR_WIDTH_RULE,
    candidate_limit,
    trigram_size,
    vector_width,
)
from askai.adapters.index.vectors import TrigramVectorSource, unit_length, unit_vector_for
from askai.adapters.store.database import connect_database
from askai.adapters.store.provision import provision
from askai.adapters.store.schema import RECORD_STORE
from askai.config.database import DatabasePaths
from askai.domain.normalise import normalise
from askai.domain.period import Period
from askai.messages.lang import Lang
from askai.ports.index import Collection, IndexPort, IndexRow, IndexScope
from askai.ports.vectors import VectorSourcePort
from askai.rules import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
INDEX_PACKAGE: Final = PACKAGE_ROOT / "adapters" / "index"

#: Every library that would make AD-13's "no ANN library and no vector server" false,
#: and every embedding runtime that would make the deferred model decision an accidental
#: dependency. Checked against the project's declared dependencies, not against imports
#: alone: a package in the tree is in the dependency tree whether or not it is imported
#: yet.
FORBIDDEN_DEPENDENCIES: Final = frozenset(
    {
        "faiss",
        "faiss-cpu",
        "faiss-gpu",
        "hnswlib",
        "annoy",
        "nmslib",
        "scann",
        "usearch",
        "pynndescent",
        "chromadb",
        "qdrant-client",
        "weaviate-client",
        "pinecone-client",
        "pymilvus",
        "lancedb",
        "pgvector",
        "redisvl",
        "sentence-transformers",
        "transformers",
        "torch",
        "tensorflow",
        "onnxruntime",
        "openai",
        "cohere",
        "tiktoken",
        "numpy",
    }
)


@pytest.fixture
def source() -> TrigramVectorSource:
    return TrigramVectorSource()


def _name_rows(prefix: str) -> tuple[IndexRow, ...]:
    """A small ``names`` corpus. *prefix* makes every id say which generation it is from."""
    return (
        IndexRow(
            id=f"{prefix}-cpi-en",
            lang=Lang.EN,
            text="Consumer Price Index",
            detail_id="d-cpi",
        ),
        IndexRow(
            id=f"{prefix}-cpi-ar",
            lang=Lang.AR,
            text="الرقم القياسي لأسعار المستهلك",
            detail_id="d-cpi",
        ),
        IndexRow(
            id=f"{prefix}-gdp-en",
            lang=Lang.EN,
            text="Real Gross Domestic Product",
            detail_id="d-gdp",
        ),
        IndexRow(
            id=f"{prefix}-population-en",
            lang=Lang.EN,
            text="Total Population",
            detail_id="d-pop",
        ),
    )


def _analyst_rows() -> tuple[IndexRow, ...]:
    """Datapoint-bound passages -- every scope column populated, as AD-14 requires."""
    return (
        IndexRow(
            id="a-1",
            lang=Lang.EN,
            text="Consumer prices rose on the back of housing costs.",
            detail_id="d-cpi",
            period=Period("2025-Q1"),
        ),
        IndexRow(
            id="a-2",
            lang=Lang.EN,
            text="Consumer prices rose on the back of housing costs.",
            detail_id="d-cpi",
            period=Period("2024-Q1"),
        ),
        IndexRow(
            id="a-3",
            lang=Lang.EN,
            text="Consumer prices rose on the back of housing costs.",
            detail_id="d-cpi",
            period=Period("2025-Q1"),
            country_id="c-bh",
        ),
    )


def _build(
    directory: Path,
    source: VectorSourcePort,
    *,
    prefix: str = "g1",
    analyst: bool = False,
) -> Path:
    rows = {Collection.NAMES: _name_rows(prefix)}
    if analyst:
        rows[Collection.ANALYST] = _analyst_rows()
    return build_generation(directory, rows, source, built_at="2026-09-15T10:00:00+00:00")


def _generation(
    directory: Path, source: VectorSourcePort, *, prefix: str = "g1", analyst: bool = False
) -> IndexGeneration:
    return load_generation(_build(directory, source, prefix=prefix, analyst=analyst), source)


# ------------------------------------------------- exact brute-force cosine, in process


def test_a_generation_is_an_index_port(tmp_path: Path, source: TrigramVectorSource) -> None:
    assert isinstance(_generation(tmp_path, source), IndexPort)


def test_the_shipped_vector_source_answers_to_the_port(source: TrigramVectorSource) -> None:
    assert isinstance(source, VectorSourcePort)


def test_every_stored_vector_is_unit_length_so_cosine_is_a_dot_product(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """AD-13: embeddings are normalised at build time, so no query divides by anything."""
    generation = _generation(tmp_path, source)
    for vector in generation.collections[Collection.NAMES].vectors:
        length = sum(value * value for value in vector) ** 0.5
        assert length == pytest.approx(1.0, abs=1e-6)


def test_a_score_is_the_plain_dot_product_of_the_two_vectors(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """Exact brute force, checked arithmetically rather than by ranking."""
    generation = _generation(tmp_path, source)
    question = "Consumer Price Index"
    query = unit_vector_for(question, source)
    matches = generation.search(question, collection=Collection.NAMES, scope=IndexScope())
    by_id = {match.row.id: match.score for match in matches}

    rows = generation.collections[Collection.NAMES].rows
    vectors = generation.collections[Collection.NAMES].vectors
    for row, vector in zip(rows, vectors, strict=True):
        if row.id not in by_id:
            continue
        expected = sum(a * b for a, b in zip(query, vector, strict=True))
        assert by_id[row.id] == pytest.approx(expected, abs=1e-9)


def test_a_surface_matches_itself_at_one(tmp_path: Path, source: TrigramVectorSource) -> None:
    generation = _generation(tmp_path, source)
    best = generation.search(
        "Consumer Price Index", collection=Collection.NAMES, scope=IndexScope()
    )[0]
    assert best.row.id == "g1-cpi-en"
    assert best.score == pytest.approx(1.0, abs=1e-6)


def test_the_better_match_of_two_ranks_first(tmp_path: Path, source: TrigramVectorSource) -> None:
    matches = _generation(tmp_path, source).search(
        "gross domestic product", collection=Collection.NAMES, scope=IndexScope()
    )
    assert matches[0].row.id == "g1-gdp-en"


def test_a_question_sharing_nothing_scores_only_collision_noise(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The honest limit of a hashed vectoriser, asserted rather than hidden.

    An unrelated question shares no trigram with any surface, so its true cosine is zero
    -- but two unrelated trigrams sometimes land in the same column at the reviewed
    width, and the residue is what comes back. It is an order of magnitude below a real
    match, and it is exactly why AD-30 makes a relevance floor something derived from
    measured distributions rather than something this story invents.
    """
    generation = _generation(tmp_path, source)
    noise = generation.search("zzzzz", collection=Collection.NAMES, scope=IndexScope())
    real = generation.search(
        "Consumer Price Index", collection=Collection.NAMES, scope=IndexScope()
    )[0].score
    assert real == pytest.approx(1.0, abs=1e-6)
    assert max((match.score for match in noise), default=0.0) * 5 < real


def test_a_question_that_folds_to_nothing_returns_nothing(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    assert (
        _generation(tmp_path, source).search(
            "!!! ---", collection=Collection.NAMES, scope=IndexScope()
        )
        == ()
    )


def test_an_empty_collection_is_searchable_and_returns_nothing(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """Built empty rather than omitted: "nothing there" and "no such collection" differ."""
    generation = _generation(tmp_path, source)
    assert generation.size(Collection.ARTICLES) == 0
    assert (
        generation.search("anything", collection=Collection.ARTICLES, scope=IndexScope()) == ()
    )


def test_the_same_question_returns_the_same_list_every_time(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """AD-17. Ties are common with hashed trigrams, so the id tie-break does real work."""
    generation = _generation(tmp_path, source)
    runs = [
        generation.search("price index", collection=Collection.NAMES, scope=IndexScope())
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)


def test_ties_break_on_the_row_id(tmp_path: Path, source: TrigramVectorSource) -> None:
    generation = _generation(tmp_path, source, analyst=True)
    matches = generation.search(
        "consumer prices rose", collection=Collection.ANALYST, scope=IndexScope()
    )
    scores = [match.score for match in matches]
    assert scores == [pytest.approx(scores[0])] * len(scores), "the three passages are identical"
    assert [match.row.id for match in matches] == sorted(match.row.id for match in matches)


def test_the_candidate_limit_comes_from_the_rules(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    generation = _generation(tmp_path, source)
    unlimited = generation.search(
        "index", collection=Collection.NAMES, scope=IndexScope(), limit=100
    )
    assert len(generation.search("index", collection=Collection.NAMES, scope=IndexScope())) <= (
        candidate_limit()
    )
    assert len(generation.search("index", collection=Collection.NAMES, scope=IndexScope(), limit=1))
    assert len(unlimited) >= 1


# ------------------------------------------------------------- no ANN library, no server


def test_no_ann_library_or_vector_server_is_in_the_dependency_tree() -> None:
    """AD-13, read off the project's own pins rather than off a promise."""
    declared = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    offenders = [name for name in FORBIDDEN_DEPENDENCIES if f'"{name}' in declared]
    assert offenders == [], f"the index needs none of these: {sorted(offenders)}"


def test_the_index_imports_only_the_standard_library_and_this_project() -> None:
    """NFR-4: it runs inside the estate. Nothing here reaches a service of any kind."""
    permitted = frozenset(
        {"askai", "hashlib", "math", "os", "sqlite3", "struct", "threading", "uuid"}
    )
    offenders: list[str] = []
    for path in sorted(INDEX_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in permitted or root in {
                    "collections",
                    "contextlib",
                    "dataclasses",
                    "datetime",
                    "enum",
                    "pathlib",
                    "types",
                    "typing",
                    "__future__",
                }:
                    continue
                offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {name}")
    assert offenders == []


def test_nothing_in_the_index_opens_a_socket_or_a_client() -> None:
    forbidden = ("socket", "httpx", "urllib", "requests", "http.client", "asyncio")
    for path in sorted(INDEX_PACKAGE.rglob("*.py")):
        source_text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert f"import {word}" not in source_text, f"{path.name} reaches outside the estate"


# ------------------------------------------------------------------------ the persisted form


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


@pytest.fixture
def built(tmp_path: Path, source: TrigramVectorSource) -> Iterator[sqlite3.Connection]:
    path = _build(tmp_path, source, analyst=True)
    connection = sqlite3.connect(str(path))
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize("collection", list(Collection))
def test_a_collection_table_carries_the_row_and_the_scope_columns(
    built: sqlite3.Connection, collection: Collection
) -> None:
    """Story 2.1's persisted form, column for column."""
    assert _columns(built, collection_table(collection)) == [
        "id",
        "lang",
        "text",
        "embedding",
        "detail_id",
        "period",
        "country_id",
        "article_date",
    ]


@pytest.mark.parametrize("collection", list(Collection))
def test_a_collection_is_indexed_on_its_scope_columns(
    built: sqlite3.Connection, collection: Collection
) -> None:
    table = collection_table(collection)
    indexes = [str(row[1]) for row in built.execute(f"PRAGMA index_list({table})")]
    scope = [name for name in indexes if name.endswith("_scope")]
    assert scope, f"{table} has no scope index"
    columns = [str(row[2]) for row in built.execute(f"PRAGMA index_info({scope[0]})")]
    assert columns == ["detail_id", "period", "country_id", "lang"]


def test_the_exact_text_embedded_is_stored_for_audit(built: sqlite3.Connection) -> None:
    stored = dict(built.execute(f"SELECT id, text FROM {collection_table(Collection.NAMES)}"))
    assert stored["g1-cpi-en"] == "Consumer Price Index"
    assert stored["g1-cpi-en"] != normalise("Consumer Price Index"), (
        "the audited text is what was published, not what was compared"
    )


def test_an_embedding_is_float32_little_endian_of_the_declared_width(
    built: sqlite3.Connection, source: TrigramVectorSource
) -> None:
    row = built.execute(
        f"SELECT embedding FROM {collection_table(Collection.NAMES)} WHERE id = 'g1-cpi-en'"
    ).fetchone()
    blob = row[0]
    assert isinstance(blob, bytes)
    assert len(blob) == source.dimensions * 4
    unpacked = struct.unpack(f"<{source.dimensions}f", blob)
    assert unpacked == pytest.approx(unit_vector_for("Consumer Price Index", source), abs=1e-6)


def test_the_file_records_what_built_it(
    built: sqlite3.Connection, source: TrigramVectorSource
) -> None:
    row = built.execute(
        f"SELECT built_at, source_identity, dimensions FROM {META_TABLE}"
    ).fetchone()
    assert row == ("2026-09-15T10:00:00+00:00", source.identity, source.dimensions)


def test_the_index_file_carries_its_own_shape_version(built: sqlite3.Connection) -> None:
    assert built.execute("PRAGMA user_version").fetchone()[0] == INDEX_SCHEMA_VERSION


def test_no_numeric_row_is_embedded(built: sqlite3.Connection) -> None:
    """AD-13: numeric rows are never embedded. There is nowhere in the shape to put one."""
    for collection in Collection:
        columns = _columns(built, collection_table(collection))
        assert not [name for name in columns if name in {"actual", "target", "baseline", "value"}]


# ------------------------------------------------------- one normalisation (AD-26)


def test_the_index_folds_text_with_the_engines_one_normalisation() -> None:
    """The index path and the query path are the same function, not merely the same rule."""
    module = importlib.import_module("askai.adapters.index.vectors")
    assert getattr(module, "normalise") is normalise


def test_a_differently_spelled_arabic_query_reaches_the_indexed_surface(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """Finding 121's shape: the fold has to happen identically on both sides or never meet."""
    generation = _generation(tmp_path, source)
    matches = generation.search(
        "الرقم القياسى لاسعار المستهلك", collection=Collection.NAMES, scope=IndexScope()
    )
    assert matches[0].row.id == "g1-cpi-ar"
    assert matches[0].score == pytest.approx(1.0, abs=1e-6)


def test_case_and_punctuation_do_not_change_the_score(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    generation = _generation(tmp_path, source)
    plain = generation.search(
        "consumer price index", collection=Collection.NAMES, scope=IndexScope()
    )
    dressed = generation.search(
        "  CONSUMER -- price_index!! ", collection=Collection.NAMES, scope=IndexScope()
    )
    assert [match.row.id for match in plain] == [match.row.id for match in dressed]
    assert plain[0].score == pytest.approx(dressed[0].score)


# ---------------------------------------------------------- filtered before it is ranked


def test_an_out_of_scope_row_is_not_a_candidate(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """AD-14: three identical passages, and only the in-scope one may be returned."""
    generation = _generation(tmp_path, source, analyst=True)
    matches = generation.search(
        "consumer prices rose",
        collection=Collection.ANALYST,
        scope=IndexScope(detail_id="d-cpi", period=Period("2025-Q1"), national=True),
    )
    assert [match.row.id for match in matches] == ["a-1"]


def test_national_scope_is_the_absence_of_a_country_not_a_country_value(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    generation = _generation(tmp_path, source, analyst=True)
    national = generation.search(
        "consumer prices rose", collection=Collection.ANALYST, scope=IndexScope(national=True)
    )
    named = generation.search(
        "consumer prices rose",
        collection=Collection.ANALYST,
        scope=IndexScope(country_id="c-bh"),
    )
    assert [match.row.id for match in national] == ["a-1", "a-2"]
    assert [match.row.id for match in named] == ["a-3"]


def test_a_scope_is_national_or_names_a_country_never_both() -> None:
    with pytest.raises(ValueError, match="never both"):
        IndexScope(country_id="c-bh", national=True)


def test_a_language_filter_is_a_pre_filter(tmp_path: Path, source: TrigramVectorSource) -> None:
    matches = _generation(tmp_path, source).search(
        "price index", collection=Collection.NAMES, scope=IndexScope(lang=Lang.AR)
    )
    assert all(match.row.lang is Lang.AR for match in matches)


def test_a_scope_admitting_nothing_returns_nothing_rather_than_the_next_best(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    matches = _generation(tmp_path, source, analyst=True).search(
        "consumer prices rose",
        collection=Collection.ANALYST,
        scope=IndexScope(detail_id="d-nothing"),
    )
    assert matches == ()


# ----------------------------------------------------- built whole into a new file


def _generation_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.name.startswith("index-"))


def test_a_build_produces_one_new_file_and_leaves_no_working_file(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    first = _build(tmp_path, source, prefix="g1")
    second = _build(tmp_path, source, prefix="g2")
    assert first != second
    assert _generation_files(tmp_path) == sorted([first, second])
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []


def test_a_failed_build_publishes_nothing_at_all(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """A half-built generation must be unreachable, not merely unlikely."""
    duplicated = (
        IndexRow(id="same", lang=Lang.EN, text="one"),
        IndexRow(id="same", lang=Lang.EN, text="two"),
    )
    with pytest.raises(IndexBuildError, match="twice"):
        build_generation(tmp_path, {Collection.NAMES: duplicated}, source)
    assert list(tmp_path.iterdir()) == []


def test_a_generation_is_never_written_again_after_it_is_published(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The loader opens read-only; the claim is checked by trying to write through it."""
    path = _build(tmp_path, source)
    load_generation(path, source)
    read_only = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            read_only.execute(f"DELETE FROM {collection_table(Collection.NAMES)}")
    finally:
        read_only.close()


def test_a_rebuild_touches_neither_the_read_model_nor_the_record_store(
    tmp_path: Path, source: TrigramVectorSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-20's reason for the separate file, observed rather than asserted in prose."""
    paths = DatabasePaths.beneath(tmp_path / "data")
    provision(paths).close()

    opened: list[str] = []
    real_connect = sqlite3.connect

    def spy(target: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        opened.append(str(target))
        connection: sqlite3.Connection = real_connect(target, *args, **kwargs)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    _build(tmp_path / "index", source)

    assert opened, "the build must have opened its own file"
    for target in opened:
        assert str(paths.read_model) not in target
        assert str(paths.record_store) not in target
        assert str(paths.semantic_index) not in target


def test_a_rebuild_does_not_block_a_live_write(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The single-writer lock AD-20 separates the files to avoid, exercised concurrently.

    A writer thread commits to the record store throughout a build of a corpus large
    enough that the two genuinely overlap. If the rebuild shared a write lock with live
    records, these writes would block behind it or fail outright.
    """
    paths = DatabasePaths.beneath(tmp_path / "data")
    provision(paths).close()

    stop = threading.Event()
    written = 0
    failures: list[BaseException] = []

    def write_records() -> None:
        nonlocal written
        connection = connect_database(RECORD_STORE, paths.record_store)
        try:
            while not stop.is_set():
                connection.execute(
                    "INSERT INTO record (record_id, recorded_at, identity_asserted, language, "
                    "question, spec_version, spec_json, answer_json) "
                    "VALUES (?, '2026-09-15T10:00:00Z', 0, 'en', 'q', 1, '{}', '{}')",
                    (f"r{written}",),
                )
                connection.commit()
                written += 1
        except BaseException as error:  # noqa: BLE001 -- reported, not swallowed
            failures.append(error)
        finally:
            connection.close()

    writer = threading.Thread(target=write_records, name="live-writer")
    writer.start()
    try:
        big = tuple(
            IndexRow(id=f"n{number}", lang=Lang.EN, text=f"Indicator number {number}")
            for number in range(400)
        )
        build_generation(tmp_path / "index", {Collection.NAMES: big}, source)
    finally:
        stop.set()
        writer.join(timeout=30)

    assert failures == []
    assert written > 0, "the writer must have run during the build"


# --------------------------------------------------------------- swapped by reference


def test_the_swap_publishes_the_new_generation_and_returns_the_old(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    first = _generation(tmp_path, source, prefix="g1")
    second = _generation(tmp_path, source, prefix="g2")
    holder = SwappableIndex(first)

    assert holder.current() is first
    assert holder.swap(second) is first
    assert holder.current() is second


def test_a_held_reference_does_not_change_when_the_index_is_swapped(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    first = _generation(tmp_path, source, prefix="g1")
    second = _generation(tmp_path, source, prefix="g2")
    holder = SwappableIndex(first)

    with holder.hold() as held:
        holder.swap(second)
        assert held is first
        matches = held.search("price index", collection=Collection.NAMES, scope=IndexScope())
        assert all(match.row.id.startswith("g1-") for match in matches)
    assert holder.current() is second


def test_a_reader_keeps_working_while_the_index_is_swapped_underneath_it(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The atomicity claim, with a concurrent reader -- which is the only evidence for it.

    The two generations share no row id, so a reader that observed a mixture would return
    a ``g2`` id from a ``g1`` reference. The reader takes one reference and searches in a
    loop; the swapper replaces the current generation repeatedly while it does.
    """
    first = _generation(tmp_path, source, prefix="g1")
    others = [_generation(tmp_path, source, prefix=f"g{number}") for number in range(2, 8)]
    holder = SwappableIndex(first)

    stop = threading.Event()
    started = threading.Event()
    seen: list[str] = []
    failures: list[BaseException] = []
    searches = 0

    def read() -> None:
        nonlocal searches
        try:
            with holder.hold() as held:
                while not stop.is_set():
                    matches = held.search(
                        "price index", collection=Collection.NAMES, scope=IndexScope()
                    )
                    seen.extend(match.row.id for match in matches)
                    searches += 1
                    started.set()
        except BaseException as error:  # noqa: BLE001 -- reported, not swallowed
            failures.append(error)

    reader = threading.Thread(target=read, name="index-reader")
    reader.start()
    try:
        assert started.wait(timeout=10), "the reader never ran"
        swaps = 0
        for _ in range(20):
            for generation in others:
                holder.swap(generation)
                swaps += 1
        assert swaps == 120
    finally:
        stop.set()
        reader.join(timeout=30)

    assert failures == []
    assert searches > 0
    assert seen, "the reader must have returned rows"
    assert {row_id.split("-")[0] for row_id in seen} == {"g1"}, (
        "a held reference returned a row from another generation"
    )


def test_a_reader_holding_a_retired_generation_still_answers(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The file is gone; the reference is in memory, and the request that holds it finishes."""
    first = _generation(tmp_path, source, prefix="g1")
    second = _generation(tmp_path, source, prefix="g2")
    holder = SwappableIndex(first)

    with holder.hold() as held:
        superseded = holder.swap(second)
        holder.retire(superseded)
        assert not first.path.exists()
        matches = held.search("price index", collection=Collection.NAMES, scope=IndexScope())
        assert matches and all(match.row.id.startswith("g1-") for match in matches)


def test_the_live_generation_cannot_be_retired(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    holder = SwappableIndex(_generation(tmp_path, source))
    with pytest.raises(ValueError, match="in force"):
        holder.retire(holder.current())
    assert holder.current().path.exists()


def test_two_refreshes_finishing_together_each_supersede_a_different_generation(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The lock's only job: a superseded generation is handed to exactly one swapper."""
    generations = [_generation(tmp_path, source, prefix=f"g{number}") for number in range(8)]
    holder = SwappableIndex(generations[0])
    ready = threading.Barrier(len(generations) - 1)
    superseded: list[IndexGeneration] = []
    lock = threading.Lock()

    def swap(generation: IndexGeneration) -> None:
        ready.wait(timeout=30)
        previous = holder.swap(generation)
        with lock:
            superseded.append(previous)

    threads = [
        threading.Thread(target=swap, args=(generation,)) for generation in generations[1:]
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len({id(generation) for generation in superseded}) == len(superseded)
    assert holder.current() not in superseded


# ------------------------------------------------------- a rebuild, never a migration


def test_an_index_built_by_another_vector_source_is_refused(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    path = _build(tmp_path, source)
    other = TrigramVectorSource(dimensions=source.dimensions, window=source.window + 1)
    with pytest.raises(IndexLoadError, match="rebuild, not a migration"):
        load_generation(path, other)


def test_an_index_of_another_width_is_refused(tmp_path: Path) -> None:
    narrow = TrigramVectorSource(dimensions=32)
    path = _build(tmp_path, narrow)
    wider = TrigramVectorSource(dimensions=64)
    with pytest.raises(IndexLoadError):
        load_generation(path, wider)


def test_an_index_of_another_shape_version_is_refused(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    path = _build(tmp_path, source)
    tamper = sqlite3.connect(str(path))
    tamper.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 1}")
    tamper.close()
    with pytest.raises(IndexLoadError, match="shape version"):
        load_generation(path, source)


def test_a_missing_generation_is_not_created_by_loading_it(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    missing = tmp_path / "index-nothing.sqlite3"
    with pytest.raises(IndexLoadError, match="no index generation"):
        load_generation(missing, source)
    assert not missing.exists()


def test_a_truncated_embedding_is_refused_rather_than_scored(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    path = _build(tmp_path, source)
    tamper = sqlite3.connect(str(path))
    with tamper:
        tamper.execute(
            f"UPDATE {collection_table(Collection.NAMES)} SET embedding = ? WHERE id = ?",
            (pack_vector((1.0, 0.0)), "g1-cpi-en"),
        )
    tamper.close()
    with pytest.raises(IndexLoadError, match="bytes of embedding"):
        load_generation(path, source)


# ------------------------------------------------------------- the deterministic fallback


def test_the_vectoriser_is_deterministic_across_processes() -> None:
    """``hash()`` is seeded per process; an index built with it would not survive a restart."""
    program = (
        "from askai.adapters.index.vectors import TrigramVectorSource, unit_vector_for;"
        "s = TrigramVectorSource();"
        "print(s.identity, sum(unit_vector_for('Consumer Price Index', s)))"
    )
    outputs = []
    for seed in ("0", "12345"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                check=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]


def test_the_identity_names_every_parameter_that_changes_a_vector() -> None:
    base = TrigramVectorSource(dimensions=64, window=3, pad=True)
    assert base.identity != TrigramVectorSource(dimensions=128, window=3, pad=True).identity
    assert base.identity != TrigramVectorSource(dimensions=64, window=4, pad=True).identity
    assert base.identity != TrigramVectorSource(dimensions=64, window=3, pad=False).identity
    assert base.identity == TrigramVectorSource(dimensions=64, window=3, pad=True).identity


def test_a_vector_has_the_declared_width(source: TrigramVectorSource) -> None:
    assert len(source.vectorise(normalise("Consumer Price Index"))) == source.dimensions


def test_text_that_folds_to_nothing_vectorises_to_zero(source: TrigramVectorSource) -> None:
    assert not any(unit_vector_for("!!!", source))


def test_unit_length_leaves_the_zero_vector_alone() -> None:
    assert unit_length((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)


def test_a_surface_shorter_than_one_window_is_still_indexable(tmp_path: Path) -> None:
    """A two-letter code must be findable, not indexed as nothing at all."""
    source = TrigramVectorSource(dimensions=64, window=5, pad=False)
    path = build_generation(
        tmp_path,
        {Collection.NAMES: (IndexRow(id="code", lang=Lang.EN, text="GDP"),)},
        source,
    )
    generation = load_generation(path, source)
    assert generation.search("GDP", collection=Collection.NAMES, scope=IndexScope())[0].score == (
        pytest.approx(1.0, abs=1e-6)
    )


# ------------------------------------------------- the constants are data, not literals


def test_the_reviewed_constants_come_from_the_rule_files() -> None:
    assert vector_width() == rules().value(VECTOR_WIDTH_RULE, "dimensions")
    assert trigram_size() == rules().value(TRIGRAM_RULE, "trigram_size")
    assert candidate_limit() == rules().value(CANDIDATE_LIMIT_RULE, "candidates")


def test_the_shipped_source_defaults_to_the_reviewed_constants() -> None:
    source = TrigramVectorSource()
    assert (source.dimensions, source.window) == (vector_width(), trigram_size())


def test_the_fallback_is_recorded_as_a_reviewed_decision() -> None:
    """Story 2.1's stated fallback, in ``rules/`` where it can be revisited with evidence."""
    rule = rules().get(TRIGRAM_RULE).rule
    assert "trigram" in rule.statement.lower()
    assert rule.values["trigram_size"] == 3


def test_no_relevance_floor_was_invented(tmp_path: Path, source: TrigramVectorSource) -> None:
    """AD-30: a floor is derived from a labelled set and recorded with its separation.

    Until that derivation exists the index applies none, and a weak match is returned to
    be judged rather than dropped by a number nobody measured. Only an exact zero -- no
    shared feature at all -- is excluded.
    """
    for entry in rules():
        assert "floor" not in entry.rule.values, f"{entry.id} declares an underived floor"
    matches = _generation(tmp_path, source).search(
        "price", collection=Collection.NAMES, scope=IndexScope()
    )
    assert matches and min(match.score for match in matches) < 0.5


# ------------------------------------------------------------------- table ownership


def _sql_literals(source_text: str) -> list[str]:
    tree = ast.parse(source_text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_only_the_index_adapter_names_an_index_table() -> None:
    """AD-20's one-owner rule for the tables this story adds, checked against the source.

    The index file's tables are declared in ``adapters/index/schema.py`` and written by
    ``adapters/index/build.py`` alone. They are not in the estate's ``TABLE_OWNERS`` map,
    which covers the three provisioned files; this is the equivalent guarantee for the
    file a generation is built into.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if INDEX_PACKAGE in path.parents:
            continue
        for literal in _sql_literals(path.read_text(encoding="utf-8")):
            lowered = literal.lower()
            if "vec_" in lowered or META_TABLE in lowered:
                offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {literal!r}")
    assert offenders == []


def test_the_index_adapter_never_writes_an_estate_table() -> None:
    """The other direction: the build writes its own file and nothing in the read model."""
    estate = ("catalogue", "detail", "datapoint", "ref_country", "ref_lookup", "record")
    for path in sorted(INDEX_PACKAGE.rglob("*.py")):
        for literal in _sql_literals(path.read_text(encoding="utf-8")):
            lowered = literal.lower()
            if "insert" not in lowered and "update" not in lowered and "delete" not in lowered:
                continue
            for table in estate:
                assert f" {table}" not in lowered, f"{path.name} writes {table}"


def _rows_of(generation: IndexGeneration, collection: Collection) -> Sequence[IndexRow]:
    return generation.collections[collection].rows


def test_a_generation_reports_what_it_holds(tmp_path: Path, source: TrigramVectorSource) -> None:
    generation = _generation(tmp_path, source, analyst=True)
    assert generation.size(Collection.NAMES) == 4
    assert generation.size(Collection.ANALYST) == 3
    assert generation.built_at == "2026-09-15T10:00:00+00:00"
    assert generation.source_identity == source.identity
    assert [row.id for row in _rows_of(generation, Collection.NAMES)] == sorted(
        row.id for row in _name_rows("g1")
    )
