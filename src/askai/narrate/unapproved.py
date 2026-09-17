"""Improving a refusal from the unapproved catalogue, without letting any of it through.

Purity: pure. It imports no port and no adapter, which is the point of the module.

Story 2.8, FR-38a, AD-12. The CMS holds 531 indicators and 189 of them reached readers.
A reader who names one of the other 342 is asking a **sensible question about a real
indicator**, and *"I do not hold an indicator matching that"* tells them to go and
rephrase a question no rephrasing will answer. *"That exists and is not approved for
publication"* tells them the gap is editorial and to stop.

**Only existence crosses, and it crosses as a boolean.** The whole of this module's
contact with the base layer is ``CatalogueProbe``: a callable taking the reader's own
words and answering ``True``, ``False`` or ``None``. No value, period, definition, unit,
id or *name* comes back -- there is no type here for one to arrive on, and nothing in
this package imports ``askai.ports.unpublished_catalogue`` or the adapter behind it. That
is the structural form of *"no type crosses from ``UnpublishedCatalogPort`` into
``Answer``"*: it is not a rule composition is asked to obey, it is a shape in which
disobeying it does not type-check. ``tests/test_unapproved_refusal.py`` asserts it by
walking every type reachable from ``Answer`` and ``AnswerPackage``, and by scanning the
answer path's imports.

**The upgrade is from one cause only.** ``NO_SUCH_INDICATOR`` is the only refusal the
unapproved catalogue can improve, because it is the only one whose claim the catalogue
can contradict. A detail that is published and empty, a period with no row, an
unsupported question and an outage all remain what they were -- upgrading an outage into
*"not approved for publication"* would be the AD-15 defect wearing a better sentence.

**``None`` is not ``False``.** A catalogue that could not be read has not said the
indicator is absent; it has said nothing. So the refusal falls back to the plain
*"no such indicator"* it would have been anyway, and carries a typed ``Degradation``
beside it, so that an editorial gap being reported as a lexical one is visible to an
operator instead of being invisible to everybody (AD-15). It never fails the answer, and
it never guesses the other way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from askai.domain.degradation import Degradation
from askai.narrate.refusal import RefusalCode
from askai.observability.degradations import DegradationKind, degrade

__all__ = [
    "UPGRADES_FROM",
    "WHERE",
    "CatalogueProbe",
    "UnapprovedRule",
    "Verdict",
    "improved_refusal",
]

#: The reader's words in, existence out -- ``True`` held, ``False`` not held, ``None``
#: the catalogue could not be read.
#:
#: A plain callable over builtins rather than the port protocol, deliberately. A
#: composer that held the port could ask it for ``names()``, and the next hand would put
#: one in a sentence; a composer that holds this can ask one question and receive one
#: bit. The three states are three because *"absent"* and *"unknown"* are different
#: facts and are answered differently below.
type CatalogueProbe = Callable[[str], bool | None]


class UnapprovedRule:
    """The rule ids this module's behaviour is recorded under, for the answer's record."""

    IS_A_DISTINCT_REFUSAL = "R-UNAPPROVED-IS-A-DISTINCT-REFUSAL"
    LEAKS_NOTHING = "R-UNAPPROVED-LEAKS-NOTHING"
    UNREACHABLE_DEGRADES = "R-UNAPPROVED-UNREACHABLE-DEGRADES"


#: The address a degradation raised here carries, so a rising rate has somewhere to go.
WHERE: Final = "narrate.unapproved"

#: The one refusal the unapproved catalogue is allowed to improve. Named rather than
#: written into the branch below, so that widening it is an edit a reviewer sees.
UPGRADES_FROM: Final = RefusalCode.NO_SUCH_INDICATOR


@dataclass(frozen=True, slots=True)
class Verdict:
    """Which of the six to say, and anything that went wrong deciding it.

    The degradations travel on the value rather than through a collector, like every
    other soft failure in this engine: the composer that asked splices them into the
    package it builds, and two requests cannot read each other's.
    """

    code: RefusalCode
    degradations: tuple[Degradation, ...] = ()


def improved_refusal(
    code: RefusalCode, named: str, probe: CatalogueProbe | None
) -> Verdict:
    """*code*, improved to *not approved for publication* where the base layer holds it.

    Deterministic: the same words and the same catalogue give the same verdict on every
    run, because the only input is one boolean question asked once. Safe by default --
    every path that is not a clear *yes* returns the refusal that was already going to be
    given:

    * no probe (a deployment wired without the base layer) -- unchanged, and **not** a
      degradation: an engine that was never given the catalogue has not lost it, and
      counting that as a fault would report an outage on every refusal it ever gives;
    * nothing named -- unchanged; there are no words to ask about;
    * a cause other than ``NO_SUCH_INDICATOR`` -- unchanged, whatever the probe says;
    * ``None`` from the probe -- unchanged, with a typed ``Degradation`` (AD-15);
    * ``False`` -- unchanged, which is the honest answer and the common one.
    """
    if code is not UPGRADES_FROM or probe is None:
        return Verdict(code)
    asked = named.strip()
    if not asked:
        return Verdict(code)
    held = probe(asked)
    if held is None:
        return Verdict(
            code,
            (
                degrade(
                    DegradationKind.ADAPTER_UNAVAILABLE,
                    WHERE,
                    "the unapproved catalogue could not be read, so an indicator the CMS "
                    "holds may have been refused as one it does not hold; the weaker "
                    "refusal is given rather than a guess in either direction",
                ),
            ),
        )
    if not held:
        return Verdict(code)
    return Verdict(RefusalCode.NOT_APPROVED_FOR_PUBLICATION)
