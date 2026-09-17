"""Which tests and corpus entries prove which rules -- read off the tree, not declared twice.

Purity: reads the repository's ``tests/`` and ``corpus/`` when asked; pure thereafter.

FR-71 asks that a rule point at the evidence that it holds, and that the link be
bidirectional: *a test names the rule ids it proves*. The obvious design is a field on
the rule listing its tests, and it is the wrong one. A list written on both sides drifts
on one of them, and the side that drifts is always the rule file, because a test that
stops proving a rule does not fail -- it passes, quietly, about something else.

So there is one side. **A test names a rule by writing its id**, in an assertion, a
parameter list or a docstring, and this module reads those names back. The rule's
evidence is the inversion, computed. Nothing is declared twice, and the link cannot rot
in the direction that does not fail: delete the test and the rule loses its evidence on
the next run of the gate.

Two consequences are deliberate:

* **A rule id in a test is a claim, and it is checked.** An id-shaped string in
  ``tests/`` that names no rule fails the scan. That is what makes the id in the test a
  link rather than a comment -- a renamed rule breaks the build at the test that named
  it, which is exactly where someone has to go and look.
* **The evidence runs on every build, because it is the test suite.** There is no
  separate evidence runner to forget to run. Coverage measures the suite CI already
  runs; a rule with evidence is a rule some test names, and that test ran.

Corpus entries link the same way and for the same reason: an entry that names a rule id
in its ``why`` is claiming to exercise it, and the claim is checked.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from askai.rules.loader import RuleSet
from askai.rules.schema import RULE_ID_PATTERN

__all__ = [
    "CORPUS_DIR",
    "FIXTURE_IDS",
    "TESTS_DIR",
    "EvidenceError",
    "EvidenceIndex",
    "collect_evidence",
    "repository_root",
]

#: The repository this package was installed from in editable form. Evidence lives in
#: the checkout rather than in the wheel: the tests are not packaged, and a deployed
#: engine has no evidence to report on -- only a build does.
_ROOT: Final = Path(__file__).resolve().parents[3]

TESTS_DIR: Final = _ROOT / "tests"
CORPUS_DIR: Final = _ROOT / "corpus"

#: An id anywhere in a test's source, including inside a docstring. The pattern is the
#: schema's own, so the two cannot disagree about what an id looks like.
_ID: Final = re.compile(RULE_ID_PATTERN.pattern)

_SUFFIX_PY: Final = ".py"

#: Ids that are fixtures rather than links, with the file that invents each one.
#:
#: A handful of tests build rule files in a ``tmp_path`` to prove the loader refuses
#: something, and the rules in them need ids. Those ids name nothing and are meant to
#: name nothing, so they are not broken links -- but this scan cannot tell them apart
#: from one, and the tests that own them are not this story's to edit.
#:
#: The list is closed and it is checked from the other side: ``test_rule_coverage.py``
#: asserts that none of these is a real rule id, so an entry here can never quietly
#: absorb a link to a rule that was renamed out from under a test.
FIXTURE_IDS: Final = frozenset(
    {
        "R-DOES-NOT-EXIST",  # test_foreclosure.py -- the id a lookup is meant to miss
        "R-DISPLAY-ROUNDING",  # test_records.py -- a stand-in in a written fixture
        "R-PERIOD-DEFAULT",  # test_records.py -- likewise
        "R-GRAIN-NOT-A-RULE",  # test_rules.py -- the malformed-file cases
        "R-OTHER-ONE",
        "R-TEST-ONE",
        "R-TEST-PRINCIPLE",
        "R-TEST-WITHDRAWN",
    }
)


class EvidenceError(Exception):
    """A test or corpus entry names a rule that does not exist.

    Fatal to the gate rather than skipped. A link to a rule id nobody defined is the
    failure mode this scan exists to catch: it reads as evidence in the report while
    proving nothing, which is worse than a rule with no evidence at all.
    """


@dataclass(frozen=True, slots=True)
class EvidenceIndex:
    """Rule id -> the test files and corpus entries that name it, in path order.

    Only links to rules that exist are ever in here: an id naming no rule has already
    stopped the scan by the time this is built, so a rule reported with no evidence is a
    rule nothing named -- never a test with a typo in it.
    """

    by_rule: Mapping[str, tuple[str, ...]]

    def for_rule(self, rule_id: str) -> tuple[str, ...]:
        """The files proving *rule_id*, in path order; empty when nothing names it."""
        return self.by_rule.get(rule_id, ())

    def covers(self, rule_id: str) -> bool:
        return bool(self.for_rule(rule_id))


def repository_root() -> Path:
    """Where ``tests/`` and ``corpus/`` live, when they live anywhere."""
    return _ROOT


def _test_sources(tests_dir: Path) -> Iterator[Path]:
    yield from sorted(
        path
        for path in tests_dir.rglob(f"*{_SUFFIX_PY}")
        if "__pycache__" not in path.parts and path.is_file()
    )


def _ids_in_text(text: str) -> frozenset[str]:
    return frozenset(match.group(0) for match in _ID.finditer(text))


def _corpus_claims(corpus_dir: Path) -> Iterator[tuple[str, str]]:
    """``(rule id, file)`` for every rule id named anywhere under *corpus_dir*.

    Read as text, exactly as a test is, rather than through a new ``proves:`` key on the
    entry: the entry shape is owned by the corpus runner and is deliberately narrow --
    an entry asserts on the ``QuerySpec`` and nothing else -- and widening it for this
    would put a second kind of thing in a mapping that is checked key by key. An id in
    an entry's ``why`` is the same claim and costs the corpus nothing.
    """
    for path in sorted(corpus_dir.glob("*.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover -- the corpus runner reports it, and better
            continue
        for rule_id in sorted(_ids_in_text(text)):
            yield rule_id, path.name


def collect_evidence(
    rule_set: RuleSet,
    *,
    tests_dir: Path | None = None,
    corpus_dir: Path | None = None,
) -> EvidenceIndex:
    """Index the evidence for *rule_set*, or raise on a link that names no rule.

    Missing directories are not an error: an installed package has no ``tests/``, and
    the honest report for that is *no evidence found*, which is what an empty index
    produces. A directory that exists and names an unknown id **is** an error.
    """
    tests = TESTS_DIR if tests_dir is None else tests_dir
    corpus = CORPUS_DIR if corpus_dir is None else corpus_dir
    known = frozenset(rule_set.by_id)

    claims: dict[str, set[str]] = {}
    unknown: list[str] = []

    def record(rule_id: str, where: str) -> None:
        if rule_id in FIXTURE_IDS:
            return
        if rule_id not in known:
            unknown.append(f"{where}: {rule_id}")
            return
        claims.setdefault(rule_id, set()).add(where)

    if tests.is_dir():
        for path in _test_sources(tests):
            for rule_id in sorted(_ids_in_text(path.read_text(encoding="utf-8"))):
                record(rule_id, path.name)
    if corpus.is_dir():
        for rule_id, where in _corpus_claims(corpus):
            record(rule_id, where)

    if unknown:
        raise EvidenceError(
            "evidence names rules that do not exist -- a rule id in a test is a link, "
            "and a broken one reads as proof while proving nothing:\n  "
            + "\n  ".join(sorted(unknown))
        )
    return EvidenceIndex(
        by_rule={key: tuple(sorted(value)) for key, value in sorted(claims.items())}
    )


def rules_without_evidence(rule_set: RuleSet, index: EvidenceIndex) -> tuple[str, ...]:
    """Every fireable rule nothing names, in id order.

    Named rather than counted, per FR-71: *"a rule with no evidence is named in the
    report, so the gap is specific rather than a number."*
    """
    return tuple(
        entry.id for entry in rule_set if entry.rule.is_fireable and not index.covers(entry.id)
    )
