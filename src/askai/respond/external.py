"""``ExternalAnswer`` -- the third party's half, in a type that cannot become the other.

Purity: orchestration; orders packages, never mutates one.

FR-85 and AD-10 ask for **two answers, never one**. That is easy to write down and easy
to lose: every reconciliation anyone has ever built started as a helper that took the
approved figure and the external text and returned something tidier than both. So the
guarantee here is not a rule, it is an absence.

**``ExternalAnswer`` is a distinct type from ``Answer`` and from ``AnswerPackage``, and
there is no road between them.** No ``from_package``, no ``to_package``, no ``merge``, no
``__add__``, no shared base class and no protocol either satisfies. More to the point,
this type *has none of the fields a merge would need*: no ``elements``, no ``spec``, no
``bindings``, no ``row_ids``, no ``resolution``, no ``source_ref``. A function reaching
for a figure, a period or a unit on an external answer does not fail review -- it fails
``mypy --strict``, because the attribute does not exist. That is FR-86's *"never
reconciles, averages, corrects or arbitrates"* made unrepresentable rather than
forbidden, and ``tests/test_epic9_external_agent.py`` proves it by running the type
checker over a merge somebody might plausibly write.

**It holds prose, and prose is all it holds.** Spine open question 5 closed with the
external agent returning text, not structured figures. Storing that text as text -- never
parsed into a ``Measure``, a ``Period`` or a value -- is what keeps the crossing
impossible at the boundary rather than only at the type: there is no parse step whose
output could be handed to the approved side by mistake.

**The caveat is unconditional** (FR-84, FR-88). ``caveat`` is a required, non-blank field
checked at construction, so there is no external answer anywhere in the tree without one.
It is a *field* rather than an element for the reason Story 9.5 gives for the agent
declaration: an element has a role, a role decides which lens shows it, and the Executive
Lens exists to be short. A caveat a brevity pass can drop is a caveat that disappears
exactly when the figure is quoted out of context.

**And the check states its own limits, or it does not exist** (FR-88a). ``BandCheck``
cannot be constructed without the sentence that says what it did *not* check. A caveat
implying figures were verified when they were not is worse than no caveat, so the type
makes the honest version the only buildable one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from askai.domain.admission import PackageSource
from askai.domain.degradation import Degradation
from askai.ports.external_agent import ExternalOutcome

__all__ = [
    "DEFAULT_CAUTION_BAND",
    "PERCENT_IN_PROSE",
    "BandCheck",
    "ExternalAnswer",
    "band_check",
    "percentages_in",
]


# ------------------------------------------------- the ratified percentage band check


#: The percentages a reader would see in a block of prose: a signed decimal sitting
#: immediately before a per-cent sign, with optional space between.
#:
#: **Ratified, not reinvented** (FR-88). The system being replaced applies exactly this
#: pattern to relayed external text in ``app/main.py`` -- ``-?\d+(?:\.\d+)?(?=\s*%)`` --
#: and the decision here was to keep it rather than write a better one, because "better"
#: would mean a second, untested extractor whose disagreements with the shipped one
#: nobody could explain. It is copied as a *specification of what is checked*; the
#: implementation below is this system's own.
PERCENT_IN_PROSE: Final = re.compile(r"-?\d+(?:\.\d+)?(?=\s*%)")

#: The plausible band, in per cent. The predecessor reads it from a display policy and
#: falls back to 25, and 25 is what shipped. Kept as the default here so the behaviour a
#: reader has seen does not change silently; a deployment that wants another number
#: passes one. It becomes a reader-affecting constant the moment the check is switched on
#: -- see ``BandCheck`` -- and belongs in ``rules/`` at that point rather than here.
DEFAULT_CAUTION_BAND: Final = 25.0

# **Deliberately not carried over.** The predecessor has a second mechanism
# (``app/reasoning.py``'s ``cross_check``) that pairs a percentage in external prose with
# a year, looks the year up in the approved rows, and states the gap within +/-0.3. It is
# arithmetic rather than interpretation and it is carefully written -- and it is exactly
# the crossing FR-85 forbids: a figure from one half read against a figure from the
# other, by the engine, in the engine's own voice. Ratifying the band check and refusing
# the cross-check is the whole of the judgement this module makes, and it is why nothing
# in this module can see an approved row: it imports no port that offers one.


def percentages_in(prose: str) -> tuple[float, ...]:
    """Every percentage the ratified pattern finds in *prose*, in the order it found them.

    Total: text with no percentage in it yields an empty tuple, and a match the float
    constructor cannot read is skipped rather than raised over. This runs on a third
    party's free text, so "it did not parse" is an ordinary Tuesday and never an error.
    """
    found: list[float] = []
    for match in PERCENT_IN_PROSE.findall(prose):
        try:
            found.append(float(match))
        except ValueError:  # a pattern match the float constructor still rejects
            continue
    return tuple(found)


@dataclass(frozen=True, slots=True)
class BandCheck:
    """A plausibility band applied to prose, and an honest account of what it is not.

    **FR-88a is the whole reason this type exists.** A number of percentages were read
    out of a block of text and compared against a fixed band. That is nearly nothing: it
    says whether a figure looks wild, never whether it is right, and it cannot see a
    figure written in words, a level rather than a rate, a currency amount, a date, or a
    percentage the pattern did not match. ``limits`` carries that sentence, in the
    reader's own language, and it is required and non-blank -- so the check cannot be
    shown without it. A caveat implying figures were verified when they were not is worse
    than no caveat, and this is that sentence made into a constructor argument.

    It is an **addition to the caveat and never a replacement for it**: the caveat on
    ``ExternalAnswer`` is unconditional and a clean band check does not soften it. Nothing
    downstream may read a ``BandCheck`` as evidence that a per-figure range check against
    approved data exists, because none does -- see the note above on the cross-check.
    """

    band: float
    limits: str
    found: tuple[float, ...] = ()
    beyond: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.band <= 0.0:
            raise ValueError("a plausibility band is a positive width; zero flags everything")
        if not self.limits.strip():
            raise ValueError(
                "a check states its own limits to the reader (FR-88a); a check shown "
                "without them implies a verification that did not happen, which is worse "
                "than showing no check at all"
            )
        if not set(self.beyond) <= set(self.found):
            raise ValueError(
                "the flagged figures are a subset of the figures found; a check cannot "
                "flag something it did not read"
            )

    @property
    def flagged(self) -> bool:
        """Whether anything fell outside the band. Never a verdict on the answer."""
        return bool(self.beyond)


def band_check(prose: str, limits: str, band: float = DEFAULT_CAUTION_BAND) -> BandCheck:
    """Apply the ratified band to *prose*, stating *limits* alongside it.

    Annotates and never edits. The predecessor relays the external text verbatim and
    appends a caution line; it does not strip an out-of-band figure, rewrite one, or
    withhold the answer -- and neither does this, because a third party's answer with the
    inconvenient numbers removed is an answer the engine has silently authored.
    """
    found = percentages_in(prose)
    return BandCheck(
        band=band,
        limits=limits,
        found=found,
        beyond=tuple(value for value in found if abs(value) > band),
    )


# --------------------------------------------------------------------- the other answer


@dataclass(frozen=True, slots=True)
class ExternalAnswer:
    """The external half of a Combined answer: prose, or the gap where prose would be.

    Frozen, with no field an approved value could occupy. Read the class docstring of
    ``narrate.package.AnswerPackage`` beside this one: they are two types describing two
    answers, and the deliberate absence of anything common to both is the design.

    **It never produces an empty card** (FR-89). Exactly one of ``prose`` and ``reason``
    is non-blank, enforced below: either the third party said something, or the engine
    says plainly that it did not and why. There is no third state in which a heading is
    rendered over nothing, which is what an unavailable external agent used to look like.
    """

    #: Which agent produced this, rendered for the reader in their own language (FR-83).
    #: The same content-not-a-flag argument ``AnswerPackage.agent`` makes, for the same
    #: reason: a declaration a client has to look up is one it can fail to look up.
    agent: str
    #: Unconditional (FR-84, FR-88). Required and non-blank: there is no external content
    #: a reader is not entitled to be warned about, including the content that is a
    #: statement that there is none.
    caveat: str
    outcome: ExternalOutcome
    #: What the third party said, verbatim and unparsed. Blank unless it answered.
    prose: str = ""
    #: The gap, stated. Blank exactly when ``prose`` is not.
    reason: str = ""
    #: The ratified plausibility band, when one was applied, with its limits stated.
    #: ``None`` means **no check ran** -- and nothing downstream may read the absence as a
    #: clean result, nor the presence as a per-figure verification against approved data.
    check: BandCheck | None = None
    #: Wall-clock seconds the external call took, for ``[ASSUMPTION A4]`` (NFR-3).
    elapsed_seconds: float = 0.0
    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        if not self.caveat.strip():
            raise ValueError(
                "an external answer carries its caveat unconditionally (FR-84, FR-88); "
                "unconditional means the type refuses one without it, rather than a "
                "composer remembering to attach one"
            )
        if not self.agent.strip():
            raise ValueError(
                "every answer declares the agent that produced it, in the reader's own "
                "language (FR-83); a declaration that can be omitted goes missing on the "
                "answer that is quoted out of context"
            )
        if bool(self.prose.strip()) == bool(self.reason.strip()):
            raise ValueError(
                "an external answer is prose or a stated gap and never both or neither; "
                "neither is the empty card FR-89 forbids, and both is a gap narrated over "
                "an answer that arrived"
            )
        if (self.outcome is ExternalOutcome.ANSWERED) is not bool(self.prose.strip()):
            raise ValueError(
                f"outcome {self.outcome.value} with "
                f"{'prose' if self.prose.strip() else 'no prose'}; the outcome recorded "
                "in the audit row and the text shown to the reader describe one call"
            )
        if self.check is not None and not self.prose.strip():
            raise ValueError(
                "a band check on an answer with no prose checked nothing; showing it "
                "would imply a verification of text that never arrived"
            )
        if self.elapsed_seconds < 0.0:
            raise ValueError("elapsed time is measured forwards")

    @property
    def source(self) -> PackageSource:
        """Always ``External``, set by the type rather than by a caller (AD-6, Story 9.5).

        A property with no setter and no backing field: the class of external content is
        a fact about which type it is, so there is no argument that could make an
        ``ExternalAnswer`` claim to be approved and no ``dataclasses.replace`` that could
        relabel one.
        """
        return PackageSource.EXTERNAL
