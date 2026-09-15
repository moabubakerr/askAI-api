"""AD-2: the dependency direction is machine-enforced, and the gate bites.

Configuring a contract is not the same as enforcing one, so these tests run
``lint-imports`` for real: green on the tree as it stands, and red once a
deliberate violation is planted. The same file also asserts the resolved
dependency tree carries no LLM orchestration framework (AD-22) and no vector
library (AD-13) — a check, not a reading.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"

# AD-22 (no orchestration framework) and AD-13 (no vector library). Adding any of
# these is a spine change, not a library choice.
FORBIDDEN_DISTRIBUTIONS = frozenset(
    {
        # LLM orchestration frameworks
        "langchain",
        "langchain-core",
        "langchain-community",
        "langgraph",
        "llama-index",
        "llama-index-core",
        "haystack-ai",
        "semantic-kernel",
        "autogen",
        "autogen-agentchat",
        "crewai",
        "dspy",
        "dspy-ai",
        "guidance",
        "litellm",
        "instructor",
        # Vector libraries and vector databases
        "faiss-cpu",
        "faiss-gpu",
        "annoy",
        "hnswlib",
        "nmslib",
        "usearch",
        "scann",
        "chromadb",
        "qdrant-client",
        "pinecone",
        "pinecone-client",
        "weaviate-client",
        "pymilvus",
        "lancedb",
        "pgvector",
        "sqlite-vec",
        "sqlite-vss",
        "txtai",
        "chroma-hnswlib",
        # Model runtimes and provider SDKs: AD-9 puts the runtime behind an adapter,
        # and the engine makes no call outside the estate.
        "torch",
        "transformers",
        "sentence-transformers",
        "openai",
        "anthropic",
    }
)

# Exact names go stale the moment a distribution is renamed or split, so the
# families are matched by prefix as well — `langchain-openai`, `llama-index-llms-*`,
# `torchvision` and their kin are caught without being listed.
FORBIDDEN_PREFIXES = (
    "langchain",
    "langgraph",
    "llama-index",
    "llama_index",
    "haystack",
    "semantic-kernel",
    "autogen",
    "crewai",
    "dspy",
    "litellm",
    "instructor",
    "guidance",
    "faiss",
    "annoy",
    "hnswlib",
    "nmslib",
    "usearch",
    "scann",
    "chroma",
    "qdrant",
    "pinecone",
    "weaviate",
    "milvus",
    "pymilvus",
    "lancedb",
    "pgvector",
    "sqlite-vec",
    "sqlite-vss",
    "txtai",
    "torch",
    "transformers",
    "sentence-transformers",
    "openai",
    "anthropic",
)


def _lint_imports() -> subprocess.CompletedProcess[str]:
    scripts_dir = Path(sys.executable).parent
    candidates = [scripts_dir / "lint-imports.exe", scripts_dir / "lint-imports"]
    executable = next((path for path in candidates if path.is_file()), None)
    resolved = str(executable) if executable else shutil.which("lint-imports")
    assert resolved, "lint-imports is not installed; run `uv sync --locked --all-extras`"
    return subprocess.run(
        [resolved],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        # import-linter's banner is box drawing; never let the console codepage
        # turn a gate result into a decode error.
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@contextmanager
def _planted(relative_path: str, source: str) -> Iterator[Path]:
    """Write a module into the package tree, and always remove it again."""
    path = PACKAGE_ROOT / relative_path
    assert not path.exists(), f"{path} already exists; refusing to overwrite"
    path.write_text(source, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_contracts_are_kept_on_the_tree_as_it_stands() -> None:
    result = _lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BROKEN" not in result.stdout


@pytest.mark.parametrize(
    ("relative_path", "violating_import", "contract"),
    [
        (
            "domain/_violation.py",
            "from askai.adapters import store",
            "domain imports nothing in-project",
        ),
        (
            "domain/_violation_config.py",
            "from askai import config",
            "domain imports nothing in-project",
        ),
        (
            "assemble/_violation.py",
            "from askai.adapters import readmodel",
            "the pure layers never reach an adapter",
        ),
    ],
)
def test_a_violating_import_fails_the_build(
    relative_path: str, violating_import: str, contract: str
) -> None:
    source = f'"""Deliberate AD-2 violation, planted by a test."""\n\n{violating_import}\n'
    with _planted(relative_path, source):
        result = _lint_imports()
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert contract in output
    assert "BROKEN" in output


def test_respond_reaching_inside_a_package_fails_the_build() -> None:
    """Reaching *inside* narrate, not merely importing it.

    The contract's point is that ``respond`` arranges finished packages and never
    touches a package's internals, so the violation has to be an import of a
    submodule. ``narrate`` has no submodules yet, so the test plants the one it
    reaches for alongside the module that reaches.
    """
    target = '"""Stand-in for a narrate internal, planted by a test."""\n'
    reacher = (
        '"""Deliberate AD-2 violation, planted by a test."""\n\n'
        "from askai.narrate import _violation_target\n"
    )
    with (
        _planted("narrate/_violation_target.py", target),
        _planted("respond/_violation.py", reacher),
    ):
        result = _lint_imports()
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "respond arranges packages, it never reaches inside one" in output
    assert "BROKEN" in output


def test_the_domain_contract_names_every_other_package() -> None:
    """The forbidden list is hand-maintained, so drift is caught here, not in review.

    A package added under ``src/askai/`` and forgotten in the contract would leave
    ``domain/`` free to import it while ``lint-imports`` still reported KEPT.
    """
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contract = next(
        item
        for item in config["tool"]["importlinter"]["contracts"]
        if item["name"] == "domain imports nothing in-project"
    )
    top_level = {path.parent.name for path in PACKAGE_ROOT.glob("*/__init__.py")}
    assert set(contract["forbidden_modules"]) == {
        f"askai.{name}" for name in top_level - {"domain"}
    }


def _resolved_distributions(lock: Path) -> set[str]:
    locked = tomllib.loads(lock.read_text(encoding="utf-8"))
    return {package["name"].lower() for package in locked.get("package", [])}


def _offenders(resolved: set[str]) -> list[str]:
    return sorted(
        name
        for name in resolved
        if name in FORBIDDEN_DISTRIBUTIONS or name.startswith(FORBIDDEN_PREFIXES)
    )


def test_the_resolved_tree_has_no_orchestration_framework_and_no_vector_library() -> None:
    lock = PROJECT_ROOT / "uv.lock"
    assert lock.is_file(), "uv.lock is the pinned resolution; it must be committed"
    offenders = _offenders(_resolved_distributions(lock))
    assert not offenders, f"forbidden dependency in the resolved tree: {', '.join(offenders)}"


def test_a_forbidden_dependency_would_be_caught_and_named(tmp_path: Path) -> None:
    """The check fires, rather than only ever passing.

    A deny-list that has never gone red is indistinguishable from one that
    cannot, so this drives it with a lockfile that does carry an offender.
    """
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "fastapi"\nversion = "0.141.1"\n\n'
        '[[package]]\nname = "LangChain"\nversion = "0.3.0"\n\n'
        '[[package]]\nname = "faiss-cpu"\nversion = "1.9.0"\n',
        encoding="utf-8",
    )
    assert _offenders(_resolved_distributions(lock)) == ["faiss-cpu", "langchain"]
