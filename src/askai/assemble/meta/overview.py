"""The executive overview -- the reviewed national set, each member at its own latest.

Purity: pure.

*"What's the latest in the national economy?"* used to return one indicator. FR-31 says it
returns the published curated set, and AD-11 says which set that is comes from the
catalogue rather than from here: ``R-OVERVIEW-SET-IS-A-PUBLISHED-CLASSIFICATION`` names a
classification, and the members are whatever that classification holds when the question
is asked. Measured 2026-09-16, ``NationalIndicators`` holds exactly 8 -- and the 8 are
nowhere in this file, which is what makes the answer defensible when a Council member asks
why these and not others. The answer is *because the people who own the data reviewed
them*, and the code cannot make that untrue.

**No common period is forced** (FR-31a, FR-24). Gross National Income stops at 2023 while
Government Revenues reaches 2026-Q1. A single period across the set would either drop the
members that do not reach it or misdate the ones that do not start there, and a briefing
that silently misdates a figure is worse than one that gives fewer. So each member carries
its own period, and each period is written **beside its own name** rather than in a second
list the reader has to pair positionally -- the catalogue's R-171, which exists because
pairing by position is how the wrong period gets read onto the right indicator.

**Two elements per fact, on purpose.** The briefing line is one ``derived`` element: it is
computed here from the members, with every input stated in its own content. Each member is
*also* emitted as a ``measured`` evidence element carrying **its own datapoint
provenance** -- so a member whose published row has gone stale between refresh and question
is refused on its own, by name, rather than taking the briefing with it or riding along
inside a sentence sourced to something else.

**Short, because F-021 says so.** One figure per member and nothing else. The recorded
failure was a technically correct answer a tester rejected with *"I did not ask for all of
this"*, which makes length a correctness property of this answer rather than a preference.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.elements import measured
from askai.assemble.format import Figure, Formatter, PublishedFormat
from askai.assemble.meta.reference import (
    CatalogueReference,
    ReferenceKind,
    catalogue_element,
)
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.element import ElementClass
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.groups import Group
from askai.rules import RuleSet

__all__ = [
    "OverviewClause",
    "OverviewMember",
    "OverviewMessage",
    "OverviewReading",
    "OverviewRule",
    "max_concurrent_fetches",
    "overview_classification",
    "overview_elements",
]


class OverviewMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    STATEMENT = "overview.statement"
    MEMBER = "overview.member"
    MEMBER_ABSENT = "overview.member_absent"
    MEMBER_SEPARATOR = "overview.member_separator"
    OWN_PERIOD_NOTE = "overview.own_period_note"


class OverviewRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    SET = "R-OVERVIEW-SET-IS-A-PUBLISHED-CLASSIFICATION"
    OWN_LATEST = "R-OVERVIEW-EACH-MEMBER-AT-ITS-OWN-LATEST"
    FAN_OUT = "R-OVERVIEW-FAN-OUT-BOUND"
    SHORT_READ = "R-OVERVIEW-IS-A-SHORT-READ"


class OverviewClause(StrEnum):
    """The clause names read off those rules."""

    CLASSIFICATION = "classification"
    FORCE_COMMON_PERIOD = "force_a_common_period"
    MAX_CONCURRENT_FETCHES = "max_concurrent_fetches"
    ONE_FIGURE_PER_MEMBER = "one_figure_per_member"


class OverviewError(LookupError):
    """The overview rules cannot be acted on, or were asked something they do not answer."""


@dataclass(frozen=True, slots=True)
class OverviewReading:
    """One member's published figure, and everything needed to write it down.

    The provenance is a real ``Provenance`` over a datapoint row, not a catalogue
    reference: an overview member *is* a published figure, and giving it the catalogue's
    envelope would mean a figure in an answer whose reference resolves because a
    classification exists. The three fields travel together because a value without its
    published format is a value that would be written at whatever precision the caller
    happened to have to hand -- the F-004 defect, arriving through a dataclass.
    """

    value: Figure
    provenance: Provenance
    published: PublishedFormat


@dataclass(frozen=True, slots=True)
class OverviewMember:
    """One member of the curated set: an indicator, its name, and its latest reading.

    ``reading`` is ``None`` when the member publishes no figure at all. That is a real
    state rather than a defensive one -- 28 of the 289 published details carry no data
    points -- and it is a field rather than an omission from the list because a member
    dropped for publishing nothing would make the overview quietly shorter than the
    reviewed set it claims to cover.
    """

    indicator_id: str
    name: str
    reading: OverviewReading | None


def overview_classification(rule_set: RuleSet) -> str:
    """Which published classification carries the curated set.

    A read rather than a constant. The set is reviewable and changeable by the people who
    own the data (FR-31, AD-11), and this is the one clause that says where to look for
    what they reviewed.
    """
    value = rule_set.value(OverviewRule.SET.value, OverviewClause.CLASSIFICATION.value)
    if not isinstance(value, str) or not value.strip():
        raise OverviewError(
            f"{OverviewRule.SET.value} value `{OverviewClause.CLASSIFICATION.value}` "
            f"must name a published classification, not {value!r}; the engine holds no "
            "list of headline indicators to fall back to, deliberately"
        )
    return value


def max_concurrent_fetches(rule_set: RuleSet) -> int:
    """The stated fan-out bound for the per-member fetches (NFR-2).

    Read here and applied by whichever layer does the fetching, so the bound is one
    reviewed number rather than a worker count buried in an executor. Stated rather than
    unlimited: an unbounded fan-out over a classification that grows is a load
    characteristic nobody declared.
    """
    value = rule_set.value(OverviewRule.FAN_OUT.value, OverviewClause.MAX_CONCURRENT_FETCHES.value)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OverviewError(
            f"{OverviewRule.FAN_OUT.value} value "
            f"`{OverviewClause.MAX_CONCURRENT_FETCHES.value}` must be a positive whole "
            f"number of concurrent fetches, not {value!r}"
        )
    return value


def overview_elements(
    catalogue: Catalogue,
    lang: Lang,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
    classification: Group,
    members: Sequence[OverviewMember],
) -> tuple[Placed, ...]:
    """The briefing, its members as evidence, and the statement about its periods.

    Returns, in order: one ``headline`` element carrying the whole short read, one
    ``evidence`` element per member carrying that member's own figure and provenance, and
    one ``note`` recording that each figure is at its own latest period.

    Nothing here chooses a precision. Each figure is written at the mode its **role**
    implies, asked of ``Placement`` -- so the same published value appears rounded in the
    briefing and at published precision in the evidence beside it, which is AD-18 working
    rather than a discrepancy.
    """
    _refuse_a_common_period(rule_set)
    _require_one_figure_per_member(rule_set)
    reference = CatalogueReference(kind=ReferenceKind.CLASSIFICATION, key=classification.key)
    separator = render(catalogue, lang, OverviewMessage.MEMBER_SEPARATOR.value)
    briefing = render(
        catalogue,
        lang,
        OverviewMessage.STATEMENT.value,
        group=_name(classification, lang),
        members=separator.join(
            _member_words(catalogue, lang, formatter, placement, Role.HEADLINE, member)
            for member in members
        ),
    )
    composed: list[Placed] = [
        Placed(
            # `derived`: computed here from the members, with every input stated in the
            # content and each one separately admitted as evidence below. A briefing line
            # is not a published row and would be `measured` only by mislabelling.
            element=catalogue_element(briefing, ElementClass.DERIVED, reference),
            role=Role.HEADLINE,
        )
    ]
    composed += [
        _member_evidence(catalogue, lang, formatter, placement, member) for member in members
    ]
    composed.append(
        Placed(
            element=catalogue_element(
                render(catalogue, lang, OverviewMessage.OWN_PERIOD_NOTE.value),
                ElementClass.DERIVED,
                reference,
            ),
            role=Role.NOTE,
        )
    )
    return tuple(composed)


def _member_evidence(
    catalogue: Catalogue,
    lang: Lang,
    formatter: Formatter,
    placement: Placement,
    member: OverviewMember,
) -> Placed:
    """One member, shown as published, sourced to its own row.

    A member that publishes nothing is sourced to the **indicator** instead, because there
    is no row to point at and the statement is still about something the catalogue holds.
    Class ``absent`` rather than omitted: the reviewed set has as many members as it has,
    and a briefing that drops the silent ones covers less than it says it does.
    """
    reading = member.reading
    if reading is None:
        content = render(catalogue, lang, OverviewMessage.MEMBER_ABSENT.value, name=member.name)
        return Placed(
            element=catalogue_element(
                content,
                ElementClass.ABSENT,
                CatalogueReference(kind=ReferenceKind.INDICATOR, key=member.indicator_id),
            ),
            role=Role.EVIDENCE,
        )
    content = _member_words(catalogue, lang, formatter, placement, Role.EVIDENCE, member)
    # Built through `assemble/elements.py` rather than through `catalogue_element`: this
    # one carries a real datapoint provenance, so it is an ordinary published element and
    # goes through the ordinary constructor. The catalogue envelope is for facts that have
    # no row, and a figure that has one must not borrow it.
    return Placed(element=measured(content, reading.provenance), role=Role.EVIDENCE)


def _member_words(
    catalogue: Catalogue,
    lang: Lang,
    formatter: Formatter,
    placement: Placement,
    role: Role,
    member: OverviewMember,
) -> str:
    """*"Real GDP, 712.4, QAR billion, 2025"* -- name, figure and period, written together.

    The period sits inside the member's own sentence rather than in a parallel list, which
    is R-171 and is why the wording takes both in one render call. A member publishing
    nothing says so in the same position, so the reader's eye does not have to change
    shape half way down the briefing.
    """
    reading = member.reading
    if reading is None:
        return render(catalogue, lang, OverviewMessage.MEMBER_ABSENT.value, name=member.name)
    written = formatter.format(reading.value, reading.published, placement.mode_for(role), lang)
    return render(
        catalogue,
        lang,
        OverviewMessage.MEMBER.value,
        name=member.name,
        value=written.value,
        unit=written.unit,
        period=render_period(catalogue, lang, reading.provenance.period),
    )


def _name(group: Group, lang: Lang) -> str:
    match lang:
        case Lang.EN:
            first, second = group.name_en, group.name_ar
        case Lang.AR:
            first, second = group.name_ar, group.name_en
    return first.strip() or second.strip() or group.key


def _refuse_a_common_period(rule_set: RuleSet) -> None:
    """The one clause whose *off* position this composer implements, and its *on* it does not.

    ``force_a_common_period`` is false and this module has no code path that forces one.
    Reading it and refusing when it is true is the difference between a rule that governs
    the answer and a comment claiming it does: a reviewer who set it to true would
    otherwise see no change at all and conclude the clause was decorative.
    """
    value = rule_set.value(OverviewRule.OWN_LATEST.value, OverviewClause.FORCE_COMMON_PERIOD.value)
    if value is not False:
        raise OverviewError(
            f"{OverviewRule.OWN_LATEST.value} value "
            f"`{OverviewClause.FORCE_COMMON_PERIOD.value}` is {value!r}; this composer "
            "shows each member at its own latest period and implements no way to force a "
            "common one, so it refuses rather than ignoring the clause"
        )


def _require_one_figure_per_member(rule_set: RuleSet) -> None:
    value = rule_set.value(
        OverviewRule.SHORT_READ.value, OverviewClause.ONE_FIGURE_PER_MEMBER.value
    )
    if value is not True:
        raise OverviewError(
            f"{OverviewRule.SHORT_READ.value} value "
            f"`{OverviewClause.ONE_FIGURE_PER_MEMBER.value}` is {value!r}; this composer "
            "gives one figure per member and has no longer form to fall back to (F-021)"
        )
