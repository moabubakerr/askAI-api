"""One generation of the index: loaded into memory, immutable, searched by dot product.

Purity: IO to load; pure to search -- once loaded, a generation touches no file.

This is the object AD-13 describes and the object AD-20 protects. Three properties are
what make the rest of the story true, and each is structural here rather than asserted:

**Exact, in process, no ANN library and no vector server.** A search is the dot product
of the query vector with every in-scope row's vector, taken over vectors that were
L2-normalised at build time, so cosine similarity *is* that dot product and there is no
approximate structure to go stale. At AD-13's corpus size an exhaustive scan is a few
million multiply-adds, and after AD-14's mandatory scope pre-filter a typical query
scores a few dozen rows -- which is why the estate needs no vector service inside it and
makes no external call (NFR-4).

**A request can never observe a mixture.** ``IndexGeneration`` is frozen and holds its
rows as tuples read at load. A refresh does not modify it, cannot modify it, and does
not wait for it: the new generation is a *different object* and swapping is rebinding
one reference (see :mod:`askai.adapters.index.swap`). A caller that took a reference at
the start of a request is still reading the same tuples at the end of it, whatever has
happened to the file or to the holder in between.

**Changing the model is a rebuild, not a migration.** The file records which vector
source built it, and a generation refuses to load against a source with a different
identity or width. A cosine between two vector spaces is a number with no meaning, and
it is the one failure that would look entirely healthy.

The scope filter runs *before* the score, not after it. An out-of-scope row is never a
candidate, so a high score cannot surface it -- F-015's December-analysis-for-a-May-
question is unrepresentable rather than filtered out downstream.
"""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from askai.adapters.index.schema import INDEX_SCHEMA_VERSION, META_TABLE, collection_table
from askai.adapters.index.tuning import candidate_limit
from askai.adapters.index.vectors import unit_vector_for
from askai.domain.period import Period
from askai.messages.lang import Lang
from askai.ports.index import Collection, IndexRow, IndexScope, Match
from askai.ports.vectors import VectorSourcePort

__all__ = ["IndexGeneration", "IndexLoadError", "LoadedCollection", "load_generation"]


class IndexLoadError(RuntimeError):
    """A generation file is absent, is of another shape, or was built by another source.

    Raised at load, before a single query, for the reason ``SchemaVersionMismatch`` is
    raised at open: running a search against vectors this build did not produce returns
    confident nonsense rather than an error, and there is nothing downstream that could
    notice.
    """


@dataclass(frozen=True, slots=True)
class LoadedCollection:
    """One collection in memory: rows, and the parallel vectors in the same order.

    Two parallel tuples rather than a tuple of pairs, because the scan reads the vectors
    and reads the scope columns, and keeping them apart is what lets the pre-filter walk
    the cheap side first.
    """

    rows: tuple[IndexRow, ...]
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.vectors):
            raise IndexLoadError(
                f"{len(self.rows)} rows and {len(self.vectors)} vectors; the arrays are "
                "parallel by construction and a mismatch would misattribute every score"
            )

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class IndexGeneration:
    """The whole index at one point in time. Satisfies ``IndexPort``.

    Frozen, and holding only tuples: there is no representable state in which this
    object's contents change. That is the whole of "a request holds one index reference
    for its lifetime and can never observe a mixture" -- not a discipline the caller has
    to keep, but a thing the value cannot do.
    """

    path: Path
    built_at: str
    source_identity: str
    dimensions: int
    collections: Mapping[Collection, LoadedCollection]
    source: VectorSourcePort

    def search(
        self,
        question: str,
        *,
        collection: Collection,
        scope: IndexScope,
        limit: int | None = None,
    ) -> tuple[Match, ...]:
        """The in-scope rows of *collection* most similar to *question*, best first.

        *question* goes through ``unit_vector_for`` -- the same function the build used,
        which begins with the engine's one ``normalise()`` (AD-26). Ties break on the row
        id so that the same question returns the same list on every run (AD-17), which
        matters more here than it would with a real embedding model: hashed trigrams
        produce exact ties often.
        """
        loaded = self.collections[collection]
        query = unit_vector_for(question, self.source)
        if not any(query):
            # Nothing comparable survived the fold -- punctuation, or an empty question.
            # Zero against everything is the honest answer, and scoring it would return
            # an arbitrary slice of the collection ordered by nothing.
            return ()

        scored = [
            Match(row=row, score=score)
            for row, vector in zip(loaded.rows, loaded.vectors, strict=True)
            if _in_scope(row, scope)
            and (score := sum(a * b for a, b in zip(query, vector, strict=True))) > 0.0
        ]
        scored.sort(key=lambda match: (-match.score, match.row.id))
        return tuple(scored[: candidate_limit() if limit is None else limit])

    def size(self, collection: Collection) -> int:
        """How many rows *collection* holds. For reporting what a refresh published."""
        return len(self.collections[collection])


