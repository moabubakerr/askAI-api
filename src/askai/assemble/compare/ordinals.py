"""A position, written as an ordinal in the reader's own language (FR-26, FR-62).

Purity: pure. Reads one constant from ``rules/`` and every word from ``messages/``.

*"A 3rd place must not arrive as the number 3 in a unit that is not a unit."* The defect
behind that sentence is ``11.00 Rank`` -- a published rank rendered through the ordinary
display path, with the ``Rank`` unit shown as though it were a quantity and two decimals
on an integer position.

Two decisions, and the second is the one that matters.

**The rank display rule governs the numeral.** ``R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL``
already says a rank carries no decimals and ``R-DISPLAY-RANK-UNIT-SPELLINGS`` already
says which published unit strings mark one. Both are read through the single
``Formatter``, which is the only route from a value to a string; this module names
neither constant and restates neither rule.

**The ordinal word is per-language data, not a suffix rule.** English makes an ordinal
by suffixing a numeral -- and irregularly, with ``1st``, ``2nd``, ``3rd`` and then
``11th`` breaking the pattern it just established. Arabic makes one with a word that
agrees with what it modifies. There is no shared "numeral plus suffix" model that
produces both, and code that assumed one would generate fluent English and broken
Arabic, which is exactly the failure the two catalogue halves exist to prevent. So each
language authors its own ordinals as messages, and this module only chooses between
them.

Past the last authored position the position is written as a numeral in the language's
own form, through ``ordinal.beyond``. ``R-COMPARE-ORDINAL-NAMED-POSITIONS`` says where
that line falls, because where a language stops having a word for a position is an
editorial fact about the language and not a constant for a composer to pick.
"""

from __future__ import annotations

from decimal import Decimal

from askai.assemble.compare.selection import CompareClause, CompareRule, SelectionRuleError
from askai.assemble.format import DisplayClause, DisplayRule, Formatter, PublishedFormat
from askai.assemble.roles import Placement, Role
from askai.messages import Catalogue, Lang, render
from askai.rules import RuleSet

__all__ = ["OrdinalMessage", "named_positions", "ordinal", "rank_format"]


class OrdinalMessage:
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    BEYOND = "ordinal.beyond"

    @staticmethod
    def at(position: int) -> str:
        """The id of the authored ordinal for *position*.

        Built from the position the same way ``render_period`` builds a quarter's id.
        The catalogue refuses an id it does not hold, so a position past the authored
        list fails loudly here rather than rendering as a hole -- which is why the
        caller checks ``named_positions`` first rather than relying on a lookup miss.
        """
        return f"ordinal.{position}"


def named_positions(rule_set: RuleSet) -> int:
    """The last position each language authors an ordinal word for."""
    value = rule_set.value(
        CompareRule.ORDINAL_NAMED_POSITIONS.value, CompareClause.NAMED_POSITIONS.value
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SelectionRuleError(
            f"{CompareRule.ORDINAL_NAMED_POSITIONS.value} value "
            f"`{CompareClause.NAMED_POSITIONS.value}` must be a position of at least "
            f"one, and is {value!r}; a language that authors no ordinal at all has "
            "nothing for this module to choose between"
        )
    return value


def rank_format(rule_set: RuleSet) -> PublishedFormat:
    """The published format a rank is written under -- the unit spelling, and no Format field.

    Read off ``R-DISPLAY-RANK-UNIT-SPELLINGS`` rather than spelled here, so that the
    formatter's own test for "is this a rank" and this module's request to be treated as
    one are the same string by construction. The empty Format field is not a placeholder:
    a position is not published, so there is no published pattern for it, and the rank
    rule is exactly what decides the decimals when the field says nothing.
    """
    spellings = rule_set.value(
        DisplayRule.RANK_UNIT_SPELLINGS.value, DisplayClause.RANK_UNITS.value
    )
    if not isinstance(spellings, tuple) or not spellings:
        raise SelectionRuleError(
            f"{DisplayRule.RANK_UNIT_SPELLINGS.value} value "
            f"`{DisplayClause.RANK_UNITS.value}` must be a non-empty list of published "
            f"unit spellings, and is {spellings!r}"
        )
    return PublishedFormat(unit=spellings[0], spec="")


def ordinal(
    position: int,
    role: Role,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
    lang: Lang,
) -> str:
    """*position*, written as *lang* writes an ordinal.

    *role* is the job the ordinal does in the answer, and is what the precision is asked
    for by -- a composer holds a role and asks ``Placement``; it never names a mode
    (AD-18, FR-48). The rank rule makes the answer the same either way, and asking
    anyway is what keeps that true rather than coincidental.
    """
    if position < 1:
        raise ValueError(
            f"a position is counted from one, and {position} is not one; a rank of zero "
            "is an ordering that has not been performed"
        )
    if position <= named_positions(rule_set):
        return render(catalogue, lang, OrdinalMessage.at(position))
    written = formatter.format(
        Decimal(position), rank_format(rule_set), placement.mode_for(role), lang
    )
    return render(catalogue, lang, OrdinalMessage.BEYOND, position=written.value)
