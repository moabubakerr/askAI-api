"""The tree matches the spine, and every package declares its purity class.

The purity line in each package docstring is the enforceable part of the
convention set in the story's Design Notes: a package whose declared class
drifts from the layer table in ``docs/ARCHITECTURE-SPINE.md`` fails here rather
than going unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from corpus_runner import (
    CORPUS_DIR,
    SUPPORTED_SPEC_VERSIONS,
    CorpusError,
    load_corpus,
    main,
    run_corpus,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"

# The spine's layer table, verbatim. `config/` appears in the Structural Seed but
# not in the layer table, so its class is set here by this story (see the spec's
# Implementation Notes) rather than quoted.
PURITY_BY_PACKAGE = {
    "domain": "pure, imports nothing in-project",
    "rules": "pure after load",
    "messages": "data",
    "compile": "pure; calls ports for candidates",
    # Subpackages added by Epics 2-5. The spine's layer table names the top-level
    # packages; a subpackage inherits its parent's class and declares it for itself, so
    # a composer that quietly started doing IO fails here rather than in review.
    "compile/resolve": "pure; calls ``CandidatePort`` for candidates and nothing else",
    "assemble/change": "pure",
    "assemble/meta": "pure. Asks ``ports/`` and imports no adapter",
    "validate": "pure",
    "execute": "IO, via ports only",
    "assemble": "pure",
    "assemble/compare": "pure",
    "narrate": "pure guard; calls one port",
    "respond": "orchestration; orders packages, never mutates one",
    "ports": "declarations only",
    "adapters": "IO",
    "adapters/model": "IO",
    "adapters/external": "IO",
    "adapters/readmodel": "IO",
    "adapters/index": "IO",
    "adapters/store": "IO",
    "observability": "IO",
    "refresh": "IO, never on the answer path",
    "api": "edge",
    "config": "configuration; validated at startup, the only in-project reader of the environment",
}


def _docstring(init_path: Path) -> str:
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree)
    assert doc is not None, f"{init_path} has no module docstring"
    return doc


def _purity_line(doc: str) -> str:
    """The purity class, read from the first line after the ``Purity:`` marker.

    Only that line — a docstring may go on to say more without silently widening
    what this compares.
    """
    marker = "Purity:"
    assert marker in doc, "docstring does not declare a purity class"
    tail = doc.split(marker, 1)[1].lstrip()
    line = tail.splitlines()[0] if tail.splitlines() else ""
    return line.strip().removesuffix(".").strip()


@pytest.mark.parametrize("package", sorted(PURITY_BY_PACKAGE))
def test_package_exists_with_declared_purity(package: str) -> None:
    init_path = PACKAGE_ROOT.joinpath(*package.split("/")) / "__init__.py"
    assert init_path.is_file(), f"askai/{package}/__init__.py is missing"
    assert _purity_line(_docstring(init_path)) == PURITY_BY_PACKAGE[package]


def test_no_package_was_invented() -> None:
    """Nothing exists under src/askai that the spine does not name."""
    found = {
        str(path.parent.relative_to(PACKAGE_ROOT)).replace("\\", "/")
        for path in PACKAGE_ROOT.rglob("__init__.py")
    }
    found.discard(".")  # the root package itself
    assert found == set(PURITY_BY_PACKAGE)


def test_root_package_has_a_docstring() -> None:
    assert _docstring(PACKAGE_ROOT / "__init__.py")


def test_corpus_runner_is_green_on_an_empty_corpus(tmp_path: Path) -> None:
    (tmp_path / "scaffold.yaml").write_text("[]\n", encoding="utf-8")
    assert run_corpus(tmp_path) == 0
    assert load_corpus(tmp_path) == []


def test_the_real_corpus_loads() -> None:
    """The committed corpus is loadable — an assertion that survives entries being added."""
    assert CORPUS_DIR.is_dir()
    assert run_corpus() == len(load_corpus())


def test_main_reports_success_on_a_valid_corpus(tmp_path: Path) -> None:
    (tmp_path / "scaffold.yaml").write_text("[]\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0


def test_main_reports_failure_on_a_malformed_corpus(tmp_path: Path) -> None:
    """The gate's exit code, pinned.

    ``main`` is what CI runs; a swallowed CorpusError here would report success on
    a broken corpus while every other test stayed green.
    """
    (tmp_path / "broken.yaml").write_text("- 42\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 1


def test_corpus_runner_names_the_file_on_a_malformed_entry(tmp_path: Path) -> None:
    bad = tmp_path / "broken.yaml"
    bad.write_text("- 42\n", encoding="utf-8")
    with pytest.raises(CorpusError) as excinfo:
        run_corpus(tmp_path)
    assert str(bad) in str(excinfo.value)
    assert "expected a mapping" in str(excinfo.value)


def test_corpus_runner_rejects_a_file_that_is_not_a_list(tmp_path: Path) -> None:
    bad = tmp_path / "mapping.yaml"
    bad.write_text("question: what is inflation\n", encoding="utf-8")
    with pytest.raises(CorpusError) as excinfo:
        run_corpus(tmp_path)
    assert str(bad) in str(excinfo.value)
    assert "expected a list of entries" in str(excinfo.value)


# ------------------------------------------------------- spec_version (Story 1.2)


def test_the_supported_spec_version_set_starts_at_one() -> None:
    assert SUPPORTED_SPEC_VERSIONS == frozenset({1})


def test_corpus_runner_accepts_the_recognised_spec_version(tmp_path: Path) -> None:
    (tmp_path / "ok.yaml").write_text(
        "- spec_version: 1\n  question: what is inflation\n", encoding="utf-8"
    )
    assert run_corpus(tmp_path) == 1


def test_corpus_runner_rejects_an_unknown_spec_version(tmp_path: Path) -> None:
    """The gate the field exists for: a shape change fails loudly, entry by entry."""
    bad = tmp_path / "future.yaml"
    bad.write_text(
        "- spec_version: 1\n  question: first\n- spec_version: 7\n  question: second\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError) as excinfo:
        run_corpus(tmp_path)
    message = str(excinfo.value)
    assert str(bad) in message, "the rejection must name the file"
    assert "entry 1" in message, "the rejection must name the entry"
    assert "spec_version 7" in message, "the rejection must name the entry's version"
    # Pinned by its own phrasing: "1" alone is already satisfied by the substring
    # "entry 1", so dropping the supported-versions half would leave this green.
    assert "supports 1" in message, "the rejection must name the supported version"


def test_corpus_runner_rejects_a_non_integer_spec_version(tmp_path: Path) -> None:
    bad = tmp_path / "stringly.yaml"
    bad.write_text("- spec_version: '1'\n", encoding="utf-8")
    with pytest.raises(CorpusError) as excinfo:
        run_corpus(tmp_path)
    assert "not an integer" in str(excinfo.value)


def test_corpus_runner_rejects_a_boolean_spec_version(tmp_path: Path) -> None:
    """`spec_version: yes` is YAML for True, and True == 1 in Python."""
    bad = tmp_path / "boolish.yaml"
    bad.write_text("- spec_version: yes\n", encoding="utf-8")
    with pytest.raises(CorpusError) as excinfo:
        run_corpus(tmp_path)
    assert "not an integer" in str(excinfo.value)


def test_an_entry_without_a_spec_version_is_still_tolerated(tmp_path: Path) -> None:
    """The rest of the entry shape is provisional until 1.11; absence is not yet wrong."""
    (tmp_path / "legacy.yaml").write_text("- question: what is inflation\n", encoding="utf-8")
    assert run_corpus(tmp_path) == 1


def test_main_reports_failure_on_an_unknown_spec_version(tmp_path: Path) -> None:
    (tmp_path / "future.yaml").write_text("- spec_version: 99\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 1
