"""One closed question, asked once, naming what is missing.

Purity: pure. Reads two clauses from ``rules/``; holds no threshold of its own.

Story 2.11. *"257 of 320 published names are ambiguous"*, so asking is the primary path
and not a consolation one -- but only if the question is worth answering:

**Specific and closed.** A clarification names the candidates or the missing dimension.
*"Please rephrase"* is not a question, it is the engine handing its problem back, and
``tests/test_refusals.py`` scans the whole of both catalogue files to assert no message
says it in either language. That scan is the acceptance criterion; this module is what
makes passing it possible, because every clarification here is composed from an id whose
parameters *are* the candidates or the dimension.

**At most one per turn** (FR-93). Structural rather than promised: a package carries one
``reason`` and one ``reason_id``, both single values, and this module returns one
``Asked`` or nothing. There is no list of questions to accidentally grow.

**A dominant candidate is answered, not asked about** (FR-93). ``prefer_assumption``
is the policy, and its threshold is ``R-CLARIFY-DOMINANT-SHARE`` in ``rules/`` rather
than a literal here. Note where the preference is actually *exercised*: AD-25's
``compile.resolve.decide`` already binds -- rather than disambiguating -- whenever one
candidate leads by ``R-RESOLVE-AMBIGUITY-MARGIN``, which is the same preference applied
at the only layer allowed to bind a field (AD-1). This function is the second, wider
guard, for a candidate set that reaches composition from any other rung.

**The rate is a tracked counter-metric.** ``ClarificationRate`` is a frozen value with
no accumulator behind it, for the reason ``RefusalTally`` is one: an engine that asks
more often is either getting more careful or getting worse, and the number is only
readable beside the refusal tally by cause.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from askai.compile.binding import UnboundReason
from askai.compile.resolve.decide import Offered
from askai.messages import Catalogue, Lang, render
from askai.rules import RuleSet
from askai.rules.schema import PER_CENT

__all__ = [
    "CLARIFY_MESSAGE_IDS",
    "ClarificationRate",
    "ClarifyCode",
    "ClarifyRule",
    "clarification_for",
    "clarify_message_id",
    "named_options",
    "one_question_per_turn",
    "prefer_assumption",
]


class ClarifyCode(StrEnum):
    """What a clarifying question is *about*. Closed, and one id each.

    Two members, because there are two closed questions the engine can actually put: it
    can name the indicators it is choosing between, and it can name the dimension the
    question left out. A third member would need a third closed question, not a third
    way of saying the same one.
    """

    WHICH_INDICATOR = "which-indicator"
    """Several indicators match; they are named, and the reader picks one."""

    WHICH_PERIOD = "which-period"
    """The indicator is clear and the period is not; the dimension is named."""


#: The catalogue id each closed question is put with. Read-only, because a module-level
#: ``dict`` in this engine is the shape an ambient collector takes and
#: ``tests/test_domain_invariants.py`` refuses one.
CLARIFY_MESSAGE_IDS: Final[Mapping[ClarifyCode, str]] = MappingProxyType({
    ClarifyCode.WHICH_INDICATOR: "clarify.which_indicator",
    ClarifyCode.WHICH_PERIOD: "clarify.which_period",
})


class ClarifyRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    DOMINANT_SHARE = "R-CLARIFY-DOMINANT-SHARE"
    ONE_PER_TURN = "R-CLARIFY-ONE-QUESTION-PER-TURN"


def clarification_for(reason: UnboundReason) -> ClarifyCode | None:
    """The closed question an unbound field can be put as, or ``None`` to refuse.

    Total over the closed ``UnboundReason`` set, and deliberately *not* a question for
    every member. FR-92 requires a **closed** question, and a closed question needs
    something to close over -- so the rule here is simply *have we got candidates or a
    named dimension to put?*

    Four states have neither, and each is a refusal rather than a stall. A question that
    named no subject at all has no candidates to offer, so asking would be *"what did you
    mean?"*, which is the open question FR-92 forbids. Nothing resolved means the
    candidate list is empty. A grain the detail does not publish cannot be fixed by a
    reply, because FR-6 bans substituting the adjacent one. And a period range running
    backwards is a question to restate, not to complete.
    """
    match reason:
        case UnboundReason.DETAIL_NAME_IS_SHARED | UnboundReason.SEVERAL_INDICATORS_MATCH:
            return ClarifyCode.WHICH_INDICATOR
        case UnboundReason.MORE_THAN_ONE_PERIOD_NAMED:
            return ClarifyCode.WHICH_PERIOD
        case (
            UnboundReason.NO_DETAIL_NAMED
            | UnboundReason.NO_INDICATOR_RESOLVED
            | UnboundReason.GRAIN_NOT_PUBLISHED
            | UnboundReason.PERIOD_RANGE_RUNS_BACKWARDS
        ):
            return None


def clarify_message_id(code: ClarifyCode) -> str:
    """The catalogue id *code* is asked with."""
    return CLARIFY_MESSAGE_IDS[code]


def named_options(catalogue: Catalogue, lang: Lang, surfaces: Sequence[str]) -> str:
    """The candidates, joined by the separator the reader's language uses.

    The separator is an id like every other punctuation decision: the Arabic comma is
    not the English one, and a list joined in code would be joined in one language.
    """
    separator = render(catalogue, lang, "clarify.option_separator")
    return separator.join(surfaces)


def prefer_assumption(candidates: Sequence[Offered], rule_set: RuleSet) -> Offered | None:
    """The candidate clear enough to answer under a stated assumption, or ``None``.

    *Clearly dominant* is a share of the candidates' combined score, read from
    ``R-CLARIFY-DOMINANT-SHARE``. A share rather than a gap, for the reason AD-25's own
    margin is relative: the scores are sums of whichever signals the question supplied,
    so a fixed gap would be dominant on a rich question and never on a bare name.

    Returns ``None`` for an empty set, for a single candidate -- which is a binding and
    was never a question -- and for any set whose leader does not reach the share. A
    non-positive total is ``None`` too: when no signal spoke, every candidate is equally
    unseparated, and picking the one that sorted first is exactly the confident wrong
    answer FR-2 exists to prevent.
    """
    if len(candidates) < 2:
        return None
    total = sum(candidate.score for candidate in candidates)
    if total <= 0.0:
        return None
    leader = max(candidates, key=lambda candidate: candidate.score)
    share = _share(rule_set, ClarifyRule.DOMINANT_SHARE, "dominant_share_percent")
    return leader if leader.score / total >= share else None


def one_question_per_turn(rule_set: RuleSet) -> bool:
    """FR-93's switch, read as data. The engine has no second setting for it today."""
    value = rule_set.value(ClarifyRule.ONE_PER_TURN.value, "one_question_per_turn")
    if not isinstance(value, bool):
        raise TypeError(
            f"{ClarifyRule.ONE_PER_TURN.value}.one_question_per_turn is "
            f"{type(value).__name__}; FR-93 is a switch and reads as one"
        )
    return value


