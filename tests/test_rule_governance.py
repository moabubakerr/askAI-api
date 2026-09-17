"""Story 10.3 -- a rule change is a reviewed change, and the trail it leaves.

FR-73 asks that a rule change be reviewable with an audit trail rather than a code edit.
While the operator surface is deferred, the trail is the commit -- and a commit is only
an audit trail if the thing it changes is a file, reviewed, in version control. That is
what is checked here: the rules are data, the data is in the repository, the ids in it
are never reused, and the corpus gates a change to any of it.

`R-GOV-CHANGING-A-RULE-NEEDS-THE-REPOSITORY` records the cost of the deferral. It is a
principle with no clause for the engine to read, so the assertion about it is the one
that matters: that it is still there, still says so, and cannot be dropped quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from askai.rules.loader import DATA_DIR, RuleSet, rules
from askai.rules.schema import RuleKind, RuleStatus

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


def test_a_rule_change_is_a_change_to_a_reviewed_file(rule_set: RuleSet) -> None:
    """The audit trail is the commit, which requires the rule to be a file under review."""
    reviewed = "R-GOV-A-RULE-CHANGE-IS-A-REVIEWED-COMMIT"
    assert rule_set.value(reviewed, "the_commit_is_the_audit_trail")
    for entry in rule_set:
        assert entry.source_file.is_file()
        assert entry.source_file.parent == DATA_DIR
        assert entry.source_file.suffix == ".yaml"


def test_the_corpus_gates_a_rule_change(rule_set: RuleSet) -> None:
    """AD-11 and AD-29: a rule is behaviour, so it answers to the same build gate as code."""
    assert rule_set.value("R-GOV-A-RULE-CHANGE-RUNS-THE-CORPUS", "the_corpus_gates_a_rule_change")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "corpus_runner.py" in workflow, "the corpus gate is claimed by a rule and must run"


def test_a_retired_id_is_never_taken_by_a_live_rule(rule_set: RuleSet) -> None:
    """FR-70: an id names one rule for the life of the catalogue.

    The ledger is empty and is meant to stay empty -- withdrawal keeps a rule visible,
    which is what `R-LATEST-PER-MEMBER-ON-NEWER-ROW` is for. The check exists so that if
    someone ever does delete one outright, the id cannot be handed to a later rule by an
    author who found it unused.
    """
    retired = rule_set.value("R-GOV-A-RULE-ID-IS-NEVER-REUSED", "retired_ids")
    assert isinstance(retired, tuple)
    assert not set(retired) & set(rule_set.by_id)


def test_the_enumerable_list_reflects_every_file_on_disk(rule_set: RuleSet) -> None:
    """FR-70 again: the list an operator can print is the set that is actually loaded."""
    on_disk = {
        rule["id"]
        for path in DATA_DIR.glob("*.yaml")
        for rule in yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]
    }
    assert on_disk == set(rule_set.by_id)


def test_the_cost_of_the_deferred_panel_is_recorded(rule_set: RuleSet) -> None:
    """A cost accepted in a conversation is a cost nobody can find later."""
    entry = rule_set.get("R-GOV-CHANGING-A-RULE-NEEDS-THE-REPOSITORY")
    assert entry.rule.kind is RuleKind.PRINCIPLE
    assert not entry.rule.values, "a principle holds no clause the engine reads"
    assert "out of reach" in entry.statement


def test_the_governance_rules_are_proposed_and_say_why(rule_set: RuleSet) -> None:
    """Agreement covered the 188 catalogue rules. These were written afterwards.

    Recording them as agreed would manufacture an approval for a rule nobody had seen,
    which is the failure FR-72a exists to prevent -- and they fire regardless, because
    nothing gates on status.
    """
    governance = [entry for entry in rule_set if entry.rule.area == "GOV"]
    assert governance
    for entry in governance:
        assert entry.status is RuleStatus.PROPOSED
        assert entry.rule.is_fireable
        assert not entry.rule.is_attributed
