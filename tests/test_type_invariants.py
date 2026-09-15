"""The invariants the *type checker* enforces, proven by making it fail.

Two of this story's guarantees are not statements about values, they are statements
about what does not type-check: an ``Element`` cannot be built without a ``source_ref``
(AD-6), and ``Percent`` cannot be mixed with ``pp`` (AD-4, FR-21). A runtime test
cannot assert either -- the whole point is that the code never runs.

So these tests run ``mypy --strict`` on a fixture that is *meant* to fail and assert it
does, following the plant-a-violation-and-run-a-subprocess idiom
``tests/test_dependency_contracts.py`` established. The fixtures are excluded from the
whole-tree mypy run by ``[tool.mypy] exclude``; mypy does not apply ``exclude`` to a
path named on the command line, which is what lets them be checked here.

A fixture that stopped failing would mean a default, an overload or a conversion had
been added -- which is exactly the regression these exist to catch.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "type_fixtures"


def _mypy(*arguments: str) -> subprocess.CompletedProcess[str]:
    scripts_dir = Path(sys.executable).parent
    candidates = [scripts_dir / "mypy.exe", scripts_dir / "mypy"]
    executable = next((path for path in candidates if path.is_file()), None)
    resolved = str(executable) if executable else shutil.which("mypy")
    assert resolved, "mypy is not installed; run `uv sync --locked --all-extras`"
    return subprocess.run(
        [resolved, "--strict", "--no-incremental", "--no-error-summary", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        # A stalled type-check must fail the suite, not hang it. `--no-incremental`
        # means a cold run every time, so the ceiling is generous rather than tight.
        timeout=300,
    )


NEGATIVE_FIXTURES = (
    "element_without_source_ref.py",
    "percent_mixed_with_pp.py",
)


@pytest.mark.parametrize("fixture", NEGATIVE_FIXTURES)
def test_the_fixture_exists_and_is_outside_the_main_run(fixture: str) -> None:
    path = FIXTURE_DIR / fixture
    assert path.is_file(), f"{fixture} is missing; the negative assertion cannot run"
    assert not path.name.startswith("test_"), "a fixture must not be collected by pytest"


def test_an_element_without_a_source_ref_does_not_type_check() -> None:
    """AD-6: there is no constructor that produces an element without a source_ref."""
    result = _mypy(str(FIXTURE_DIR / "element_without_source_ref.py"))
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"mypy accepted an Element with no source_ref:\n{output}"
    assert "source_ref" in output, output
    assert 'call to "Element"' in output, output


def test_percent_mixed_with_pp_does_not_type_check() -> None:
    """AD-4 / FR-21: distinct types, no implicit conversion in either direction."""
    result = _mypy(str(FIXTURE_DIR / "percent_mixed_with_pp.py"))
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"mypy accepted Percent mixed with pp:\n{output}"
    # Both directions, so a conversion added on one side only still fails here.
    assert output.count("error:") >= 2, output
    assert "Percent" in output and "PercentagePoints" in output, output


def test_the_negative_fixtures_are_excluded_from_the_whole_tree_run() -> None:
    """The acceptance criterion, asserted rather than assumed.

    ``mypy --strict src/askai tests`` must be clean *with* the fixtures on disk -- if
    the exclude were dropped, the gate CI runs would go permanently red.
    """
    result = _mypy("src/askai", "tests")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for fixture in NEGATIVE_FIXTURES:
        assert fixture not in output, f"{fixture} leaked into the whole-tree run:\n{output}"


def test_mypy_is_actually_reporting_rather_than_always_failing(tmp_path: Path) -> None:
    """A checker that fails on everything would make the two tests above meaningless."""
    clean = tmp_path / "clean_fixture.py"
    clean.write_text(
        "from decimal import Decimal\n\n"
        "from askai.domain.element import Element, ElementClass\n"
        "from askai.domain.numbers import Percent\n\n"
        'ELEMENT = Element("2.6%", ElementClass.MEASURED, "row-1")\n'
        'TOTAL = Percent(Decimal("2.6")) + Percent(Decimal("0.4"))\n',
        encoding="utf-8",
    )
    result = _mypy(str(clean))
    assert result.returncode == 0, result.stdout + result.stderr
