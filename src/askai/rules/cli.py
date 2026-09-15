"""The enumerate command -- ``python -m askai.rules``.

Purity: writes to the streams it is handed; the enumeration itself is pure.

FR-70: *"the rule set is enumerable -- it is possible to produce the complete list of
rules the engine implements."* Complete means complete: ``rejected`` rules are printed
with the rest, because a withdrawal an operator cannot see is a withdrawal that gets
re-proposed. Each line carries the id, the statement and the file it came from, so the
answer to *"where do I change this?"* is in the output rather than in someone's head.

The command loads through the same ``load_rules()`` the service starts with, so an
operator who can enumerate the rules has also just proved the service would start.
"""

from __future__ import annotations

import sys
import textwrap
from collections import Counter
from collections.abc import Sequence
from typing import Final, TextIO

from askai.rules.loader import RuleLoadError, RuleSet, load_rules
from askai.rules.schema import RuleStatus

__all__ = ["main", "render"]

_WIDTH: Final = 92
_INDENT: Final = "    "


def render(rule_set: RuleSet, out: TextIO) -> None:
    """Print every rule as id, statement and source file, then the status tally.

    The tally is the shape of the catalogue's own register (``docs/RULES.md`` §4.3): it
    is how an operator sees at a glance that nothing is ``agreed`` yet, which is the
    standing gap FR-72a records and this command must not hide.
    """
    for entry in rule_set:
        print(f"{entry.id}  [{entry.status.value}]  {entry.source_file.name}", file=out)
        for line in textwrap.wrap(entry.statement, width=_WIDTH - len(_INDENT)):
            print(f"{_INDENT}{line}", file=out)
        print(file=out)

    counted = Counter(entry.status for entry in rule_set)
    # ASCII, deliberately: the catalogue writes this tally with an em dash and a middle
    # dot, and an operator's console is not guaranteed to be UTF-8. A command that
    # raises UnicodeEncodeError while printing its summary would look like a rule
    # failure rather than a terminal setting.
    tally = " | ".join(f"{status.value} {counted[status]}" for status in RuleStatus)
    files = len({entry.source_file for entry in rule_set})
    print(f"{len(rule_set)} rules from {files} files -- {tally}", file=out)


def main(argv: Sequence[str] | None = None) -> int:
    """Enumerate the rules. Exit 0 when they load, 2 when they do not.

    A load failure prints the file and the violated constraint to stderr and prints no
    rules at all -- the same refusal the service makes at startup, for the same reason:
    a partial enumeration would be read as the complete one.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        usage = f"usage: python -m askai.rules (takes no arguments, got {arguments})"
        print(usage, file=sys.stderr)
        return 2
    try:
        rule_set = load_rules()
    except RuleLoadError as error:
        print(f"rules failed to load: {error}", file=sys.stderr)
        return 2
    render(rule_set, sys.stdout)
    return 0
