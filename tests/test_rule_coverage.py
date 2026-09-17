"""Stories 10.1, 10.2 and 10.7 -- the evidence link, the approver field, and the gate.

The gate itself runs here, which is the point: FR-71 asks for evidence that runs on
every build rather than on request, and the cheapest way to satisfy that is for the
coverage report to be produced by a test in the suite CI already runs.

What is asserted, and why each is worth a test:

* an id in a test that names no rule fails the scan -- that is what makes the link a
  link, rather than a string that used to mean something;
* a rule's evidence is the inversion of those names, so nothing is written twice;
* the gate never prints a percentage over an empty agreed set (TEA risk BUS-1), and it
  starts counting the moment a rule is agreed, with no code change;
* the withdrawn rule is excluded from every denominator **and** asserted not to fire --
  convention 7's inverted criterion;
* the approver field exists, is empty, and is reported as empty.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from askai.rules.coverage import (
    CatalogueRegister,
    Coverage,
    main,
    measure,
    read_catalogue,
    render,
)
from askai.rules.evidence import (
    FIXTURE_IDS,
    EvidenceError,
    collect_evidence,
    rules_without_evidence,
)
from askai.rules.loader import RuleRejectedError, RuleSet, rules
from askai.rules.schema import Rule, RuleKind, RuleStatus

ROOT = Path(__file__).resolve().parents[1]

# Ids that name no rule are assembled rather than written. The scanner reads this file's
# text, so a literal here would be a link to a rule that does not exist -- which is the
# very thing it refuses. Assembling them keeps the negative cases out of the index and
# keeps the positive ones (R-PARITY-..., R-LATEST-PER-MEMBER-ON-NEWER-ROW below) real.
_ABSENT = "R-" + "INVENTED" + "-NOTHING"
_SAMPLE = "R-" + "GOV" + "-SAMPLE"


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


@pytest.fixture(scope="module")
def coverage(rule_set: RuleSet) -> Coverage:
    return measure(rule_set)


def _rule(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": _SAMPLE,
        "statement": "A statement long enough to answer the schema's minimum length.",
        "status": "agreed",
        "kind": RuleKind.SWITCH.value,
        "sources": ["tests/test_rule_coverage.py"],
    }
    return base | overrides


# ------------------------------------------------------------------ 10.1: the link


def test_every_evidence_link_names_a_rule_that_exists(rule_set: RuleSet) -> None:
    """The scan over the real tree. A typo'd or renamed id fails here and nowhere else."""
    index = collect_evidence(rule_set)
    assert index.by_rule, "the suite should name rules by id; nothing does"
    for rule_id in index.by_rule:
        assert rule_id in rule_set.by_id


def test_a_test_naming_an_unknown_rule_fails_the_scan(rule_set: RuleSet, tmp_path: Path) -> None:
    (tmp_path / "test_invented.py").write_text(f'RULE = "{_ABSENT}"\n', encoding="utf-8")
    with pytest.raises(EvidenceError) as caught:
        collect_evidence(rule_set, tests_dir=tmp_path, corpus_dir=tmp_path)
    assert _ABSENT in str(caught.value)
    assert "test_invented.py" in str(caught.value)


def test_a_corpus_entry_links_to_the_rules_it_exercises(rule_set: RuleSet) -> None:
    """`corpus/epic-10.yaml` names, in its parity pair, the rules that pair exercises."""
    index = collect_evidence(rule_set)
    where = index.for_rule("R-PARITY-EVERY-CAPABILITY-IS-ASKED-IN-BOTH")
    assert "epic-10.yaml" in where, where


def test_no_fixture_id_is_a_real_rule(rule_set: RuleSet) -> None:
    """The exemption list is checked from the other side.

    A handful of tests invent rule ids to build malformed files with. They are skipped
    by the scan, and the skip is only safe while none of them names a rule -- otherwise
    an entry there would silently absorb a link to a rule that was renamed.
    """
    assert not FIXTURE_IDS & set(rule_set.by_id)


def test_a_rule_nothing_names_is_reported_by_name(rule_set: RuleSet) -> None:
    """FR-71: the gap is specific rather than a number."""
    index = collect_evidence(rule_set)
    without = rules_without_evidence(rule_set, index)
    assert set(without) <= set(rule_set.by_id)
    assert all(rule_set.get(rule_id).rule.is_fireable for rule_id in without)


def test_evidence_is_absent_rather_than_fatal_where_there_is_no_checkout(
    rule_set: RuleSet, tmp_path: Path
) -> None:
    """An installed engine has no `tests/`; the honest report for that is *none found*."""
    index = collect_evidence(rule_set, tests_dir=tmp_path / "gone", corpus_dir=tmp_path / "gone")
    assert index.by_rule == {}


# ------------------------------------------------------- 10.7: honest about zero