def _share(rule_set: RuleSet, rule: ClarifyRule, key: str) -> float:
    """A whole-percentage clause, read through the divisor the schema owns."""
    value = rule_set.value(rule.value, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{rule.value}.{key} is {type(value).__name__}; a share is a whole percentage"
        )
    return value / PER_CENT


@dataclass(frozen=True, slots=True)
class ClarificationRate:
    """How often the engine asked rather than answered -- FR-93's counter-metric.

    Two counters and a derived rate, frozen, with ``+`` to combine. The denominator is
    carried rather than assumed: a rate with no turn count cannot be compared between
    two days, and the number that matters is *"how often, out of how many"*.
    """

    turns: int = 0
    clarifications: int = 0

    def __post_init__(self) -> None:
        if self.turns < 0 or self.clarifications < 0:
            raise ValueError("a counter does not go backwards")
        if self.clarifications > self.turns:
            raise ValueError(
                f"{self.clarifications} clarifications over {self.turns} turns; FR-93 "
                "allows at most one question per turn, so the count cannot exceed them"
            )

    @property
    def rate(self) -> float:
        """The share of turns that asked. Zero turns is zero, never a division."""
        return self.clarifications / self.turns if self.turns else 0.0

    def __add__(self, other: ClarificationRate) -> ClarificationRate:
        return ClarificationRate(
            turns=self.turns + other.turns,
            clarifications=self.clarifications + other.clarifications,
        )
