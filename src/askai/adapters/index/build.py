"""Building one index generation: whole, into a new file, published by rename.

Purity: IO.

This is the half of AD-13 that says *"a refresh builds them whole into a new file and
swaps by reference"*, and the half of AD-20 that says the build *"is never written in
place alongside live records or conversation state"*. Both are properties of how this
module writes, not claims made about it:

**A generation is a new file, never an edit.** Every build creates a file that nothing
has ever opened. There is no ``UPDATE``, no ``DELETE`` and no second ``INSERT`` into a
row -- a generation is written once and is thereafter read-only -- so an index rebuild
cannot take a write lock that a live request is waiting for. The read model and the
record store are different files, so a build contends with nothing at all.

**A half-built file is unreachable.** The build writes to a hidden working name in the
same directory and, only after the last row is committed and the connection is closed,
renames it to the generation name the loader looks for. ``os.replace`` is atomic within a
directory on every platform this runs on, so a reader either finds a complete generation
or does not find that generation at all. There is no window in which it finds half of one.

**The working file is cleaned up when the build fails.** A build that raises leaves no
partial file behind under either name, because the partial file never had the name
anything looks for and is removed on the way out.

The generation is written with sqlite's ordinary rollback journal rather than WAL. That
is not a departure from AD-20's connection policy but the consequence of it: WAL exists
to keep a *concurrent reader* consistent with a *concurrent writer*, and this file has
neither -- it is written once by one connection and read by loaders afterwards. Keeping
it out of WAL also keeps a generation exactly one file, which is what makes publishing it
a single atomic rename instead of a rename plus two sidecars.
"""

from __future__ import annotations

import os
import sqlite3
import struct
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from askai.adapters.index.schema import META_TABLE, collection_table, create_index_schema
from askai.adapters.index.vectors import unit_vector_for
from askai.ports.index import Collection, IndexRow
from askai.ports.vectors import VectorSourcePort

__all__ = ["GENERATION_SUFFIX", "IndexBuildError", "build_generation", "pack_vector"]

#: Every generation file ends with this. The loader identifies generations by it, which
#: is why the working file must not carry it until the build has finished.
GENERATION_SUFFIX: Final = ".sqlite3"

_GENERATION_PREFIX: Final = "index-"
_WORKING_PREFIX: Final = ".building-"


class IndexBuildError(RuntimeError):
    """A generation could not be built. Raised, never degraded to a partial index.

    An index missing rows nobody noticed is worse than no index: it answers, plausibly,
    from a corpus that is not the published one. AD-15's fail-soft policy is about the
    answer path degrading a *request*; a build is out of band (AD-21) and has an operator
    to tell.
    """


def pack_vector(vector: tuple[float, ...]) -> bytes:
    """*vector* as float32, little-endian -- the on-disk form of an embedding.

    Endianness is stated rather than inherited from the machine: a generation built on
    one host and loaded on another must be the same numbers, and ``array.tobytes()``
    would quietly make that false.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def build_generation(
    directory: Path,
    rows: Mapping[Collection, Sequence[IndexRow]],
    source: VectorSourcePort,
    *,
    built_at: str | None = None,
) -> Path:
    """Build every collection into a new generation file under *directory*; return its path.

    *rows* need not name every collection: a collection with no rows is built empty
    rather than omitted, so searching it returns nothing instead of failing.

    *built_at* defaults to now, in UTC, and is an argument so a test can pin it. It is
    recorded in the file and travels with the loaded generation, which is how an answer
    can state the freshness of the index behind it (AD-21).
    """
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    working = directory / f"{_WORKING_PREFIX}{token}"
    published = directory / f"{_GENERATION_PREFIX}{token}{GENERATION_SUFFIX}"
    stamp = built_at if built_at is not None else datetime.now(UTC).isoformat()

    try:
        _write(working, rows, source, stamp)
    except BaseException:
        working.unlink(missing_ok=True)
        raise
    # The one moment the generation becomes visible. Atomic within the directory, and
    # onto a name nothing has ever opened, so no reader can be holding the destination.
    os.replace(working, published)
    return published


def _write(
    path: Path,
    rows: Mapping[Collection, Sequence[IndexRow]],
    source: VectorSourcePort,
    built_at: str,
) -> None:
    connection = sqlite3.connect(str(path))
    try:
        with connection:
            create_index_schema(connection)
            for collection in Collection:
                _insert_rows(connection, collection, rows.get(collection, ()), source)
            _insert_meta(connection, source, built_at)
    finally:
        connection.close()


def _insert_rows(
    connection: sqlite3.Connection,
    collection: Collection,
    rows: Sequence[IndexRow],
    source: VectorSourcePort,
) -> None:
    table = collection_table(collection)
    statement = (
        f"INSERT INTO {table} "
        "(id, lang, text, embedding, detail_id, period, country_id, article_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    for row in rows:
        vector = unit_vector_for(row.text, source)
        if len(vector) != source.dimensions:
            raise IndexBuildError(
                f"{row.id} in {collection.value} vectorised to {len(vector)} dimensions, "
                f"but {source.identity} declares {source.dimensions}; a collection whose "
                "rows are different widths cannot be searched at all"
            )
        try:
            connection.execute(
                statement,
                (
                    row.id,
                    row.lang.value,
                    row.text,
                    pack_vector(vector),
                    row.detail_id,
                    None if row.period is None else row.period.value,
                    row.country_id,
                    row.article_date,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise IndexBuildError(
                f"{collection.value} was given {row.id!r} twice, or with a value the "
                f"collection refuses: {error}"
            ) from error


def _insert_meta(connection: sqlite3.Connection, source: VectorSourcePort, built_at: str) -> None:
    connection.execute(
        f"INSERT INTO {META_TABLE} (only_row, built_at, source_identity, dimensions) "
        "VALUES (1, ?, ?, ?)",
        (built_at, source.identity, source.dimensions),
    )
