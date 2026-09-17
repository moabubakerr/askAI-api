"""Correcting a premise the published data contradicts, before answering it.

Purity: pure.

Story 2.10, FR-41. *"Why did inflation fall to 0.2%?"* carries an assertion as well as a
question, and answering the question while leaving the assertion standing is how a
briefing gets built on a figure nobody published. So when the bound data contradicts the
asserted figure, the correction is composed **first** and the answer follows it.

**First, because it answers the question that was actually asked** (FR-58). The
correction is a ``Placed`` of role ``headline`` returned ahead of the ordinary headline,
so its position is a property of the tuple the composer builds rather than a sort the
client is trusted to perform.

**In both lenses** (FR-59d). ``headline`` is named by both ``executive_roles`` and
``explore_roles`` in ``R-ROLE-LENS-MAPPING``, so an executive is not shielded from the
fact that their premise was wrong. That is why the correction takes the headline role
rather than a note: brevity may remove detail and may not remove what makes the answer
defensible, and a correction the short lens drops is a correction nobody reads.

**With full provenance.** The correction carries the published figure, and it is built
from the same ``Provenance`` the headline is, through the same ``Formatter`` -- so it is
admitted against the loaded published layer exactly as every other element is (AD-7),
and a correction whose row has since been retired is refused rather than shown.

**Contradiction is exact, and it is arithmetic rather than text.** Two ``Decimal``
values are compared numerically, so ``2.6`` and ``2.60`` are the same premise and do not
produce a correction, while ``0.2`` and ``2.6`` are different and do.
``R-PREMISE-CONTRADICTION-IS-EXACT`` records the decision and why a tolerance was not
introduced: a near-miss tolerance would silently accept a wrong figure in a briefing,
which is the whole of what this story prevents.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from askai.assemble.elements import measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.presentation import PublishedDetail

__all__ = ["AssertedFigure", "PremiseMessage", "contradicts", "correction_element"]


class PremiseMessage:
    """The message ids this module renders. Ids, not wording."""

    CORRECTED = "premise.corrected"


class PremiseRule:
    """The rule ids the behaviour here is recorded under, for the answer's record."""

    CONTRADICTION_IS_EXACT = "R-PREMISE-CONTRADICTION-IS-EXACT"
    CORRECTION_LEADS = "R-PREMISE-CORRECTION-LEADS"


@dataclass(frozen=True, slots=True)
class AssertedFigure:
    """A figure the question states as true, as it was read from the question.

    A value and nothing else. It deliberately carries no unit and no period of its own:
    the engine corrects a premise against the figure it actually bound, and a premise
    carrying its own period would invite a comparison against a row the question never
    reached. What was compared is said by the correction's provenance.
    """

    value: Decimal


def contradicts(asserted: AssertedFigure, published: Decimal) -> bool:
    """Does the published figure contradict what the question asserted?

    Numeric equality on ``Decimal``, so trailing zeros are not a contradiction and a
    genuinely different figure always is. No tolerance: see the module docstring.
    """
    return asserted.value != published


def correction_element(
    catalogue: Catalogue,
    lang: Lang,
    formatter: Formatter,
    placement: Placement,
    provenance: Provenance,
    published: PublishedDetail,
    value: Decimal,
    period_text: str | None = None,
) -> Placed:
    """The correction, carrying the published figure with its full provenance.

    The role is not an argument. ``Role.HEADLINE`` is returned by the constructor, so
    *"the correction is first and appears in both lenses"* is a property of this function
    rather than a habit of its callers -- and the display mode is asked for by role
    (AD-18), never named here.
    """
    role = Role.HEADLINE
    written = formatter.format(
        value,
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        lang,
    )
    period = (
        period_text
        if period_text is not None
        else render_period(catalogue, lang, provenance.period)
    )
    content = render(
        catalogue,
        lang,
        PremiseMessage.CORRECTED,
        detail=published.name,
        value=written.value,
        unit=written.unit,
        period=period,
    )
    return Placed(element=measured(content, provenance), role=role)
