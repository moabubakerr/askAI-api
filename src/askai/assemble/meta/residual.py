"""The unaccounted remainder of a set of shares, named for what it is.

Purity: pure.

FR-37c, and the whole of Story 5.9: when published components are shares and they do not
sum to their whole, **something** has to happen to the difference. There are three things
an engine can do with it, and two of them are the defect:

* **adjust the parts so they sum.** The parts stop being the published figures and become
  numbers this engine made up, and nothing in the answer says so.
* **drop it.** The reader is shown a set of parts that appears to account for the whole.
  This is worse than adjusting, because there is no discrepancy left to notice.
* **name it.** The remainder is stated as its own part, with what it was computed from.

Three properties make the third one hold rather than be intended:

**It is ``Derived``, with its inputs stated** (FR-45). The residual is not a published
component and must never be mistaken for one, so the class says where it came from and the
wording names the total it was taken from. ``Measured`` here would be the engine's own
arithmetic entering the answer with the authority of a published row.

**It is not called "other"** (``R-META-RESIDUAL-IS-NOT-CALLED-OTHER``). "Other" asserts
that the remainder is a residual category of the same kind as the parts -- a real bucket
somebody publishes. Nothing published says that. When the data *does* name such a
component, the caller passes that published label and it is used; otherwise the wording is
*not accounted for by the published components*, which is a description rather than a
claim.

**Exact decimal arithmetic, and no tolerance.** Published values are exact decimals, so the
remainder is exact and "do they sum" is an exact question. A tolerance would be a
reader-affecting constant deciding when a discrepancy stops being reported, and this module
deliberately has none: a remainder of zero is no remainder, and anything else is stated.

**What this module does not have is its input.** The components come from the declared
sub-indicator membership -- 24 indicators declare it, 113 memberships over 110 distinct
details -- and the read model has **no table for it**. ``P07a`` in the CMS export carries
the rows and the ingest of Story 1.8 materialises none of them. So Story 5.8's composer is
not here, this module takes the shares as values, and ``tests/test_meta.py`` drives it
directly. Story 5.9's arithmetic is the half that can be built and defended today; the half
that needs a table is reported rather than faked.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from askai.assemble.elements import derived
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.messages import Catalogue, Lang, render
from askai.rules import RuleSet

__all__ = [
    "Residual",
    "ResidualClause",
    "ResidualMessage",
    "ResidualRule",
    "residual_element",
    "residual_of",
]


class ResidualMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    UNACCOUNTED = "residual.unaccounted"
    STATEMENT = "residual.statement"
    EXCEEDS = "residual.exceeds"


class ResidualRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    NAMED_NOT_ABSORBED = "R-META-RESIDUAL-IS-NAMED-NOT-ABSORBED"
    NOT_CALLED_OTHER = "R-META-RESIDUAL-IS-NOT-CALLED-OTHER"


class ResidualClause(StrEnum):
    """The clause names read off those rules."""

    STATE_THE_REMAINDER = "state_the_remainder"
    NAME_IT_OTHER = "name_the_remainder_other"


class ResidualError(LookupError):
    """The residual rules cannot be acted on, or were asked something they do not answer."""


@dataclass(frozen=True, slots=True)
class Residual:
    """What the published components do not account for, and which way it runs.

    ``amount`` is always non-negative and ``exceeds`` says which direction the discrepancy
    runs, rather than the amount carrying a sign a reader has to interpret. Parts summing
    to *more* than their stated total is a real published state and a different sentence:
    there is no remainder to name, there is an inconsistency to report, and an engine that
    rendered it as a negative "other" category would have invented a negative share.
    """

    amount: Decimal
    total: Decimal
    exceeds: bool

    def __post_init__(self) -> None:
        if self.amount < Decimal(0):
            raise ValueError(
                f"a residual is stated as a magnitude and a direction, not as a signed "
                f"amount; {self.amount} would render as a negative share of a whole"
            )


def residual_of(total: Decimal, parts: Sequence[Decimal]) -> Residual | None:
    """*total* less *parts*, or ``None`` when the parts account for the whole exactly.

    ``None`` is *"there is no remainder"*, which is a different answer from a remainder of
    zero and is why this returns an option rather than a ``Residual`` with a zero amount:
    a zero-amount residual would be composed into a sentence naming a part that is not
    there, on every set of shares that happens to be complete.

    Exact ``Decimal`` arithmetic throughout. No rounding, no tolerance, and no float:
    the parts are published decimals and the subtraction of published decimals is exact,
    so a difference that appears is a difference the published data has.
    """
    difference = total - sum(parts, Decimal(0))
    if not difference:
        return None
    return Residual(amount=abs(difference), total=total, exceeds=difference < Decimal(0))


def residual_element(
    catalogue: Catalogue,
    lang: Lang,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
    residual: Residual,
    published: PublishedFormat,
    provenance: Provenance,
    published_label: str | None = None,
) -> Placed:
    """The residual, said -- named honestly, classed ``derived``, with its inputs stated.

    *published_label* is the name the data gives a residual component, when it gives one.
    It is the **only** way this element gets a label of its own: there is no clause that
    turns "other" on, so a caller cannot ask for one, and the default wording describes
    the remainder rather than naming a category (``R-META-RESIDUAL-IS-NOT-CALLED-OTHER``).

    The provenance is the row the **total** came from, so the element resolves against the
    published figure it was derived from. A residual sourced to nothing would be exactly
    the unsourced content AD-7 rejects, and it would be the most plausible-looking kind.

    Role ``delta``: the remainder is a movement between a stated whole and its stated
    parts, which is the job ``delta`` names, and it is in both lenses -- a residual that
    brevity removed would restore the silent-drop defect the whole module exists to end.
    """
    _require_stated(rule_set)
    written = formatter.format(residual.amount, published, placement.mode_for(Role.DELTA), lang)
    whole = formatter.format(residual.total, published, placement.mode_for(Role.DELTA), lang)
    if residual.exceeds:
        content = render(
            catalogue,
            lang,
            ResidualMessage.EXCEEDS.value,
            value=written.value,
            unit=written.unit,
            total=whole.value,
        )
    else:
        content = render(
            catalogue,
            lang,
            ResidualMessage.STATEMENT.value,
            label=_label(catalogue, lang, rule_set, published_label),
            value=written.value,
            unit=written.unit,
            total=whole.value,
        )
    return Placed(element=derived(content, provenance), role=Role.DELTA)


def _label(catalogue: Catalogue, lang: Lang, rule_set: RuleSet, published_label: str | None) -> str:
    """The published name for the remainder, or the description that is not a name.

    The clause is read even though this module has no branch that could produce "other":
    a rule whose *on* position nothing implements is a rule a reviewer could turn on and
    see no change from, which is how a file stops governing the code it describes.
    """
    value = rule_set.value(ResidualRule.NOT_CALLED_OTHER.value, ResidualClause.NAME_IT_OTHER.value)
    if value is not False:
        raise ResidualError(
            f"{ResidualRule.NOT_CALLED_OTHER.value} value "
            f"`{ResidualClause.NAME_IT_OTHER.value}` is {value!r}; this composer names the "
            "remainder only from the published data and implements no residual category "
            "of its own, so it refuses rather than ignoring the clause"
        )
    named = (published_label or "").strip()
    return named or render(catalogue, lang, ResidualMessage.UNACCOUNTED.value)


def _require_stated(rule_set: RuleSet) -> None:
    value = rule_set.value(
        ResidualRule.NAMED_NOT_ABSORBED.value, ResidualClause.STATE_THE_REMAINDER.value
    )
    if value is not True:
        raise ResidualError(
            f"{ResidualRule.NAMED_NOT_ABSORBED.value} value "
            f"`{ResidualClause.STATE_THE_REMAINDER.value}` is {value!r}; the only other "
            "behaviour is dropping the remainder, which this composer does not implement "
            "and which is the defect it exists to prevent"
        )
