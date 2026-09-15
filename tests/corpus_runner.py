"""The corpus runner.

Loads every ``corpus/*.yaml`` and ``corpus/*.yml``, parses each entry and
executes it. A file must parse to a list of mappings whose keys are strings, and
an entry must declare a ``spec_version`` this runner recognises.

Since Story 1.11, executing an entry also **compiles its question**, in every
language the entry asks it in, through the one binder -- and asserts the three
properties that are the binder's own, rather than the catalogue's: compiling is
total (a question the engine cannot resolve produces a spec whose fields are
``Unbound``, never an exception), every field is bound exactly once with its
precedence recorded, and the same question with the same history and the same
``today`` compiles to an **identical** spec on every run (NFR-1, AD-17).

The catalogue the corpus compiles against is deliberately **empty**: the read
model is ingested by another story, and an entry must not start passing or
failing because of what happens to be in a database. What an entry asserts about
a *resolved* detail arrives with the typed elements in 1.13.

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
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import BoundBy, CompiledQuestion
from askai.compile.catalogue import SnapshotCatalogue
from askai.domain.spec import SPEC_VERSION, Measure, Operation

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


#: The catalogue every corpus question compiles against: nothing published.
#:
#: Compiling against an empty catalogue is not a weaker test, it is a different one.
#: It asserts the properties the binder owns on its own -- totality, one binder per
#: field, and determinism -- and it asserts them for every entry on a machine with no
#: database, which is what "every test in this epic passes with no infrastructure"
#: means. The entries that turn on a *resolved* detail assert that where the resolution
#: lives, not here.
EMPTY_CATALOGUE = SnapshotCatalogue()


def run_entry(entry: CorpusEntry) -> None:
    """Execute one entry: check its declared shape, then compile every question on it.

    Never asserts on prose -- only on the ``QuerySpec`` and the account of how its
    fields were bound.
    """
    _check_spec_version(entry)
    _check_declared_enums(entry)
    for compiled in _compile_every_question(entry):
        _check_bound_once_and_never_by_a_model(entry, compiled)


def _check_spec_version(entry: CorpusEntry) -> None:
    """Reject an entry written against a spec shape this runner does not know.

    Absence is tolerated only where there is nothing to assert. Since Story 1.11 an
    entry carrying a question block compiles to a ``QuerySpec``, and *that* entry must
    declare the shape it was written against -- checked where the compiling happens. An
    entry with no question asserts nothing, so it has no shape to be stale against. A
    version that is *present* and unrecognised is rejected here whatever the entry
    carries, naming the file, the entry and both versions.
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


def _check_declared_enums(entry: CorpusEntry) -> None:
    """``operation`` and ``measure`` name domain members, or nothing at all.

    ``measure: null`` is meaningful and is not a missing value: it says no ``Measure``
    member applies, because the question asks for nothing numeric. A *misspelled*
    member is the failure this catches -- an entry asserting against a member that does
    not exist would otherwise be discovered by the story that starts reading it.
    """
    declared_operation = entry.data.get("operation")
    if declared_operation is not None and declared_operation not in set(Operation):
        raise CorpusError(
            f"{entry.source}: entry {entry.index} declares operation "
            f"{declared_operation!r}, which is not a member of Operation"
        )
    declared_measure = entry.data.get("measure")
    if declared_measure is not None and declared_measure not in set(Measure):
        raise CorpusError(
            f"{entry.source}: entry {entry.index} declares measure {declared_measure!r}, "
            "which is not a member of Measure (null means no member applies)"
        )


def _asked(entry: CorpusEntry, key: str) -> dict[str, str]:
    """One ``{language: text}`` block off the entry, checked rather than assumed.

    An entry whose ``question`` is a bare string is the minimal shape the loader has
    always accepted: it names no language and pins no date, so there is nothing to
    compile deterministically and nothing here to compile it against. Every entry under
    ``corpus/`` uses the mapping shape and is compiled; ``tests/test_compile.py``
    asserts that, so the seam cannot quietly stop compiling anything.
    """
    block = entry.data.get(key)
    if block is None or isinstance(block, str):
        return {}
    if not isinstance(block, dict) or not block:
        raise CorpusError(
            f"{entry.source}: entry {entry.index} has `{key}` as "
            f"{type(block).__name__}; it is a mapping of language to the question asked"
        )
    asked: dict[str, str] = {}
    for language, text in block.items():
        if not isinstance(language, str) or not isinstance(text, str) or not text.strip():
            raise CorpusError(
                f"{entry.source}: entry {entry.index} has an empty or non-text question "
                f"under `{key}.{language!r}`"
            )
        asked[language] = text
    return asked


