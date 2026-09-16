"""What a change *is*: a basis, a flavour, and the one place either is constructed.

Purity: pure, imports nothing in-project outside ``domain/``.

``domain/numbers.py`` gives the engine two percentage types that never convert. This
module gives them the vocabulary the published data states them in, and the only two
arithmetic operations AD-4 allows a change to be produced by -- because ``assemble/``
may construct neither type, which ``tests/test_assemble.py`` asserts by scanning the
package for a ``Percent(...)`` call. The composer selects and labels; it does not build
a quantity. Everything that decides *which quantity a change is* therefore lives here,
below it, where a reviewer can read the whole of it at once.

**The flavour is declared, never inferred.** ``change_value`` takes a ``ChangeFlavour``
and never looks at the number: a published column says what it publishes, and a value
of 2.0 is 2% or 2 pp depending entirely on which column it was read from (FR-21, Story
3.6). Inferring it from the magnitude is the F-005/F-029 defect with an extra step.

**The basis is not the grain.** One quarterly row publishes both QoQ and YoY, so a basis
is a separate closed vocabulary rather than something read off a period. Which bases a
grain may carry, and which one a question that names none falls back to, are published
decisions and live in ``rules/data/change-columns.yaml`` -- not here, because they are
facts about this export rather than about arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation
from enum import StrEnum
from typing import Final

from askai.domain.numbers import Percent, PercentagePoints
from askai.domain.text import is_published_text

__all__ = [
    "Basis",
    "ChangeFlavour",
    "ChangeValue",
    "UndefinedChange",
    "change_value",
    "computed_change",
    "flavour_of",
    "percent_between",
    "points_between",
    "read_change",
]

#: Per hundred, which is what "percent" means. Not a rule: a rule file offering to
#: change it would be offering to redefine the word rather than to tune the engine.
_PER_HUNDRED: Final = Decimal(100)


class Basis(StrEnum):
    """What a change was measured against. Closed; the published columns are these.

    Spelled as the export spells them, and rendered to a reader through the bilingual
    catalogue rather than by showing the member (FR-63): *"year on year"* and its Arabic
    counterpart are authored words, and a transliterated ``YoY`` in an Arabic answer is
    the label defect FR-63 exists to end.
    """

    YOY = "yoy"
    """Against the same period one year earlier."""

    QOQ = "qoq"
    """Against the previous quarter."""

    MOM = "mom"
    """Against the previous month."""


class ChangeFlavour(StrEnum):
    """Which of the two quantities a change is. There is no third and no conversion."""

    PERCENT = "percent"
    """A proportional movement on an indicator measured in its own unit."""

    PERCENTAGE_POINTS = "pp"
    """The movement between two percentages, on an indicator already measured in %."""


#: A change, as a value. The union is the two types and nothing else -- in particular
#: not a bare ``Decimal``, so a change that has lost its flavour cannot be passed as one.
type ChangeValue = Percent | PercentagePoints


class UndefinedChange(ArithmeticError):
    """A change was asked for between two readings that do not define one.

    The earlier reading being zero is the case that happens: a proportional movement
    from nothing is not a large percentage, it is undefined, and returning a very large
    number instead would be the engine inventing the most alarming figure on the card.
    """


def change_value(flavour: ChangeFlavour, value: Decimal) -> ChangeValue:
    """*value*, as the quantity *flavour* declares it to be.

    The one constructor for a change. Exhaustive over the flavours, and the value is
    never consulted -- which is the property Story 3.6's *"its declared flavour
    determines the type, the engine does not infer it from the value"* asks for.
    """
    match flavour:
        case ChangeFlavour.PERCENT:
            return Percent(value)
        case ChangeFlavour.PERCENTAGE_POINTS:
            return PercentagePoints(value)
        case _:
            raise TypeError(
                f"{flavour!r} is not a change flavour; a change is a percentage or it is "
                "percentage points, and there is no third quantity to build"
            )


def flavour_of(value: ChangeValue) -> ChangeFlavour:
    """Which flavour *value* is -- read off the type, never off the magnitude."""
    match value:
        case PercentagePoints():
            return ChangeFlavour.PERCENTAGE_POINTS
        case Percent():
            return ChangeFlavour.PERCENT
        case _:
            raise TypeError(
                f"{type(value).__name__} is not a change value; a change carries its "
                "quantity in its type, which is what stops percent becoming pp"
            )


def points_between(later: Percent, earlier: Percent) -> PercentagePoints:
    """The movement between two percentages, which is **percentage points**.

    A named function over ``Percent.__sub__`` rather than a second implementation of it:
    the subtraction already returns the right type, and this exists so the computed-change
    path reads as the deliberate act it is instead of as an inline operator somebody
    could later "simplify" into a percent.
    """
    return later - earlier


def percent_between(later: Decimal, earlier: Decimal) -> Percent:
    """The proportional movement from *earlier* to *later*, as a percentage.

    Used only where no published column exists (AD-4). ``Decimal`` throughout, so the
    published digits are never routed through binary floating point on the way to a
    figure a reader checks against a published table.
    """
    if not earlier.is_finite() or not later.is_finite():
        raise UndefinedChange(f"a change needs two finite readings, not {earlier} and {later}")
    if earlier.is_zero():
        raise UndefinedChange(
            "a proportional change from zero is undefined; the movement is stated in the "
            "indicator's own unit instead, never as a percentage of nothing"
        )
    try:
        return Percent((later - earlier) / earlier * _PER_HUNDRED)
    except (DivisionByZero, InvalidOperation) as error:  # pragma: no cover -- guarded above
        raise UndefinedChange(f"no change is defined between {earlier} and {later}") from error


def computed_change(flavour: ChangeFlavour, later: Decimal, earlier: Decimal) -> ChangeValue:
    """The movement from *earlier* to *later*, as the quantity *flavour* declares.

    The whole of the computed-change path, in one exhaustive match, so that ``assemble/``
    -- which may construct neither percentage type -- has a single call to make and no
    branch of its own to get wrong. An indicator already measured in percent moves by
    percentage points; anything else moves by a percentage of where it was.
    """
    match flavour:
        case ChangeFlavour.PERCENTAGE_POINTS:
            return points_between(Percent(later), Percent(earlier))
        case ChangeFlavour.PERCENT:
            return percent_between(later, earlier)
        case _:
            raise TypeError(
                f"{flavour!r} is not a change flavour; there is no third quantity a "
                "movement between two readings can be"
            )


def read_change(flavour: ChangeFlavour, published: str | None) -> ChangeValue | None:
    """A published change column's digits, as the quantity that column declares.

    ``None`` when the column publishes nothing, or publishes something that is not a
    number -- which is a fact about the cell, not a failure, and is how "no QoQ is
    published on this row" reaches a composer as an absence it can state.

    The parse lives here rather than in the composer for the same reason the
    constructors do: ``assemble/`` builds no quantity, and a ``Decimal(...)`` beside a
    flavour is one line away from being a ``Percent`` beside a value.
    """
    if published is None or not is_published_text(published):
        return None
    try:
        digits = Decimal(published.strip())
    except (InvalidOperation, ValueError):
        return None
    if not digits.is_finite():
        return None
    return change_value(flavour, digits)
