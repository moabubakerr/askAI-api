"""The rules are data, they are validated at startup, and a bad file stops the service.

Three properties are asserted here, and they are the three AD-11 rests on:

1. **Loaded, not defaulted.** Every packaged rule answers to one schema, carries a
   status it stated for itself, and can name the file it came from (FR-70).
2. **Fail to start.** Missing, malformed, or schema-violating -- each raises, and each
   message names the file and the constraint. A loader that limped on would leave the
   engine answering by logic nobody can see, which is the founding defect.
3. **No reader-affecting constant is a code literal.** The scan at the end of this file
   watches ``compile/``, ``execute/`` and ``assemble/`` for the literal that would make
   the rule files decorative. Those packages are empty today; the scan is written so it
   keeps biting as they fill.

The fixtures below build rule directories by hand rather than mutating the packaged
ones: a test that edits ``src/askai/rules/data/`` to prove a failure mode can leave the
tree broken when it is interrupted.
"""

from __future__ import annotations

import ast
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from askai.rules import (
    DATA_DIR,
    Rule,
    RuleKind,
    RuleLoadError,
    RuleRejectedError,
    RuleStatus,
    load_rules,
    rules,
)
from askai.rules.cli import main, render
from askai.rules.schema import RULE_ID_PATTERN, RuleFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"

# The packages whose constants a reader sees in an answer. AD-11 names exactly these
# three for the scan; `narrate/` and `respond/` compose from what they are handed.
READER_FACING_PACKAGES = ("compile", "execute", "assemble")

# Literals that carry no reader-affecting decision: an empty container, an index, a
# count of none or one. Anything else in those packages is a number a reader can see.
INNOCUOUS_NUMBERS = frozenset({0, 1})

# Names a module may bind to a literal without it being business logic. Deliberately
# tiny, and each entry needs an argument made in review -- the exemption list is how
# this test stops working.
LITERAL_NAME_EXEMPTIONS = frozenset({"__all__"})

A_VALID_RULE = """
area: TEST
about: a directory built by a test, holding one rule
rules:
  - id: R-TEST-ONE
    statement: A statement long enough to be a statement rather than a label.
    status: proposed
    kind: constant
    sources: ["tests/test_rules.py"]
    values:
      threshold: 7
"""


def write_rules(directory: Path, name: str = "test.yaml", body: str = A_VALID_RULE) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------- the packaged rules


def test_the_packaged_rules_load() -> None:
    """The startup path, run as the service runs it."""
    assert len(load_rules()) > 0


def test_every_packaged_rule_is_enumerable() -> None:
    """FR-70: id, statement, and the file it came from -- for every rule, with no gaps."""
    for entry in rules():
        assert RULE_ID_PATTERN.fullmatch(entry.id), f"{entry.id} is not R-<AREA>-<SLUG>"
        assert entry.statement.strip()
        assert entry.source_file.is_file()
        assert entry.source_file.parent == DATA_DIR


def test_every_packaged_rule_states_its_own_status() -> None:
    """Read, never defaulted.

    The catalogue records a status for all 188 of its rules and **none of them is
    ``agreed``**; a rule here claiming agreement would be code asserting agreement on a
    stakeholder's behalf, which is what FR-72a exists to prevent. This asserts the
    weaker, durable half -- the status is one of the three and came out of the file --
    and the stronger half is asserted by the file itself failing to load without one.
    """
    for entry in rules():
        assert entry.status in set(RuleStatus)


def test_the_epic_one_rules_are_present_as_data() -> None:
    """Grain selection, latest value and display rounding exist in ``rules/``, not in code."""
    by_id = rules().by_id
    for rule_id in (
        "R-GRAIN-COARSEST-WITH-ENOUGH-READINGS",
        "R-GRAIN-PERIODLESS-WINDOW",
        "R-LATEST-MOST-RECENT-ACTUAL",
        "R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT",
        "R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL",
    ):
        assert rule_id in by_id, f"{rule_id} is missing from {DATA_DIR}"


def test_the_reader_affecting_constants_are_reachable_by_name() -> None:
    """The one door to a constant. If this works, no layer needs a literal."""
    rule_set = rules()
    assert rule_set.value("R-GRAIN-COARSEST-WITH-ENOUGH-READINGS", "minimum_readings") == 3
    assert rule_set.value("R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL", "decimals") == 0
    assert rule_set.value("R-LATEST-MOST-RECENT-ACTUAL", "measure") == "actual"
    assert rule_set.value("R-GRAIN-PERIODLESS-WINDOW", "window_years") == {
        "monthly": 3,
        "quarterly": 6,
        "yearly": 10,
    }


def test_rules_is_cached_but_load_rules_is_not() -> None:
    """The set is read once per process; the loader itself stays callable per directory."""
    assert rules() is rules()
    assert load_rules() is not load_rules()


# --------------------------------------------------------------- loaded, never fired


def test_a_rejected_rule_is_loaded_and_enumerated() -> None:
    """``R-157`` exists so it is not re-proposed. Dropping it at load would lose that."""
    entry = rules().get("R-LATEST-PER-MEMBER-ON-NEWER-ROW")
    assert entry.status is RuleStatus.REJECTED
    assert entry.rule.withdrawn_because is not None


