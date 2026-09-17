"""The counter-metric: how often the approved path refused and the external one answered.

Purity: pure -- it classifies a finished response and counts values. Nothing here does
IO, holds process state, or knows a store exists.

Story 9.4 asks for a refusal to be stated rather than quietly outsourced, and then asks
for the quiet outsourcing to be *measured* anyway -- because the failure it guards against
is not a line of code anyone would write. It is drift: the approved knowledge base stops
covering the questions people ask, Combined keeps returning something fluent, and nobody
notices that the thing being read is no longer the thing that was defended. A single
response cannot show that. A rising share of :attr:`Outsourcing.OUTSOURCED` can.

**It is a value, not a counter.** ``degradations.Tally`` makes the argument in full and it
applies here without change: a module-level collector would be shared by two concurrent
requests, would make this module untestable in isolation, and is banned tree-wide. So
:class:`Outsourcing` is computed from what a finished response actually answered, and
:class:`OutsourcedShare` is derived from those verdicts and added with ``+``. There is no
``record()``, no ``reset()`` and nothing to register with. A verdict that is not on a
result is counted nowhere, which is the property that makes the count worth reading.

**The type says what the metric means.** ``OUTSOURCED`` is a named member rather than a
boolean, so the line that reports it cannot be read as "true, good". Its docstring carries
the interpretation -- a rising share is the closed world being quietly outsourced -- where
the person adding a dashboard will see it, rather than in a document they will not.

**It names no package type.** ``observability/`` may not reach into an answer package any
more than ``respond/`` may (AD-2), and Story 1.15 built ``respond/`` generic over an opaque
type for exactly that reason. So the two stances arrive already read off the finished
response by the layer that is allowed to read one, and this module classifies the pair.
That keeps the metric honest about its inputs: it measures what was answered, and it
cannot quietly consult anything else.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "AnswerStance",
    "FinishedResponse",
    "OutsourcedShare",
    "Outsourcing",
    "outsourcing_of",
]


class AnswerStance(StrEnum):
    """What one path did with a question. Closed, and three states rather than two.

    ``ABSENT`` is not ``REFUSED``. A path that was never admitted -- ``{Approved}`` alone
    admits no external answer -- did not decline anything, and counting its silence as a
    refusal would inflate the metric with every single-agent request. This is the same
    separation ``Outcome`` makes between ``Absent`` and ``Failed``, at a different grain.
    """

    #: The path produced an answer the reader can read.
    ANSWERED = "answered"

    #: The path declined, with a cause. For the approved path this is FR-80's refusal.
    REFUSED = "refused"

    #: The path was not admitted, or produced nothing at all. Not a decline.
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class FinishedResponse:
    """What a finished response did, reduced to the two facts the metric turns on.

    Deliberately two fields and both stances. There is no figure here, no prose and no
    package: the metric is a statement about *whether* each path answered, and anything
    more on this type would be an invitation to compute something about the content --
    which is the merge AD-10 makes impossible one layer up.
    """

    approved: AnswerStance
    external: AnswerStance


class Outsourcing(StrEnum):
    """How a finished response divided the work between the two paths.

    A closed classification, so a count by member is a count of four known things rather
    than of whatever strings a call site invented.
    """

    #: The approved path answered. Whatever the external path did, the reader has the
    #: answer the engine can defend, so nothing was outsourced.
    APPROVED_ANSWERED = "approved_answered"

    #: **The counter-metric.** The approved path refused and the external path answered:
    #: the reader asked the engine a question, and what came back is the third party's.
    #: One of these is legitimate and expected -- the gap is real and it was stated. A
    #: *rising share* of them is the closed world being quietly outsourced, and it is the
    #: number to watch, because no single response looks wrong.
    OUTSOURCED = "outsourced"

    #: The approved path refused and the external path did not answer either. An honest
    #: gap, fully stated, and the outcome the closed world is supposed to produce.
    BOTH_SILENT = "both_silent"

    #: The approved path was not admitted at all -- an ``{External}`` request. The closed
    #: world does not apply, so neither does this metric, and folding these into the
    #: denominator would move the share every time the mix of requests moved.
    NOT_MEASURED = "not_measured"


def outsourcing_of(finished: FinishedResponse) -> Outsourcing:
    """Classify *finished*. Pure, total, and computed from what was answered.

    Total by construction: the match is over two closed enums and ``mypy --strict``
    refuses it if a case is missed, so a new stance cannot slip through as an implicit
    "not outsourced" -- which is precisely the direction an error here would fall.
    """
    match finished.approved:
        case AnswerStance.ABSENT:
            return Outsourcing.NOT_MEASURED
        case AnswerStance.ANSWERED:
            return Outsourcing.APPROVED_ANSWERED
        case AnswerStance.REFUSED:
            return (
                Outsourcing.OUTSOURCED
                if finished.external is AnswerStance.ANSWERED
                else Outsourcing.BOTH_SILENT
            )


@dataclass(frozen=True, slots=True)
class OutsourcedShare:
    """How many measured responses were outsourced, out of how many were measurable.

    Frozen and derived, never accumulated into -- ``Tally``'s shape, for ``Tally``'s
    reasons. ``+`` combines two shares on the way up a call chain, which is how a figure
    covering many responses is built without anything owning a mutable total.

    ``measured`` excludes ``NOT_MEASURED``, so the denominator is the set of responses the
    closed world actually governed. A share over all requests would fall simply because
    more people chose ``{External}``, which is the opposite of what a reader of this
    number wants to learn.
    """

    outsourced: int = 0
    measured: int = 0

    def __post_init__(self) -> None:
        if self.outsourced < 0 or self.measured < 0:
            raise ValueError("a share counts responses; a negative count is not one")
        if self.outsourced > self.measured:
            raise ValueError(
                f"{self.outsourced} outsourced of {self.measured} measured; the outsourced "
                "responses are a subset of the measured ones"
            )

    @classmethod
    def over(cls, verdicts: Iterable[Outsourcing]) -> OutsourcedShare:
        """The share across *verdicts* -- the only way one is built."""
        outsourced = 0
        measured = 0
        for verdict in verdicts:
            if verdict is Outsourcing.NOT_MEASURED:
                continue
            measured += 1
            if verdict is Outsourcing.OUTSOURCED:
                outsourced += 1
        return cls(outsourced=outsourced, measured=measured)

    @property
    def per_cent(self) -> int | None:
        """The share as a whole percentage, or ``None`` when nothing was measurable.

        ``None`` rather than zero: no measured responses is not a share of zero, and a
        dashboard plotting zero for an empty window would show the metric at its healthiest
        exactly when it is saying nothing at all.
        """
        if self.measured == 0:
            return None
        return round(self.outsourced * 100 / self.measured)

    def __add__(self, other: OutsourcedShare) -> OutsourcedShare:
        return OutsourcedShare(
            outsourced=self.outsourced + other.outsourced,
            measured=self.measured + other.measured,
        )
