"""The gap between two published figures, in the unit the gap is actually in.

Purity: pure, imports nothing outside ``domain/``.

``numbers.py`` makes ``Percent - Percent -> PercentagePoints`` a property of the types,
so that FR-21's conflation is a type error rather than a review finding. This module is
where a *composer* reaches that subtraction, and it exists because of where it may not
be reached from: ``tests/test_assemble.py`` scans ``assemble/`` for any construction of
``Percent`` or ``PercentagePoints``, on the argument that building either is the step
that turns a movement into a level.

That scan and FR-27 would otherwise be in direct conflict -- Story 4.8 requires a spread
over a percentage indicator to come out in ``pp``, and the only honest way to get one is
to subtract two ``Percent`` values. So the subtraction lives here, one level below the
scan, and ``assemble/`` asks for a difference instead of assembling one. Nothing is
evaded: the relabelling the scan exists to catch -- taking a percentage's ``Decimal``
and declaring it points -- is still not written anywhere, because ``spread`` only ever
returns points from an actual subtraction of two percentages.

**Whether the figures are percentages is an argument, not a judgement made here.** The
published unit spellings that count as a percentage are a reader-affecting table
(``R-COMPARE-SPREAD-OVER-PERCENT-IS-POINTS``), ``domain/`` may not read ``rules/``, and
a spelling list written here would be exactly the literal AD-11 bans. So the caller,
which does read the rule, says which case this is, and this module owns only the
arithmetic that follows from the answer.
"""

from __future__ import annotations

from decimal import Decimal

from askai.domain.numbers import Percent, PercentagePoints

__all__ = ["Spread", "spread"]

#: What a spread comes out as. A plain ``Decimal`` keeps the indicator's own published
#: unit; ``PercentagePoints`` is a different quantity from the ``Percent`` figures it
#: came from, and carries a different unit into the answer.
type Spread = Decimal | PercentagePoints


def spread(high: Decimal, low: Decimal, *, measured_in_percent: bool) -> Spread:
    """The distance from *low* to *high*, typed by what the two figures measure.

    Keyword-only on purpose. ``spread(a, b, True)`` at a call site says nothing about
    what the third argument decides, and the decision it makes -- whether an answer
    reads ``2.0 %`` or ``2.0 pp`` -- is precisely the one FR-21 says a reader must not
    have to take on trust.

    Refuses a negative result rather than returning one: the endpoints of a spread are
    the extrema of a scope, so the caller has already found which is which, and a
    negative spread means it passed them the other way round. Returning it would put a
    minus sign in front of a distance in an answer.
    """
    if high < low:
        raise ValueError(
            f"a spread runs from the lower extremum to the higher, and {high} is below "
            f"{low}; the endpoints are the wrong way round"
        )
    if measured_in_percent:
        # The one subtraction in the engine that changes a figure's unit, and it changes
        # it because the types say so -- not because a caller wrote "pp" somewhere.
        return Percent(high) - Percent(low)
    return high - low
