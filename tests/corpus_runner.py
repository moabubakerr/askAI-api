"""The corpus runner.

Loads every ``corpus/*.yaml`` and ``corpus/*.yml``, parses each entry and
executes it. Binding a ``QuerySpec`` arrives with Story 1.11, so "execute" is
structural validation only: a file must parse to a list of mappings whose keys
are strings, and an entry that declares a ``spec_version`` must declare one this
runner recognises. The assertion surface against the ``QuerySpec`` and the typed
elements arrives with 1.11/1.13.

``spec_version`` is the entry shape's first real field. It exists so that a
change to the serialised spec surfaces as a failing corpus rather than as stale
entries passing quietly against a shape that no longer exists.

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

from askai.domain.spec import SPEC_VERSION

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

#: Spec shapes this runner can execute. Spelled out literally, *not* derived from
#: ``SPEC_VERSION``: deriving it would mean bumping the spec to 2 silently dropped
#: support for 1, so the "keep the old one where it is still executable" decision would
#: be made by a line that looks like it needs no editing. This list has to be edited.
SUPPORTED_SPEC_VERSIONS: frozenset[int] = frozenset({1})

if SPEC_VERSION not in SUPPORTED_SPEC_VERSIONS:
    raise RuntimeError(
        f"the domain serialises spec_version {SPEC_VERSION}, which this runner does not "
        f"support ({sorted(SUPPORTED_SPEC_VERSIONS)}); add it, and decide explicitly "
        "whether the older versions are still executable"
    )


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

    With no question compiling to a ``QuerySpec`` yet, execution is the
    ``spec_version`` check plus the structural check ``load_corpus`` already made.
    This function is the seam Story 1.11 fills; it must never grow an assertion
    on prose.
    """
    _check_spec_version(entry)


def _check_spec_version(entry: CorpusEntry) -> None:
    """Reject an entry written against a spec shape this runner does not know.

    Absence is still tolerated: the entry shape stays provisional until Story 1.11,
    and entries predating the field are not yet wrong. A version that is *present*
    and unrecognised is rejected, naming the file, the entry and both versions -- the
    alternative is asserting the new shape against an entry written for the old one
    and reporting the mismatch as a content failure.
    """
    if "spec_version" not in entry.data:
        return

    declared = entry.data["spec_version"]
    supported = ", ".join(str(version) for version in sorted(SUPPORTED_SPEC_VERSIONS))
    # bool is an int in Python, and `spec_version: yes` parses to True in YAML.
    if not isinstance(declared, int) or isinstance(declared, bool):
        raise CorpusError(
            f"{entry.source}: entry {entry.index} declares spec_version "
            f"{declared!r} ({type(declared).__name__}), which is not an integer; "
            f"this runner supports {supported}"
        )
    if declared not in SUPPORTED_SPEC_VERSIONS:
        raise CorpusError(
            f"{entry.source}: entry {entry.index} declares spec_version {declared}, "
            f"which this runner does not recognise; it supports {supported}"
        )


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