def _in_scope(row: IndexRow, scope: IndexScope) -> bool:
    """AD-14's pre-filter: an unset field constrains nothing, a set one is exact.

    ``national`` is its own field because the published layer spells national scope as
    the *absence* of a country (AD-5); a single nullable filter could not tell "any
    country" from "no country", and the second is a real, common, answerable scope.
    """
    if scope.detail_id is not None and row.detail_id != scope.detail_id:
        return False
    if scope.period is not None and row.period != scope.period:
        return False
    if scope.lang is not None and row.lang is not scope.lang:
        return False
    if scope.national:
        return row.country_id is None
    return scope.country_id is None or row.country_id == scope.country_id


def load_generation(path: Path, source: VectorSourcePort) -> IndexGeneration:
    """Read the generation at *path* into memory, or refuse to return one.

    Opened read-only: a loader that could write is a second writer to a file whose whole
    safety argument is that it has none. Every check that can fail does so here, at
    startup or at swap time, rather than at the first question.
    """
    if not path.is_file():
        raise IndexLoadError(
            f"no index generation at {path}; a generation is created by the build step "
            "and published by rename, never brought into being by opening it"
        )
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        _verify_version(connection, path)
        built_at, identity, dimensions = _read_meta(connection, path)
        _verify_source(path, identity, dimensions, source)
        collections = {
            collection: _read_collection(connection, collection, dimensions, path)
            for collection in Collection
        }
    finally:
        connection.close()
    return IndexGeneration(
        path=path,
        built_at=built_at,
        source_identity=identity,
        dimensions=dimensions,
        collections=MappingProxyType(collections),
        source=source,
    )


def _verify_version(connection: sqlite3.Connection, path: Path) -> None:
    row = connection.execute("PRAGMA user_version").fetchone()
    found = int(row[0]) if row is not None else 0
    if found != INDEX_SCHEMA_VERSION:
        raise IndexLoadError(
            f"{path} is an index of shape version {found}; this build reads "
            f"{INDEX_SCHEMA_VERSION}. A generation is rebuilt, never migrated."
        )


def _read_meta(connection: sqlite3.Connection, path: Path) -> tuple[str, str, int]:
    row = connection.execute(
        f"SELECT built_at, source_identity, dimensions FROM {META_TABLE} WHERE only_row = 1"
    ).fetchone()
    if row is None:
        raise IndexLoadError(
            f"{path} records nothing about what built it; without the vector source's "
            "identity there is no way to refuse a query from another vector space"
        )
    return str(row[0]), str(row[1]), int(row[2])


def _verify_source(path: Path, identity: str, dimensions: int, source: VectorSourcePort) -> None:
    if identity != source.identity:
        raise IndexLoadError(
            f"{path} was built by {identity!r} and is being loaded against "
            f"{source.identity!r}. Changing the vector source is a rebuild, not a "
            "migration: a cosine across two vector spaces is confident nonsense."
        )
    if dimensions != source.dimensions:
        raise IndexLoadError(
            f"{path} holds {dimensions}-dimension vectors and {source.identity!r} "
            f"produces {source.dimensions}"
        )


def _read_collection(
    connection: sqlite3.Connection,
    collection: Collection,
    dimensions: int,
    path: Path,
) -> LoadedCollection:
    table = collection_table(collection)
    cursor = connection.execute(
        "SELECT id, lang, text, embedding, detail_id, period, country_id, article_date "
        f"FROM {table} ORDER BY id"
    )
    rows: list[IndexRow] = []
    vectors: list[tuple[float, ...]] = []
    for record in cursor:
        rows.append(_row_of(record))
        vectors.append(_unpack(record[3], dimensions, str(record[0]), collection, path))
    return LoadedCollection(rows=tuple(rows), vectors=tuple(vectors))


def _row_of(record: Sequence[object]) -> IndexRow:
    period = record[5]
    return IndexRow(
        id=str(record[0]),
        lang=Lang(str(record[1])),
        text=str(record[2]),
        detail_id=None if record[4] is None else str(record[4]),
        period=None if period is None else Period(str(period)),
        country_id=None if record[6] is None else str(record[6]),
        article_date=None if record[7] is None else str(record[7]),
    )


def _unpack(
    blob: object, dimensions: int, row_id: str, collection: Collection, path: Path
) -> tuple[float, ...]:
    if not isinstance(blob, bytes):
        raise IndexLoadError(f"{row_id} in {collection.value} of {path} holds no embedding")
    expected = dimensions * 4
    if len(blob) != expected:
        raise IndexLoadError(
            f"{row_id} in {collection.value} of {path} holds {len(blob)} bytes of "
            f"embedding, expected {expected} for {dimensions} float32 values"
        )
    return struct.unpack(f"<{dimensions}f", blob)
