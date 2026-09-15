"""``Percent`` and ``pp`` -- distinct types, because the data says they are.

Purity: pure, imports nothing in-project.

On an indicator already measured in ``%``, a change is in **percentage points**, not
percent. Conflating the two is the F-005/F-029 class of defect: a figure that looks
right, reads fluently, and is wrong by a factor nobody can see. FR-21 forbids it and
AD-4 makes the two distinct types with no implicit conversion in either direction.

So there is no ``__float__``, no ``to_percent()``, no ``from_pp()`` and no arithmetic
that accepts the other type. Mixing them is a type error rather than a silent
coercion; ``tests/test_type_invariants.py`` asserts ``mypy --strict`` reports it.

**Subtracting two percentages yields ``pp``**, because that is what the difference
between two percentages is. The inverse -- ``Percent + pp -> Percent``, advancing a
percentage by a movement -- is deliberately *not* offered: it is arithmetically
sensible, but the story's I/O matrix requires ``Percent`` added to ``pp`` to fail the
type check, and an operand type cannot be both rejected and accepted. Whoever needs it
should add it as a named method with its own story, not as an overload that quietly
reopens ``+``.

**Values are ``Decimal`` end to end, never ``float``** -- a published value that has
been through binary floating point is no longer the published value. Rounding and
value-to-string formatting are deliberately absent: those belong to the single
``Formatter`` in ``assemble/`` (AD-18, Story 1.13), and a convenience here would become
the second implementation it exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["Percent", "PercentagePoints", "pp"]


def _check(value: Decimal, owner: str) -> None:
    """Both types take a finite ``Decimal``, and nothing else.

    ``NaN`` and ``Infinity`` are ``Decimal`` instances and would pass a type check, but
    they break both properties these values are declared with: ``NaN != NaN``, so a
    frozen value would not equal itself, and comparing either raises ``InvalidOperation``
    inside ``sorted()``, which an ``order=True`` type is expected to survive.
    """
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{owner} takes a Decimal, not {type(value).__name__}; "
            "a published value that has been through float is no longer published"
        )
    if not value.is_finite():
        raise ValueError(f"{owner} takes a finite Decimal, not {value}")


@dataclass(frozen=True, slots=True, order=True)
class Percent:
    """A proportion expressed as a percentage -- *"inflation was 2.6%"*."""

    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "Percent")

    # `NotImplemented` rather than a blind `self.value + other.value`: both types carry
    # a `value`, so duck typing alone would add a pp to a Percent and hand back a
    # plausible Percent. mypy stops that at the call site; this stops it at runtime, so
    # the guarantee does not depend on the caller having been type-checked.
    def __add__(self, other: Percent) -> Percent:
        if not isinstance(other, Percent):
            return NotImplemented
        return Percent(self.value + other.value)

    def __sub__(self, other: Percent) -> PercentagePoints:
        """The difference between two percentages is **percentage points**, not percent.

        This is the whole reason the module exists. Returning a ``Percent`` here would
        put the F-005 conflation inside the type that was built to prevent it: *"3.2%
        against 2.6%"* is a movement of 0.6 pp, and 0.6% is a different quantity.
        """
        if not isinstance(other, Percent):
            return NotImplemented
        return PercentagePoints(self.value - other.value)

    def __neg__(self) -> Percent:
        return Percent(-self.value)


@dataclass(frozen=True, slots=True, order=True)
class PercentagePoints:
    """The movement between two percentages -- *"up 0.4 pp on the year"*.

    Spelled ``pp`` in the spine and in the published change columns; the alias below
    carries that spelling into code without creating a second type.
    """

    value: Decimal

    def __post_init__(self) -> None:
        _check(self.value, "PercentagePoints")

    def __add__(self, other: PercentagePoints) -> PercentagePoints:
        if not isinstance(other, PercentagePoints):
            return NotImplemented
        return PercentagePoints(self.value + other.value)

    def __sub__(self, other: PercentagePoints) -> PercentagePoints:
        if not isinstance(other, PercentagePoints):
            return NotImplemented
        return PercentagePoints(self.value - other.value)

    def __neg__(self) -> PercentagePoints:
        return PercentagePoints(-self.value)


#: The spine's and the data contract's spelling. An alias, not a subclass: there is
#: exactly one percentage-point type, under two names.
pp = PercentagePoints
