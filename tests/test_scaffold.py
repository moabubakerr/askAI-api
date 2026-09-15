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

from corpus_runner import CORPUS_DIR, CorpusError, load_corpus, main, run_corpus

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
    "validate": "pure",
    "execute": "IO, via ports only",
    "assemble": "pure",
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
