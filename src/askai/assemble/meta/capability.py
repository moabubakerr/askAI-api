"""*"What can you do?"* -- answered by counting the data held, never from a written list.

Purity: pure.

Recorded failure F-007 is that this question returned nothing. The obvious fix is a
paragraph describing the product, and it is the wrong one: a hand-maintained list of
capabilities drifts from the truth the moment an indicator is added or a refresh removes
one, and it drifts **silently** -- nothing fails, and the answer stays confident.

So every clause of this answer is a count of the loaded read model, taken when the
question is asked (``R-META-CAPABILITY-IS-COUNTED-NOT-DECLARED``). A refresh that adds a
classification changes the answer with nobody editing a sentence, and a refresh that
empties a table makes the answer say so.

Two honesty clauses sit beside it, and both are about claims the counts would otherwise
let the engine make by omission:

**The gaps are named** (``R-META-CAPABILITY-STATES-WHAT-IS-NOT-HELD``). The read model has
no table for analyst prose and none for articles -- the ingest counts 1,031 analyses and
stores none, because Story 1.8 says load them and Story 1.6 creates no table for them. An
answer listing only what works reads as a complete account of the engine's reach, and the
reader who then asks *"why did it move"* has been misled by an answer true in every clause.

**The confidential filter is not claimed**
(``R-META-CONFIDENTIAL-FILTER-IS-NOT-CLAIMED``). The priority vocabulary defines
``Confidential`` and **zero** of the 189 published indicators carry it: 105 are ``Priority``
and 84 carry nothing. Saying *"confidential indicators are excluded"* would describe an
exclusion that never happens and imply a body of withheld data that does not exist. The
read model's CHECK constraint still refuses such a row, and that stays -- this is about
what the answer says, not about what the store accepts.

Every element here carries the **whole-catalogue** reference, because every count is true
of the file the engine loaded and of nothing narrower. It resolves when that file holds any
published indicator at all, so a capability answer computed from an empty read model is
refused rather than delivered as a confident catalogue of nothing (FR-77).
"""

from __future__ import annotations

from enum import StrEnum

from askai.assemble.meta.reference import catalogue_element, whole_catalogue
from askai.assemble.roles import Placed, Role
from askai.domain.element import ElementClass
from askai.messages import Catalogue, Lang, compose_counted, render
from askai.ports.groups import Coverage
from askai.rules import RuleSet

__all__ = ["CapabilityClause", "CapabilityMessage", "CapabilityRule", "capability_elements"]


class CapabilityMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    HOLDS = "sentence.capability_holds"
    WITH_DATA = "sentence.capability_with_data"
    CATEGORIES = "sentence.capability_categories"
    GROUPS = "sentence.capability_groups"
    COUNTRIES = "sentence.capability_countries"
    NO_COMMENTARY = "capability.no_commentary"
    NO_CONFIDENTIAL_FILTER = "capability.no_confidential_filter"

    #: The counted nouns each clause is said in. The unit is an argument at every call
    #: (R-175): indicators are counted in indicators and series in series, and a shared
    #: default noun is how 261 details become 261 indicators in an Arabic sentence.
    INDICATOR = "count.indicator"
    CATEGORY = "count.category"
    GROUP = "count.group"
    DETAIL = "count.detail"


class CapabilityRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    COUNTED = "R-META-CAPABILITY-IS-COUNTED-NOT-DECLARED"
    STATES_GAPS = "R-META-CAPABILITY-STATES-WHAT-IS-NOT-HELD"
    NO_CONFIDENTIAL_CLAIM = "R-META-CONFIDENTIAL-FILTER-IS-NOT-CLAIMED"


class CapabilityClause(StrEnum):
    """The clause names read off those rules."""

    COUNT_THE_READ_MODEL = "count_the_read_model"
    STATE_THE_GAPS = "state_the_gaps"
    CLAIM_A_CONFIDENTIAL_FILTER = "claim_a_confidential_filter"


class CapabilityError(LookupError):
    """The capability rules cannot be acted on.

    Raised rather than defaulted. Every default available here is a claim: defaulting
    ``state_the_gaps`` to false produces an answer that describes only what works, and
    defaulting the confidential clause to true produces an answer claiming a filter that
    filters nothing. Both read as correct.
    """


def capability_elements(
    catalogue: Catalogue, lang: Lang, rule_set: RuleSet, coverage: Coverage
) -> tuple[Placed, ...]:
    """What this engine can answer, counted from *coverage*, with its gaps named.

    Every element is ``measured``: each one is a count of rows in the loaded published
    layer, which is what ``measured`` means -- a count is a figure and obeys the same
    rules (AD-3, Story 5.3). The two honesty clauses are ``measured`` too, and that is not
    a stretch: *"no published indicator is marked confidential"* is a reading of the
    priority column, not an opinion about the product.

    Role ``headline`` for the reach clauses and ``note`` for the gaps, so the executive
    lens carries both -- ``note`` is in both lenses, which is what keeps *"and here is what
    I cannot do"* from being the first thing brevity removes.
    """
    _require(rule_set, CapabilityRule.COUNTED, CapabilityClause.COUNT_THE_READ_MODEL, True)
    _require(rule_set, CapabilityRule.STATES_GAPS, CapabilityClause.STATE_THE_GAPS, True)
    _require(
        rule_set,
        CapabilityRule.NO_CONFIDENTIAL_CLAIM,
        CapabilityClause.CLAIM_A_CONFIDENTIAL_FILTER,
        False,
    )
    reach = (
        (CapabilityMessage.HOLDS, CapabilityMessage.INDICATOR, coverage.indicators),
        (
            CapabilityMessage.WITH_DATA,
            CapabilityMessage.INDICATOR,
            coverage.indicators_with_data,
        ),
        (CapabilityMessage.CATEGORIES, CapabilityMessage.CATEGORY, coverage.classifications),
        (CapabilityMessage.GROUPS, CapabilityMessage.GROUP, coverage.entities),
        (
            CapabilityMessage.COUNTRIES,
            CapabilityMessage.DETAIL,
            coverage.details_with_country_data,
        ),
    )
    composed = [
        _element(
            compose_counted(catalogue, lang, message.value, unit.value, count),
            Role.HEADLINE,
        )
        for message, unit, count in reach
    ]
    composed += [
        _element(render(catalogue, lang, message.value), Role.NOTE)
        for message in (
            CapabilityMessage.NO_COMMENTARY,
            CapabilityMessage.NO_CONFIDENTIAL_FILTER,
        )
    ]
    return tuple(composed)


def _element(content: str, role: Role) -> Placed:
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, whole_catalogue()),
        role=role,
    )


def _require(
    rule_set: RuleSet, rule: CapabilityRule, clause: CapabilityClause, position: bool
) -> None:
    """Read a switch and refuse to compose when the file disagrees with what this implements.

    Both positions are checked, including the ones that are off. ``claim_a_confidential
    _filter`` is false and there is no code here that would claim it; reading the clause
    and refusing when it is true is what stops it being a comment that describes the
    composer rather than governing it.
    """
    value = rule_set.value(rule.value, clause.value)
    if value is not position:
        raise CapabilityError(
            f"{rule.value} value `{clause.value}` is {value!r}; this composer implements "
            f"it as {position!r} and has no other form, so composing anyway would make "
            "the clause decorative"
        )
