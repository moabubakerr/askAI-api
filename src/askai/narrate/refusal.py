"""The six refusals: six causes, six codes, six sentences a reader can tell apart.

Purity: pure.

Story 2.7. FR-38 names six reasons the engine cannot answer, and they are six because a
reader acts on each of them differently:

1. **no such indicator** -- nothing in the published catalogue matches what was named;
2. **not approved for publication** -- the CMS holds it and the published layer does not;
3. **published but has no data** -- the detail exists and carries no datapoint at all;
4. **no data for this period, grain or country** -- it carries data, and none here;
5. **the question is unsupported** -- well formed, and not a query this engine performs;
6. **the data could not be reached** -- a fault in the engine, not an absence in the data.

**Collapsing any two is the failure this module prevents.** Before it,
``narrate.structured`` mapped eleven ``FigureCause`` members and every ``UnboundReason``
onto three sentences, so a QC tester could not tell a data gap from a catalogue gap, and
the difference between (2) and (3) -- editorial versus empty -- disappeared entirely.
``tests/test_refusals.py`` asserts the six renderings are pairwise distinct **in both
languages**, which is the property that cannot be restored once it is lost.

**A code beside the id.** ``RefusalCode`` is the stable machine half: it does not change
when a wording is fixed in ``messages/data``, so a dashboard counting refusals keeps
counting the same thing across an editorial change. The wording half is a message id in
both catalogue files and nothing else -- there is no sentence in this module.

**Counted by cause.** ``RefusalTally`` is the coverage-ceiling metric the PRD asks for: a
refusal rate that rises is only alarming once you know *which* cause rose. A rising
``DATA_COULD_NOT_BE_REACHED`` is an outage; a rising ``PUBLISHED_WITH_NO_DATA`` is the
28 empty details being asked about, which is the engine being honest. It is a frozen
value derived from what a result already carries, like ``observability.Tally`` and for
the same reason: a module-level counter is the ambient state AD-15 rules out, and two
requests can corrupt one.

**A failure is never worded as an absence** (AD-15, findings 23/128/150). Cause (6) is
the only one reached from a ``Degradation``, it has its own id, and no path in this
package can render an unreachable dependency as *"no approved figures"*.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from askai.compile.binding import UnboundReason
from askai.execute.value import FigureCause
from askai.messages import Catalogue, Lang, render

__all__ = [
    "REFUSAL_MESSAGE_IDS",
    "RefusalCode",
    "RefusalTally",
    "refusal_for",
    "refusal_for_unbound",
    "refusal_message_id",
    "refusal_statement",
]


class RefusalCode(StrEnum):
    """FR-38's six causes, as stable machine codes.

    Closed, and closed on purpose: a seventh cause is a reviewable act in this file with
    a sentence in both catalogue files beside it, never a string invented at a call site.
    The values are kebab-case like every other code in the engine, and they are stable --
    a wording fix in ``messages/data`` never touches one.
    """

    NO_SUCH_INDICATOR = "no-such-indicator"
    """Nothing published matches the indicator the question named."""

    NOT_APPROVED_FOR_PUBLICATION = "not-approved-for-publication"
    """The CMS holds it; the published layer does not (FR-38a, Story 2.8's cause)."""

    PUBLISHED_WITH_NO_DATA = "published-with-no-data"
    """The detail is in the catalogue and carries no datapoint at all -- 28 of 189."""

    NO_DATA_FOR_THIS_SELECTION = "no-data-for-this-selection"
    """It carries data, and none for this period, grain or country."""

    QUESTION_NOT_SUPPORTED = "question-not-supported"
    """Well formed, and not a query this engine performs on the published data."""

    DATA_COULD_NOT_BE_REACHED = "data-could-not-be-reached"
    """A fault here, not an absence there. The only cause that is a ``Degradation``."""


#: The message id each code is said with, in whichever language the question was asked.
#:
#: One id per code and no id shared by two, which is what makes the six *distinct*
#: rather than six labels on three sentences. Two of them are ids the catalogue already
#: carried and that already say exactly this: ``refusal.not_supported`` is (5), and
#: ``failure.data_unavailable`` is (6) and is already worded as a fault rather than as an
#: absence. Reusing them is deliberate -- a second id with the same meaning is the drift
#: the single catalogue exists to prevent.
REFUSAL_MESSAGE_IDS: Final[Mapping[RefusalCode, str]] = MappingProxyType({
    RefusalCode.NO_SUCH_INDICATOR: "refusal.no_such_indicator",
    RefusalCode.NOT_APPROVED_FOR_PUBLICATION: "refusal.not_approved_for_publication",
    RefusalCode.PUBLISHED_WITH_NO_DATA: "refusal.published_but_no_data",
    RefusalCode.NO_DATA_FOR_THIS_SELECTION: "refusal.no_data_for_this_selection",
    RefusalCode.QUESTION_NOT_SUPPORTED: "refusal.not_supported",
    RefusalCode.DATA_COULD_NOT_BE_REACHED: "failure.data_unavailable",
})


#: Every ``FigureCause`` the fetch can produce, against the refusal it is said as.
#:
#: Total over the closed set, and checked to be total at import by ``_check_total``: a
#: cause with no entry would reach a reader as a blank, which is the shape an error used
#: to take. Written as a table rather than as a ``match`` so that the mapping is a thing
#: a reviewer can read in one screen and a test can iterate.
_FROM_FIGURE_CAUSE: Final[Mapping[FigureCause, RefusalCode]] = MappingProxyType({
    # An unbound field. The reason code on the field says more than the cause does, so
    # `refusal_for_unbound` is preferred where the spec carries one; these are the
    # answers for a field whose reason could not be read.
    FigureCause.DETAIL_NOT_BOUND: RefusalCode.NO_SUCH_INDICATOR,
    FigureCause.PERIOD_NOT_BOUND: RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    # Bound, and not the single-figure fetch the engine performs.
    FigureCause.COUNTRY_SCOPE_NOT_BOUND: RefusalCode.QUESTION_NOT_SUPPORTED,
    FigureCause.MEASURE_NOT_BOUND: RefusalCode.QUESTION_NOT_SUPPORTED,
    FigureCause.OPERATION_NOT_BOUND: RefusalCode.QUESTION_NOT_SUPPORTED,
    FigureCause.OPERATION_IS_NOT_A_VALUE: RefusalCode.QUESTION_NOT_SUPPORTED,
    FigureCause.SCOPE_IS_NOT_ONE_SERIES: RefusalCode.QUESTION_NOT_SUPPORTED,
    FigureCause.CHANGE_IS_A_PUBLISHED_COLUMN: RefusalCode.QUESTION_NOT_SUPPORTED,
    # The catalogue holds the detail and the detail holds nothing -- 28 of 189.
    FigureCause.DETAIL_PUBLISHES_NOTHING: RefusalCode.PUBLISHED_WITH_NO_DATA,
    # It holds rows, and none in this country scope, at this grain, or at this period.
    FigureCause.SCOPE_PUBLISHES_NOTHING: RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    FigureCause.NO_READING_AT_OR_BEFORE_TODAY: RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD: RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    FigureCause.MEASURE_NOT_PUBLISHED: RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    # The row is intact and publishes a rating rather than a number. Not an empty
    # detail and not an empty period: the published data cannot answer *this* question,
    # which is (5) and is why 21 details answering in words are not reported as gaps.
    FigureCause.VALUE_IS_NOT_A_FIGURE: RefusalCode.QUESTION_NOT_SUPPORTED,
    # The one cause that is a failure. Never worded as an absence (AD-15).
    FigureCause.LOOKUP_FAILED: RefusalCode.DATA_COULD_NOT_BE_REACHED,
})


#: Every ``UnboundReason`` ``compile/`` can record, against the refusal it is said as.
#:
#: Total over the closed set. Several of these are *clarifications* before they are
#: refusals -- ``narrate.clarify`` is asked first, and only a state it declines to put
#: as a closed question reaches here -- but the mapping is total anyway, because a
#: reason with no refusal would be a reader shown nothing on whichever path skipped the
#: question.
_FROM_UNBOUND_REASON: Final[Mapping[UnboundReason, RefusalCode]] = MappingProxyType({
    UnboundReason.NO_DETAIL_NAMED: RefusalCode.NO_SUCH_INDICATOR,
    UnboundReason.DETAIL_NAME_IS_SHARED: RefusalCode.NO_SUCH_INDICATOR,
    UnboundReason.SEVERAL_INDICATORS_MATCH: RefusalCode.NO_SUCH_INDICATOR,
    UnboundReason.NO_INDICATOR_RESOLVED: RefusalCode.NO_SUCH_INDICATOR,
    # FR-6: no adjacent grain is ever substituted, so a reader who asked for a quarter of
    # something published only yearly is told the question cannot be answered as asked --
    # not that the indicator is missing, which would be false.
    UnboundReason.GRAIN_NOT_PUBLISHED: RefusalCode.QUESTION_NOT_SUPPORTED,
    UnboundReason.MORE_THAN_ONE_PERIOD_NAMED: RefusalCode.QUESTION_NOT_SUPPORTED,
    UnboundReason.PERIOD_RANGE_RUNS_BACKWARDS: RefusalCode.QUESTION_NOT_SUPPORTED,
})


def _check_total() -> None:
    """Both tables cover their closed set, checked when this module is imported.

    At import rather than in a test, because the consequence of a gap is a reader shown
    a blank where a sentence belongs, and a process that would do that should not start.
    """
    for name, covered, declared in (
        ("FigureCause", frozenset(_FROM_FIGURE_CAUSE), frozenset(FigureCause)),
        ("UnboundReason", frozenset(_FROM_UNBOUND_REASON), frozenset(UnboundReason)),
    ):
        missing = sorted(member.value for member in declared - covered)
        if missing:
            raise ValueError(
                f"{name} members with no refusal: {missing}; every cause is said as one "
                "of the six, or it reaches a reader as a blank"
            )
    uncovered = sorted(
        code.value for code in RefusalCode if code not in REFUSAL_MESSAGE_IDS
    )
    if uncovered:
        raise ValueError(f"refusal codes with no message id: {uncovered}")
    ids = list(REFUSAL_MESSAGE_IDS.values())
    if len(set(ids)) != len(ids):
        raise ValueError(
            "two refusal codes share a message id; six causes said in five sentences is "
            "the collapse Story 2.7 exists to prevent"
        )


_check_total()


def refusal_for(cause: FigureCause) -> RefusalCode:
    """Which of the six *cause* is said as. Total over the closed ``FigureCause`` set."""
    return _FROM_FIGURE_CAUSE[cause]


def refusal_for_unbound(reason: UnboundReason) -> RefusalCode:
    """Which of the six an unbound field is said as. Total over ``UnboundReason``."""
    return _FROM_UNBOUND_REASON[reason]


def refusal_message_id(code: RefusalCode) -> str:
    """The catalogue id *code* is worded by, in whichever language was asked."""
    return REFUSAL_MESSAGE_IDS[code]


def refusal_statement(catalogue: Catalogue, lang: Lang, code: RefusalCode) -> str:
    """The sentence for *code*, in *lang*, from the bilingual catalogue and nowhere else."""
    return render(catalogue, lang, refusal_message_id(code))


@dataclass(frozen=True, slots=True)
class RefusalTally:
    """How many refusals of each cause happened -- the PRD's coverage metric.

    Frozen and derived, never accumulated into, for the reason
    ``observability.degradations.Tally`` is: a counter a caller can reach is a counter
    two requests can corrupt, and a module-level one is the ambient state AD-15 rules
    out. ``+`` is how a count travels up a call chain without a collector.

    A cause with a zero count is **absent** rather than present-as-zero: the tally says
    what happened, and ``RefusalCode`` already says what could.
    """

    #: Sorted by code value, so two tallies of the same multiset compare and hash equal.
    counts: tuple[tuple[RefusalCode, int], ...] = ()

    def __post_init__(self) -> None:
        codes = [code for code, _ in self.counts]
        if codes != sorted(codes):
            raise ValueError("a tally is held in code order; build one with RefusalTally.of")
        if len(set(codes)) != len(codes):
            raise ValueError("a tally holds one entry per cause; a repeated code is two counts")
        for code, count in self.counts:
            if count < 1:
                raise ValueError(
                    f"{code.value} is tallied {count}; an absent cause is simply absent"
                )

    @classmethod
    def of(cls, codes: Iterable[RefusalCode]) -> RefusalTally:
        """Count *codes* by cause."""
        totals: dict[RefusalCode, int] = {}
        for code in codes:
            totals[code] = totals.get(code, 0) + 1
        return cls(counts=tuple(sorted(totals.items(), key=lambda pair: pair[0].value)))

    @property
    def total(self) -> int:
        """How many refusals in all -- the number a bare rate would report on its own."""
        return sum(count for _, count in self.counts)

    def count(self, code: RefusalCode) -> int:
        """How many refusals of *code*; zero if none."""
        for candidate, found in self.counts:
            if candidate is code:
                return found
        return 0

    def as_mapping(self) -> Mapping[RefusalCode, int]:
        """A read-only view, for a metrics sink that wants a mapping."""
        return MappingProxyType(dict(self.counts))

    def __add__(self, other: RefusalTally) -> RefusalTally:
        totals: dict[RefusalCode, int] = dict(self.counts)
        for code, count in other.counts:
            totals[code] = totals.get(code, 0) + count
        return RefusalTally(counts=tuple(sorted(totals.items(), key=lambda pair: pair[0].value)))

    def __bool__(self) -> bool:
        return bool(self.counts)