def test_the_gate_never_reports_a_percentage_over_an_empty_agreed_set() -> None:
    empty = Coverage(
        fireable=188,
        agreed=0,
        attributed=0,
        rejected=("R-LATEST-PER-MEMBER-ON-NEWER-ROW",),
        with_evidence=(),
        without_evidence=(),
        encoded_from_catalogue=(),
        register=CatalogueRegister(ids=(), rejected=()),
    )
    assert not empty.evidence_is_measurable
    with pytest.raises(ValueError, match="empty agreed set"):
        _ = empty.evidence_percent

    out = StringIO()
    render(empty, out)
    printed = out.getvalue()
    assert "n/a -- 0 of 188 agreed" in printed
    assert "%" not in printed, "no percentage of any kind is printed over an empty set"


def test_the_gate_activates_on_the_first_agreed_rule_with_no_code_change() -> None:
    one = Coverage(
        fireable=188,
        agreed=1,
        attributed=0,
        rejected=(),
        with_evidence=("R-GOV-A-RULE-ID-IS-NEVER-REUSED",),
        without_evidence=(),
        encoded_from_catalogue=(),
        register=CatalogueRegister(ids=(), rejected=()),
    )
    assert one.evidence_is_measurable
    assert one.evidence_percent == 100
    assert "1 of 1 agreed" in _rendered(one)


def test_a_withdrawn_rule_is_in_no_denominator(coverage: Coverage) -> None:
    assert coverage.rejected, "the catalogue retains a withdrawn rule; it should be visible"
    assert coverage.agreed <= coverage.fireable
    for rule_id in coverage.rejected:
        assert rule_id not in coverage.with_evidence
        assert rule_id not in coverage.without_evidence


def test_the_withdrawn_rule_does_not_fire(rule_set: RuleSet, coverage: Coverage) -> None:
    """The inverted acceptance criterion (convention 7): it is retained, and it is inert."""
    for rule_id in coverage.rejected:
        assert rule_id in rule_set.by_id, "a withdrawn rule is retained, not deleted"
        assert rule_set.get(rule_id).rule.withdrawn_because
        with pytest.raises(RuleRejectedError):
            rule_set.fire(rule_id)


def test_the_report_names_the_organisational_gate(coverage: Coverage) -> None:
    printed = _rendered(coverage)
    assert "organisational gate (FR-72a)" in printed
    assert "UNRECORDED" in printed


def test_the_catalogue_supplies_the_implementation_denominator() -> None:
    """Coverage over encoded rules alone would flatter; the denominator is the catalogue's."""
    register = read_catalogue()
    assert register.is_available, "docs/RULES.md should be readable from a checkout"
    assert len(register.ids) == 188
    assert len(register.rejected) == 0 or register.live < len(register.ids)


def test_an_absent_catalogue_is_reported_rather_than_guessed(tmp_path: Path) -> None:
    register = read_catalogue(tmp_path / "RULES.md")
    assert not register.is_available
    printed = _rendered(measure(register=register))
    assert "catalogue denominator is unknown" in printed


def test_the_gate_runs_as_a_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "askai.rules.coverage"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "rule coverage" in result.stdout


def test_the_gate_rejects_arguments() -> None:
    assert main(["--everything-is-fine"]) == 2


# ----------------------------------------------------------- 10.2: the approver


def test_the_approver_field_exists_and_is_empty(rule_set: RuleSet) -> None:
    """Built, left null, and said out loud. Nobody was named, so nobody is recorded."""
    assert "agreed_by" in Rule.model_fields
    assert "agreed_on" in Rule.model_fields
    for entry in rule_set:
        assert entry.rule.agreed_by is None, f"{entry.id} names an approver nobody appointed"
        assert entry.rule.agreed_on is None
        assert not entry.rule.is_attributed


def test_an_approver_without_a_date_is_refused() -> None:
    with pytest.raises(ValidationError, match="half of its approval"):
        Rule.model_validate(_rule(agreed_by="a person with standing"))


def test_a_date_without_an_approver_is_refused() -> None:
    with pytest.raises(ValidationError, match="half of its approval"):
        Rule.model_validate(_rule(agreed_on=date(2026, 9, 16)))


def test_a_proposed_rule_may_not_name_an_approver() -> None:
    with pytest.raises(ValidationError, match="names an approver"):
        Rule.model_validate(
            _rule(status="proposed", agreed_by="a person", agreed_on=date(2026, 9, 16))
        )


def test_an_attributed_rule_is_accepted_and_reported_as_attributed() -> None:
    """The day someone is named, the move is a two-line data edit and the report changes."""
    rule = Rule.model_validate(
        _rule(agreed_by="a person with standing", agreed_on=date(2026, 9, 16))
    )
    assert rule.is_attributed
    assert rule.status is RuleStatus.AGREED


def test_coverage_counts_only_agreed_rules(rule_set: RuleSet) -> None:
    """FR-71: a proposed rule cannot inflate the number."""
    proposed = {
        entry.id for entry in rule_set if entry.status is RuleStatus.PROPOSED
    }
    assert proposed, "this tree carries proposed rules; the test is vacuous without them"
    result = measure(rule_set)
    assert not proposed & set(result.with_evidence)
    assert not proposed & set(result.without_evidence)
    assert result.agreed + len(proposed) + len(result.rejected) == len(rule_set)


def _rendered(coverage: Coverage) -> str:
    out = StringIO()
    render(coverage, out)
    return out.getvalue()
