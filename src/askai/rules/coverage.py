"""The rule-coverage gate -- and its refusal to report a percentage of nothing.

Purity: reads the packaged rules, and the checkout's evidence and catalogue; prints.

Run it as ``uv run python -m askai.rules.coverage``. ``tests/test_rule_coverage.py``
runs the same function, so the number is produced on every build rather than on request
(FR-71's *continuously*).

The gate reports three separate things, and keeping them separate is the whole design:

**Agreement** -- how many loaded rules are ``agreed``, and how many of those name the
person who agreed them. Both numbers, because they have different answers: all 92
fireable rules are agreed and **not one is attributed** (FR-72a, Story 10.2). A single
"agreed" number would let a verbal agreement nobody signed read as an approval.

**Implementation** -- how many of the catalogue's 188 rules are encoded as data here.
This is the number that flatters if you let it: coverage over *encoded* rules alone is
high and means little, because the rules nobody has encoded are invisible to it. The
denominator is therefore the catalogue's, and the report says so in the same line.

**Evidence** -- how many agreed rules some test names (``evidence.py``). Over agreed
rules only, per FR-71, so a proposed rule cannot inflate it; and **never expressed as a
percentage when the denominator is zero**, which is the failure TEA risk BUS-1 names:
a coverage calculation over an empty agreed set returns 100%, and a green dashboard
would then stand in for an agreement nobody gave. Zero agreed prints ``n/a``, and the
first rule to be agreed activates the real denominator with no code change -- the
denominator is counted, not written down.

Rejected rules are excluded from every denominator. ``R-157`` is retained, enumerated
and asserted *not* to fire (convention 7's inverted criterion, in the test file), which
is a different thing from being counted as work outstanding.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from askai.rules.evidence import (
    EvidenceError,
    EvidenceIndex,
    collect_evidence,
    repository_root,
    rules_without_evidence,
)
from askai.rules.loader import RuleLoadError, RuleSet, load_rules
from askai.rules.schema import RuleStatus

__all__ = ["CatalogueRegister", "Coverage", "main", "measure", "read_catalogue", "render"]

#: The catalogue document, which is the denominator of implementation and is *not*
#: owned here. Its per-rule status column still reads `proposed` on every rule and its
#: argument section still argues the pre-agreement position; a dated v2.2 note records
#: why neither was bulk-edited. So this module reads the register for its ids and takes
#: agreement from the data files, where agreement was actually recorded.
CATALOGUE: Final = repository_root() / "docs" / "RULES.md"

#: ``#### `R-157```, or ``#### `R-17` -- Timeout``: the id is backticked and first, and
#: about a sixth of the entries carry a title after it.
_HEADING: Final = re.compile(r"^#{2,4}\s+`(?P<id>[A-Z]+-[0-9A-Za-z.-]+)`.*$", re.MULTILINE)

#: The status the catalogue records inline on the same entry.
_STATUS: Final = re.compile(r"\*\*Status:\*\*\s*`(?P<status>agreed|proposed|rejected)`")

_UNRECORDED: Final = "UNRECORDED"


@dataclass(frozen=True, slots=True)
class CatalogueRegister:
    """The ids ``docs/RULES.md`` carries, and which of them it records as withdrawn."""

    ids: tuple[str, ...]
    rejected: tuple[str, ...]

    @property
    def live(self) -> int:
        """Catalogue rules that are not withdrawn -- the implementation denominator."""
        return len(self.ids) - len(self.rejected)

    @property
    def is_available(self) -> bool:
        return bool(self.ids)


@dataclass(frozen=True, slots=True)
class Coverage:
    """One run of the gate: the three counts, and the rules behind each gap."""

    fireable: int
    agreed: int
    attributed: int
    rejected: tuple[str, ...]
    with_evidence: tuple[str, ...]
    without_evidence: tuple[str, ...]
    encoded_from_catalogue: tuple[str, ...]
    register: CatalogueRegister

    @property
    def evidence_is_measurable(self) -> bool:
        """Is there an agreed rule to measure evidence over at all?

        The single question standing between this report and a meaningless 100%.
        """
        return self.agreed > 0

    @property
    def evidence_percent(self) -> int:
        """Whole per cent of agreed rules with evidence. Only ask when it is measurable."""
        if not self.evidence_is_measurable:
            raise ValueError(
                "evidence coverage over zero agreed rules has no percentage; a "
                "calculation over an empty agreed set returns 100%, which is the one "
                "number this gate exists to never print"
            )
        return round(100 * len(self.with_evidence) / self.agreed)

    @property
    def is_attributed(self) -> bool:
        """Has anyone with standing put their name to the agreement? (FR-72a.)"""
        return self.attributed == self.agreed and self.agreed > 0


def read_catalogue(path: Path | None = None) -> CatalogueRegister:
    """The ids and withdrawals ``docs/RULES.md`` records, or an empty register.

    Absent is not an error. The document is not packaged, so an installed engine has no
    catalogue to read; the report then says the denominator is unavailable rather than
    inventing one, which is the same discipline as everything else here.
    """
    document = CATALOGUE if path is None else path
    try:
        text = document.read_text(encoding="utf-8")
    except OSError:
        return CatalogueRegister(ids=(), rejected=())

    headings = list(_HEADING.finditer(text))
    ids: list[str] = []
    rejected: list[str] = []
    for position, heading in enumerate(headings):
        rule_id = heading.group("id")
        end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
        entry = text[heading.end() : end]
        status = _STATUS.search(entry)
        if status is None:
            continue  # a heading that is not a rule entry -- it carries no status line
        ids.append(rule_id)
        if status.group("status") == RuleStatus.REJECTED.value:
            rejected.append(rule_id)
    return CatalogueRegister(ids=tuple(ids), rejected=tuple(rejected))


def measure(
    rule_set: RuleSet | None = None,
    *,
    index: EvidenceIndex | None = None,
    register: CatalogueRegister | None = None,
) -> Coverage:
    """Count the three coverages over *rule_set*, raising on broken evidence links."""
    loaded = load_rules() if rule_set is None else rule_set
    evidence = collect_evidence(loaded) if index is None else index
    catalogue = read_catalogue() if register is None else register

    fireable = [entry for entry in loaded if entry.rule.is_fireable]
    agreed = [entry for entry in fireable if entry.status is RuleStatus.AGREED]
    without = rules_without_evidence(loaded, evidence)
    without_agreed = tuple(entry.id for entry in agreed if entry.id in set(without))
    encoded = {
        catalogue_id
        for entry in loaded
        if entry.rule.is_fireable
        for catalogue_id in entry.rule.catalogue
    }
    return Coverage(
        fireable=len(fireable),
        agreed=len(agreed),
        attributed=sum(1 for entry in agreed if entry.rule.is_attributed),
        rejected=tuple(entry.id for entry in loaded if not entry.rule.is_fireable),
        with_evidence=tuple(entry.id for entry in agreed if evidence.covers(entry.id)),
        without_evidence=without_agreed,
        encoded_from_catalogue=tuple(sorted(encoded)),
        register=catalogue,
    )


def render(coverage: Coverage, out: TextIO) -> None:
    """Print the report an acceptance reviewer reads, gaps named rather than counted."""
    print("rule coverage", file=out)

    if coverage.evidence_is_measurable:
        headline = (
            f"  evidence      {len(coverage.with_evidence)} of {coverage.agreed} agreed "
            f"rules are named by a test that runs in CI ({coverage.evidence_percent}%)"
        )
    else:
        headline = (
            f"  evidence      n/a -- 0 of {coverage.fireable} agreed. Coverage over an "
            "empty agreed set is undefined, and reads as complete"
        )
    print(headline, file=out)

    approval = (
        f"{coverage.attributed} of {coverage.agreed} name an approver"
        if coverage.is_attributed
        else f"agreed_by is {_UNRECORDED} on all {coverage.agreed}"
    )
    counted = f"{coverage.agreed} of {coverage.fireable} rules agreed"
    print(f"  agreement     {counted}; {approval}", file=out)
    print(
        "                this is an organisational gate (FR-72a), not an engineering "
        "one: the field exists and nobody has been named to fill it",
        file=out,
    )

    if coverage.register.is_available:
        live = coverage.register.live
        encoded = len(coverage.encoded_from_catalogue)
        print(
            f"  implemented   {encoded} of {live} live catalogue rules are encoded as "
            f"data ({len(coverage.register.ids)} in the catalogue, "
            f"{len(coverage.register.rejected)} withdrawn)",
            file=out,
        )
    else:
        print(
            "  implemented   n/a -- docs/RULES.md is not in this tree, so the "
            "catalogue denominator is unknown and is not guessed",
            file=out,
        )

    if coverage.rejected:
        print(
            f"  withdrawn     {', '.join(coverage.rejected)} -- retained so it is not "
            "re-proposed, excluded from every denominator, asserted never to fire",
            file=out,
        )

    if coverage.without_evidence:
        print(f"  no evidence   {len(coverage.without_evidence)} agreed rules:", file=out)
        for rule_id in coverage.without_evidence:
            print(f"                  {rule_id}", file=out)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the coverage report. Exit 0 on a report, 2 when it cannot be produced.

    A gap is not a failure exit: the target is 100% before acceptance, and a gate that
    fails the build today would be switched off today. A *broken* link is a failure
    exit, because that is a lie in the report rather than a gap in the work.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        print(
            f"usage: python -m askai.rules.coverage (takes no arguments, got {arguments})",
            file=sys.stderr,
        )
        return 2
    try:
        render(measure(), sys.stdout)
    except (RuleLoadError, EvidenceError) as error:
        print(f"rule coverage cannot be reported: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised as a subprocess
    sys.exit(main())