def test_a_rejected_rule_never_fires() -> None:
    with pytest.raises(RuleRejectedError) as excinfo:
        rules().fire("R-LATEST-PER-MEMBER-ON-NEWER-ROW")
    assert "R-LATEST-PER-MEMBER-ON-NEWER-ROW" in str(excinfo.value)
    assert "re-proposed" in str(excinfo.value)


def test_the_loader_does_not_gate_on_status(tmp_path: Path) -> None:
    """``agreed`` and ``proposed`` fire identically.

    This is the assertion that makes *"a rule moving to `agreed` needs no code change"*
    true rather than intended: were the loader to require agreement, every rule in the
    catalogue would be inert today, and were it to require `proposed`, agreement would
    break the engine. Only ``rejected`` is treated differently anywhere.
    """
    for status in (RuleStatus.AGREED, RuleStatus.PROPOSED):
        write_rules(tmp_path, body=A_VALID_RULE.replace("status: proposed", f"status: {status}"))
        rule_set = load_rules(tmp_path)
        assert rule_set.fire("R-TEST-ONE").status is status
        assert rule_set.value("R-TEST-ONE", "threshold") == 7


def test_a_rejected_rule_must_say_why_it_was_withdrawn() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Rule.model_validate(
            {
                "id": "R-TEST-WITHDRAWN",
                "statement": "A statement long enough to be a statement rather than a label.",
                "status": "rejected",
                "kind": "code",
                "sources": ["tests/test_rules.py"],
            }
        )
    assert "withdrawn_because" in str(excinfo.value)


# --------------------------------------------------------------- fail to start


def test_a_missing_rule_directory_fails_to_start(tmp_path: Path) -> None:
    missing = tmp_path / "not-here"
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(missing)
    assert str(missing) in str(excinfo.value)


def test_an_empty_rule_directory_fails_to_start(tmp_path: Path) -> None:
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(tmp_path) in str(excinfo.value)
    assert "no *.yaml" in str(excinfo.value)


def test_malformed_yaml_names_the_file(tmp_path: Path) -> None:
    path = write_rules(tmp_path, "broken.yaml", "area: TEST\n  rules: [\n")
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "not readable YAML" in str(excinfo.value)


def test_a_file_that_is_not_a_mapping_names_the_file(tmp_path: Path) -> None:
    path = write_rules(tmp_path, "list.yaml", "- id: R-TEST-ONE\n")
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "mapping" in str(excinfo.value)


def test_a_missing_status_fails_to_start_naming_the_field(tmp_path: Path) -> None:
    """The status is read from the file. Nothing supplies one when the file does not."""
    path = write_rules(tmp_path, body=A_VALID_RULE.replace("    status: proposed\n", ""))
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "status" in str(excinfo.value)


def test_an_unknown_status_fails_to_start(tmp_path: Path) -> None:
    path = write_rules(tmp_path, body=A_VALID_RULE.replace("proposed", "ratified"))
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "status" in str(excinfo.value)


def test_a_misspelled_key_fails_to_start(tmp_path: Path) -> None:
    """The way a rule silently stops carrying what its author thought it carried."""
    path = write_rules(tmp_path, body=A_VALID_RULE.replace("statement:", "statment:"))
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "statment" in str(excinfo.value)


def test_a_malformed_id_fails_to_start(tmp_path: Path) -> None:
    path = write_rules(tmp_path, body=A_VALID_RULE.replace("R-TEST-ONE", "TEST_ONE"))
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "id" in str(excinfo.value)


def test_a_rule_filed_under_another_area_fails_to_start(tmp_path: Path) -> None:
    path = write_rules(tmp_path, body=A_VALID_RULE.replace("R-TEST-ONE", "R-OTHER-ONE"))
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "area" in str(excinfo.value)


def test_a_reused_id_across_files_fails_to_start(tmp_path: Path) -> None:
    """Ids are stable and never reused -- including by a second file."""
    first = write_rules(tmp_path, "a.yaml")
    second = write_rules(tmp_path, "b.yaml")
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(second) in str(excinfo.value)
    assert first.name in str(excinfo.value)


def test_a_partial_grain_table_fails_to_start(tmp_path: Path) -> None:
    """A window table missing a grain falls through to a default living in code."""
    body = A_VALID_RULE.replace(
        "      threshold: 7\n",
        "      window_years:\n        monthly: 3\n        yearly: 10\n",
    )
    path = write_rules(tmp_path, body=body)
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)
    assert "quarterly" in str(excinfo.value)


def test_a_non_data_rule_may_not_carry_values() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Rule.model_validate(
            {
                "id": "R-TEST-PRINCIPLE",
                "statement": "A statement long enough to be a statement rather than a label.",
                "status": "proposed",
                "kind": RuleKind.PRINCIPLE.value,
                "sources": ["tests/test_rules.py"],
                "values": {"threshold": 7},
            }
        )
    assert "values" in str(excinfo.value)