def _today(entry: CorpusEntry) -> date:
    """The entry's pinned date.

    Required, and required to be a date rather than a timestamp: determinism is the
    property being asserted, and a time of day would make the same entry compile to two
    specs on one day (AD-17, and ``QuerySpec`` refuses a ``datetime`` for that reason).
    """
    value = entry.data.get("today")
    if not isinstance(value, date) or isinstance(value, datetime):
        raise CorpusError(
            f"{entry.source}: entry {entry.index} has `today` as "
            f"{type(value).__name__}; every entry pins a plain date (YYYY-MM-DD), "
            "because a spec is only reproducible against the day it was compiled for"
        )
    return value


def _history(entry: CorpusEntry, language: str) -> tuple[str, ...]:
    """The earlier turns of this entry, in the language being compiled, oldest first."""
    turns = entry.data.get("history") or []
    if not isinstance(turns, list):
        raise CorpusError(
            f"{entry.source}: entry {entry.index} has `history` as "
            f"{type(turns).__name__}; history is a list of earlier turns"
        )
    return tuple(
        turn[language]
        for turn in turns
        if isinstance(turn, dict) and isinstance(turn.get(language), str)
    )


def _compile_every_question(entry: CorpusEntry) -> list[CompiledQuestion]:
    """Compile the entry in every language it is asked in, twice, and require agreement.

    Twice is the point. NFR-1 makes determinism a gate rather than an aspiration: the
    same question, history and ``today`` must compile to an identical spec, and a
    difference is a failing corpus rather than tolerated variance.
    """
    asked = _asked(entry, "question")
    if not asked:
        return []
    if "spec_version" not in entry.data:
        supported = ", ".join(str(version) for version in sorted(SUPPORTED_SPEC_VERSIONS))
        raise CorpusError(
            f"{entry.source}: entry {entry.index} asks a question and so compiles to a "
            f"QuerySpec, but declares no spec_version; state the shape it was written "
            f"against ({supported})"
        )
    today = _today(entry)
    compiled: list[CompiledQuestion] = []
    for language, text in sorted(asked.items()):
        request = CompileInput(
            question=text, today=today, history=_history(entry, language)
        )
        first = compile_question(request, EMPTY_CATALOGUE)
        again = compile_question(request, EMPTY_CATALOGUE)
        if first != again:
            raise CorpusError(
                f"{entry.source}: entry {entry.index} ({language}) compiled to two "
                f"different specs on one run:\n  {first.spec}\n  {again.spec}"
            )
        if first.spec.today != today:
            raise CorpusError(
                f"{entry.source}: entry {entry.index} ({language}) pinned {today} and "
                f"compiled against {first.spec.today}; `today` is an input, never a clock"
            )
        if first.spec.spec_version != entry.data["spec_version"]:
            raise CorpusError(
                f"{entry.source}: entry {entry.index} ({language}) declares spec_version "
                f"{entry.data['spec_version']} and compiled to {first.spec.spec_version}"
            )
        compiled.append(first)
    return compiled


def _check_bound_once_and_never_by_a_model(
    entry: CorpusEntry, compiled: CompiledQuestion
) -> None:
    """AD-19 and FR-14: one binder per field, each saying whose authority it carries.

    "Exactly one binder per field" is enforced by ``CompiledQuestion`` itself, so
    reaching this point has already proved it. What is left to assert is the epic's own
    claim: **no field is ever bound by a model here, because this epic makes no model
    call.** The day one does, this fails and the epic that added it says so out loud.
    """
    for binding in compiled.bindings:
        if binding.bound_by is BoundBy.MODEL:
            raise CorpusError(
                f"{entry.source}: entry {entry.index} bound {binding.field.value} by a "
                "model; no field is bound by a model in this epic, which makes no model call"
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
    print(
        f"corpus: {count} entries collected from {corpus_dir}, all structurally valid "
        "and every question compiled to one deterministic QuerySpec"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
