"""The corpus runner.

Loads every ``corpus/*.yaml`` and ``corpus/*.yml``, parses each entry and
executes it. ``QuerySpec``
does not exist yet (Story 1.11), so "execute" is structural validation only:
a file must parse to a list of mappings whose keys are strings. The assertion
surface against the ``QuerySpec`` and the typed elements arrives with 1.11/1.13.

Failures name the offending file and the reason; they are never swallowed.

Runnable directly, with the same invocation CI uses::

    uv run python tests/corpus_runner.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"


class CorpusError(Exception):
    """A corpus file could not be loaded or is not structurally valid."""


@dataclass(frozen=True)
class CorpusEntry:
    """One corpus entry, with the file it came from and its position in it."""

    source: Path
    index: int
    data: dict[str, Any]


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[CorpusEntry]:
    """Load and structurally validate every entry under *corpus_dir*.

    Raises ``CorpusError`` naming the file and the reason on anything malformed.
    """
    if not corpus_dir.is_dir():
        raise CorpusError(f"{corpus_dir}: corpus directory does not exist")

    entries: list[CorpusEntry] = []
    paths = sorted(set(corpus_dir.glob("*.yaml")) | set(corpus_dir.glob("*.yml")))
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CorpusError(f"{path}: not valid YAML: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise CorpusError(f"{path}: not valid UTF-8: {exc}") from exc
        except OSError as exc:
            raise CorpusError(f"{path}: could not be read: {exc}") from exc

        if raw is None:
            raise CorpusError(
                f"{path}: file is empty; an empty corpus file must still be a list ([])"
            )
        if not isinstance(raw, list):
            raise CorpusError(f"{path}: expected a list of entries, got {type(raw).__name__}")

        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise CorpusError(
                    f"{path}: entry {index} is a {type(item).__name__}, expected a mapping"
                )
            if not all(isinstance(key, str) for key in item):
                raise CorpusError(f"{path}: entry {index} has a non-string key")
            entries.append(CorpusEntry(source=path, index=index, data=dict(item)))

    return entries


def run_entry(entry: CorpusEntry) -> None:
    """Execute one entry.

    With no ``QuerySpec`` to bind against, execution is the structural check
    ``load_corpus`` already made. This function is the seam Story 1.11 fills;
    it must never grow an assertion on prose.
    """


def run_corpus(corpus_dir: Path = CORPUS_DIR) -> int:
    """Load and execute the whole corpus. Returns the entry count."""
    entries = load_corpus(corpus_dir)
    for entry in entries:
        run_entry(entry)
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    corpus_dir = Path(args[0]).resolve() if args else CORPUS_DIR
    try:
        count = run_corpus(corpus_dir)
    except CorpusError as exc:
        print(f"corpus: FAILED — {exc}", file=sys.stderr)
        return 1
    print(f"corpus: {count} entries collected from {corpus_dir}, all structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