def test_a_file_with_no_rules_fails_to_start(tmp_path: Path) -> None:
    path = write_rules(tmp_path, body="area: TEST\nabout: an empty file\nrules: []\n")
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert str(path) in str(excinfo.value)


def test_an_unknown_rule_is_a_lookup_error_naming_the_directory() -> None:
    with pytest.raises(LookupError) as excinfo:
        rules().get("R-GRAIN-NOT-A-RULE")
    assert "R-GRAIN-NOT-A-RULE" in str(excinfo.value)


def test_an_unknown_value_names_the_clauses_the_rule_does_carry() -> None:
    with pytest.raises(LookupError) as excinfo:
        rules().value("R-GRAIN-PERIODLESS-WINDOW", "window_months")
    assert "window_years" in str(excinfo.value)


def test_the_schema_is_shared_rather_than_invented_per_file() -> None:
    """One schema owned by ``rules/``: every packaged file validates against ``RuleFile``."""
    files = sorted(DATA_DIR.glob("*.yaml"))
    assert files, f"{DATA_DIR} holds no rule files"
    for path in files:
        assert RuleFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------- the enumerate command


def test_enumerate_prints_id_statement_and_file_for_every_rule() -> None:
    out = io.StringIO()
    render(rules(), out)
    printed = out.getvalue()
    for entry in rules():
        assert entry.id in printed
        assert entry.statement.split()[0] in printed
        assert entry.source_file.name in printed


def test_enumerate_prints_the_status_tally_including_the_agreed_count() -> None:
    """The standing gap is in the output, not hidden by it (FR-72a)."""
    out = io.StringIO()
    render(rules(), out)
    printed = out.getvalue()
    assert "agreed" in printed
    assert "rejected" in printed


def test_enumerate_exits_zero() -> None:
    assert main([]) == 0


def test_enumerate_rejects_arguments() -> None:
    assert main(["--all"]) == 2


def test_enumerate_runs_as_a_command() -> None:
    """``python -m askai.rules`` -- the command an operator actually types."""
    result = subprocess.run(
        [sys.executable, "-m", "askai.rules"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "R-LATEST-MOST-RECENT-ACTUAL" in result.stdout


# --------------------------------------------------------------- no constant in code


def _module_files(package: str) -> list[Path]:
    return sorted((PACKAGE_ROOT / package).rglob("*.py"))


def _literal_constants(tree: ast.Module) -> list[tuple[str, int]]:
    """Module-level names bound to a literal -- the classic home of a business constant."""
    found: list[tuple[str, int]] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None or not _is_literal(value):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id not in LITERAL_NAME_EXEMPTIONS:
                found.append((target.id, node.lineno))
    return found


def _is_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_is_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(item is not None and _is_literal(item) for item in [*node.keys, *node.values])
    return False


def _magic_numbers(tree: ast.Module) -> list[tuple[str, int]]:
    """Numeric literals other than 0 and 1, anywhere in the module.

    A threshold, a window, a decimal count and a minimum row count all look like this,
    and each is a rule the reader is entitled to read in ``rules/`` rather than in a
    diff. Zero and one are indices and emptiness checks, not decisions.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            if isinstance(node.value, bool) or node.value in INNOCUOUS_NUMBERS:
                continue
            found.append((repr(node.value), node.lineno))
    return found


@pytest.mark.parametrize("package", READER_FACING_PACKAGES)
def test_no_reader_affecting_constant_is_a_code_literal(package: str) -> None:
    """AD-11, asserted rather than trusted.

    ``compile/``, ``execute/`` and ``assemble/`` hold only their ``__init__`` today, so
    this passes vacuously in Epic 1 -- and it is written as a scan of whatever those
    packages contain, so it starts biting the first time one of them gains a module. A
    constant that genuinely belongs in code goes in ``LITERAL_NAME_EXEMPTIONS`` with the
    argument for it, which is a line a reviewer sees.
    """
    offences: list[str] = []
    for path in _module_files(package):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(PACKAGE_ROOT)
        offences += [
            f"{where}:{line} binds {name} to a literal" for name, line in _literal_constants(tree)
        ]
        offences += [
            f"{where}:{line} uses the literal {text}" for text, line in _magic_numbers(tree)
        ]
    assert not offences, (
        "a reader-affecting constant belongs in src/askai/rules/data/*.yaml, read through "
        "rules().value(...), not in code (AD-11):\n  " + "\n  ".join(offences)
    )


def test_the_scan_would_catch_a_literal(tmp_path: Path) -> None:
    """The scan's own smoke test -- otherwise Epic 1's empty packages prove nothing."""
    module = tmp_path / "rounding.py"
    module.write_text("DISPLAY_DECIMALS = 2\n\n\ndef cap() -> int:\n    return 42\n", "utf-8")
    tree = ast.parse(module.read_text(encoding="utf-8"))
    assert _literal_constants(tree) == [("DISPLAY_DECIMALS", 1)]
    assert _magic_numbers(tree) == [("2", 1), ("42", 5)]
