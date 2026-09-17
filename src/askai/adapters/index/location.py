"""Where a deployment's generations live, and which vector source reads them.

Purity: IO.

AD-13 says a generation is a file built whole and published by rename, and
:mod:`askai.adapters.index.build` writes one. It does not say *where*, because the build
is handed a directory. This module is the one place that answers it, so the refresh that
publishes a generation and the process that serves out of one cannot disagree — a
disagreement whose only symptom is a server that resolves nothing, which is exactly what
Session M was called in to fix.

**Beside the databases, in a directory of their own.** ``ASKAI_DATABASE_DIR`` already
names the volume the estate lives on (``askai-databases:/var/lib/askai`` in compose), and
a generation belongs to that estate: it is rebuilt by the same refresh that reloads the
read model, from the same export, and is meaningless beside a different one. It is a
*directory* rather than a fourth filename because publication is an atomic rename within
a directory and retirement is an unlink of the file it superseded — two names for one
generation cannot express that, and ``DatabasePaths.semantic_index`` is the store-shaped
build target of AD-20, not this.

**The newest file wins, and normally there is only one.** A publication retires what it
superseded, so the directory holds one generation. Two can only be there after a build
that died between the rename and the unlink, and taking the newest of them is the same
answer that an operator re-running the build would get.

**Which vector source is a deployment fact, not a guess.** A process told about an
embedding runtime uses it; a process told about none falls back to the shipped trigram
source, which needs nothing. That fallback is safe *only* because a generation records
what built it and refuses to load against anything else
(:func:`askai.adapters.index.generation.load_generation`): a deployment that built with
BGE-M3 and serves with trigrams does not answer worse, it does not start.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from askai.adapters.index.build import GENERATION_PREFIX, GENERATION_SUFFIX
from askai.adapters.index.vectors import TrigramVectorSource
from askai.adapters.model.embeddings import EmbeddingVectorSource
from askai.config.database import ConfigError, DatabasePaths
from askai.config.model import EmbeddingSettings
from askai.ports.vectors import VectorSourcePort

__all__ = [
    "GENERATIONS_DIRNAME",
    "configured_source",
    "generations_dir",
    "latest_generation",
    "published_generations",
]

#: The directory, under the estate's database directory, that generations are published
#: into. Named here and nowhere else.
GENERATIONS_DIRNAME: Final = "index"

_GLOB: Final = f"{GENERATION_PREFIX}*{GENERATION_SUFFIX}"


def generations_dir(paths: DatabasePaths) -> Path:
    """The generation directory for the estate at *paths*.

    Derived from the read model's own directory rather than configured separately, for
    the reason ``state_path_for`` derives the refresh state file's: an index configured
    apart from the databases it describes is an index of some other deployment's export,
    and nothing downstream could tell.
    """
    return paths.read_model.parent / GENERATIONS_DIRNAME


def published_generations(directory: Path) -> tuple[Path, ...]:
    """Every published generation in *directory*, newest first. Empty when there is none.

    A half-built file is invisible here by construction: the build writes under a hidden
    working name and only the completed file carries the generation prefix.
    """
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(directory.glob(_GLOB), key=lambda path: (-path.stat().st_mtime_ns, path.name))
    )


def latest_generation(directory: Path) -> Path | None:
    """The generation a process should serve out of, or ``None`` when there is none."""
    found = published_generations(directory)
    return found[0] if found else None


def configured_source(environ: Mapping[str, str] | None = None) -> VectorSourcePort:
    """The vector source this deployment builds and loads generations with.

    The embedding runtime when the settings name one, and the shipped trigram source
    otherwise. Unlike the chat runtime, this is not an optional capability the answer
    path can do without: whichever source is returned here is the one an index is built
    with *and* the one it is checked against, so the two halves cannot come apart, and a
    mismatch between the deployment that built and the one that serves is a refusal to
    load rather than a scored comparison between two vector spaces.
    """
    try:
        settings = EmbeddingSettings.from_env(environ)
    except ConfigError:
        return TrigramVectorSource()
    return EmbeddingVectorSource(settings=settings)
