"""Run the retrieval harness against a real embedding endpoint, and print the report.

``python -m askai.adapters.index`` measures the shipped character-trigram source, because
the index package is held to a narrow import allow-list and takes its vector source as a
function argument rather than a flag. This script is the other half: the same harness,
the same labelled set, the same export -- pointed at an embedding service instead.

It lives outside ``src/askai/`` on purpose. It reads the environment and parses arguments,
neither of which the package permits, and it is a measuring instrument rather than part of
the engine.

Run it with the embedding service reachable::

    ASKAI_EMBEDDING_BASE_URL=http://localhost:8080/v1 \
    ASKAI_EMBEDDING_MODEL=BAAI/bge-m3 \
    ASKAI_EMBEDDING_DIMENSIONS=1024 \
    uv run python scripts/measure_embeddings.py

Compare what it prints against the trigram baseline from
``uv run python -m askai.adapters.index``. The bar the embedding source has to clear is in
``src/askai/rules/data/names-floor.yaml``: beat 21.4% recall@1 and 47.6% recall@10 on
paraphrases, and 50%/90% on synonyms, **without** dropping below 96% on exact names or
94% on typos.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from askai.adapters.index.labelled import load_labelled_set
from askai.adapters.index.quality import (
    EXPORT_ROOT,
    LABELLED_ROOT,
    render,
    render_derivation,
    report_for,
)
from askai.adapters.model.embeddings import EmbeddingVectorSource
from askai.adapters.readmodel.export import CmsExport
from askai.config.model import EmbeddingSettings


def main() -> int:
    try:
        settings = EmbeddingSettings.from_env()
    except Exception as error:  # noqa: BLE001 - a measuring script, not the engine
        print(f"settings: {error}", file=sys.stderr)
        print(
            "\nSet ASKAI_EMBEDDING_BASE_URL, ASKAI_EMBEDDING_MODEL and "
            "ASKAI_EMBEDDING_DIMENSIONS.\nDimensions has no default on purpose: it is half "
            "the index identity, and a guess would be\nwritten into the index file and "
            "compared at every later load.",
            file=sys.stderr,
        )
        return 2

    source = EmbeddingVectorSource(settings=settings)
    print(f"vector source  {source.identity}")
    print(f"endpoint       {settings.base_url}\n")

    workspace = PROJECT_ROOT / f".measure-{uuid.uuid4().hex}"
    try:
        measured = report_for(
            load_labelled_set(LABELLED_ROOT),
            CmsExport.rooted(EXPORT_ROOT),
            source,
            workspace=workspace,
        )
    except (OSError, RuntimeError) as error:
        print(f"{error}", file=sys.stderr)
        print(
            "\nIf this is a connection failure the endpoint is not reachable from here. "
            "The\nembedding service must publish its port, and this machine must be able "
            "to reach it.",
            file=sys.stderr,
        )
        return 1
    finally:
        if workspace.is_dir():
            for path in workspace.iterdir():
                path.unlink(missing_ok=True)
            workspace.rmdir()

    render(measured, None)
    print()
    render_derivation(measured, "", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
