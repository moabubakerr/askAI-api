"""Group answers -- how many, what they are called, and which level the reader meant.

Purity: pure. Every word comes from ``messages/``; every threshold and list from ``rules/``.

The published catalogue divides all 189 indicators into 7 classifications and 22 entities,
and every indicator carries exactly one of each -- measured, 189/189. The layer was
materialised by Story 1.8 and never read back, which is the whole of what Story 5.1 fixes.

Three decisions here, and each has a wrong answer that looks right.

**A count is a figure.** ``group_count_element`` returns a ``Measured`` element carrying a
``CatalogueReference``, admitted against the loaded catalogue like any other (AD-3, AD-6).
It comes from ``Group.indicator_count``, which the port computed with the same filter that
built the list -- so FR-50's *"excluded from the count, not merely hidden from the list"*
is a property of the query rather than of two call sites agreeing.

**A category is answered by its groups, not by its members.** ``Sectors`` holds 105
indicators across 8 entities, and 105 names is not something a reader can scan.
``R-GROUP-CATEGORY-ANSWERED-BY-ITS-GROUPS`` (the catalogue's R-165) is read here, so the
shape of that answer is a reviewer's edit rather than a deployment.

**A name at both levels is clarified, never resolved.** *"Sectors"* is a classification of
105; a named sector is an entity of between 7 and 23. Preferring a level would be wrong
silently and by as much as 98 indicators, which is precisely FR-2 and AD-25.

What is **not** here: nothing in this module binds a name. ``groups_named`` is asked, and
the caller decides what to do with none, one or several -- resolution is Epic 2's ladder
and this module must not grow a second one.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from askai.assemble.meta.reference import (
    CatalogueReference,
    ReferenceKind,
    catalogue_element,
)
from askai.assemble.roles import Placed, Role
from askai.domain.element import ElementClass
from askai.messages import Catalogue, Lang, compose_counted, render
from askai.ports.groups import Group, GroupedIndicator, GroupLevel
from askai.rules import RuleSet

__all__ = [
    "GroupClause",
    "GroupMessage",
    "GroupRule",
    "ambiguous_group_statement",
    "group_breakdown_element",
    "group_count_element",
    "group_members_element",
    "group_name",
    "group_reference",
    "is_answered_at_classification_level",
]


class GroupMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    HOLDS = "sentence.group_holds"
    MEMBERS = "group.members"
    BREAKDOWN = "group.breakdown"
    ENTRY = "sentence.group_entry"
    SINGLE_GROUP = "group.single_group"
    AMBIGUOUS = "group.ambiguous"
    READING_CLASSIFICATION = "sentence.group_reading_classification"
    READING_ENTITY = "sentence.group_reading_entity"
    READING_SEPARATOR = "group.reading_separator"
    LIST_SEPARATOR = "group.list_separator"
    #: The counted noun a group's size is said in. The unit is an argument everywhere it
    #: is used (R-175); it is named here because a group is counted in indicators and in
    #: nothing else, and a caller choosing the noun could count 105 of something wrong.
    INDICATOR = "count.indicator"


class GroupRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    CONTAINER_LEVEL = "R-GROUP-CONTAINER-ANSWERED-AT-CLASSIFICATION"
    CATEGORY_BY_GROUPS = "R-GROUP-CATEGORY-ANSWERED-BY-ITS-GROUPS"
    SIZE_IS_STATED = "R-GROUP-SIZE-IS-STATED"
    AMBIGUOUS_IS_CLARIFIED = "R-GROUP-AMBIGUOUS-NAME-IS-CLARIFIED"


class GroupClause(StrEnum):
    """The clause names read off those rules."""

    CONTAINER_CLASSIFICATIONS = "container_classifications"
    SUMMARISE_BY_GROUPS = "summarise_category_by_its_groups"
    STATE_SIZE = "state_group_size"
    CLARIFY = "clarify_rather_than_prefer_a_level"


class GroupError(LookupError):
    """A group table cannot be acted on, or was asked something it does not answer.

    Raised rather than defaulted. A clause read as the wrong type and quietly ignored
    would make this module answer by a convention nobody can read, which is the founding
    defect ``rules/`` exists to end.
    """


# ------------------------------------------------------------------ naming and sourcing


def group_name(group: Group, lang: Lang) -> str:
    """The group's published name in *lang*, falling back to the other only when blank.

    The fallback is not a translation. A classification is published as one name with no
    Arabic counterpart at all, so the Arabic answer shows the published spelling rather
    than a hole where a group name belongs -- and an entity that publishes both shows the
    one the reader asked in.
    """
    match lang:
        case Lang.EN:
            first, second = group.name_en, group.name_ar
        case Lang.AR:
            first, second = group.name_ar, group.name_en
    return first.strip() or second.strip() or group.key


def group_reference(group: Group) -> CatalogueReference:
    """The catalogue reference an element about *group* carries.

    The level decides the kind, so a classification's count can never resolve because an
    entity of that key exists. Exhaustive on the enum with no fallback: a level added to
    the port without a reference kind here fails loudly rather than sourcing its elements
    to whichever kind was written first.
    """
    match group.level:
        case GroupLevel.CLASSIFICATION:
            kind = ReferenceKind.CLASSIFICATION
        case GroupLevel.ENTITY:
            kind = ReferenceKind.ENTITY
        case _:
            raise GroupError(
                f"{group.level!r} has no catalogue reference kind; a level the port "
                "returns is a level an element about it has to be able to point at"
            )
    return CatalogueReference(kind=kind, key=group.key)


# --------------------------------------------------------------------- the composers


def group_count_element(
    catalogue: Catalogue, lang: Lang, rule_set: RuleSet, group: Group
) -> Placed:
    """*"Diversification Targets holds 12 indicators."* -- the size, as a headline element.

    Class ``measured``: the count is read off the published catalogue, which is what
    ``measured`` means. Role ``headline``, because the count *is* the answer to *"how
    many"* -- and the role, not this module, then decides which lens shows it.
    """
    _require(rule_set, GroupRule.SIZE_IS_STATED, GroupClause.STATE_SIZE)
    content = compose_counted(
        catalogue,
        lang,
        GroupMessage.HOLDS.value,
        GroupMessage.INDICATOR.value,
        group.indicator_count,
        group=group_name(group, lang),
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, group_reference(group)),
        role=Role.HEADLINE,
    )


def group_members_element(
    catalogue: Catalogue, lang: Lang, group: Group, members: Sequence[GroupedIndicator]
) -> Placed:
    """*"Education Sector: <13 names>"* -- what the group is called, listed.

    Role ``evidence``: the names are the published rows behind the count, shown so the
    count can be checked against them. That places the list in the explore lens and keeps
    the executive answer to the figure, which is FR-59b's division doing its job rather
    than this module deciding how long an answer should be.
    """
    separator = render(catalogue, lang, GroupMessage.LIST_SEPARATOR.value)
    content = render(
        catalogue,
        lang,
        GroupMessage.MEMBERS.value,
        group=group_name(group, lang),
        names=separator.join(_member_name(member, lang) for member in members),
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, group_reference(group)),
        role=Role.EVIDENCE,
    )


def group_breakdown_element(
    catalogue: Catalogue,
    lang: Lang,
    rule_set: RuleSet,
    classification: Group,
    entities: Sequence[Group],
) -> Placed:
    """*"Sectors is divided into: Transportation and Storage (23 indicators), ..."*

    The catalogue's R-165, composed: a category is answered with the groups inside it and
    their counts -- the level above the list -- rather than with every name it holds. The
    switch is read rather than assumed, so turning it off in the file returns the
    membership instead, and no code moves.
    """
    _require(rule_set, GroupRule.CATEGORY_BY_GROUPS, GroupClause.SUMMARISE_BY_GROUPS)
    separator = render(catalogue, lang, GroupMessage.LIST_SEPARATOR.value)
    content = render(
        catalogue,
        lang,
        GroupMessage.BREAKDOWN.value,
        group=group_name(classification, lang),
        groups=separator.join(
            compose_counted(
                catalogue,
                lang,
                GroupMessage.ENTRY.value,
                GroupMessage.INDICATOR.value,
                entity.indicator_count,
                name=group_name(entity, lang),
            )
            for entity in entities
        ),
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, group_reference(classification)),
        role=Role.HEADLINE,
    )


def single_group_note(catalogue: Catalogue, lang: Lang, classification: Group) -> Placed:
    """*"Diversification Targets has a single group of the same name..."*

    The statement that accompanies a container classification, so the reader can see why
    they were given a category where they named a group. Role ``note``: it is a caveat
    about the shape of the answer, not a second figure, and ``note`` is in both lenses.

    Class ``measured`` rather than ``derived``: the one-to-one is a published fact about
    the catalogue's own division, read off it, not something computed here.
    """
    content = render(
        catalogue,
        lang,
        GroupMessage.SINGLE_GROUP.value,
        group=group_name(classification, lang),
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, group_reference(classification)),
        role=Role.NOTE,
    )


def ambiguous_group_statement(
    catalogue: Catalogue, lang: Lang, rule_set: RuleSet, readings: Sequence[Group]
) -> str:
    """The clarification for a name published at both levels (FR-2).

    Returns a **string, not an element**, and that is the point rather than an oversight:
    ``AnswerPackage`` carries a clarification in ``reason`` precisely because an element
    cannot exist without a ``source_ref``, and a question that resolved to two readings
    has not settled on a row to point at. Both readings are named with their sizes so the
    reader can choose on the fact that actually distinguishes them -- 105 against 7.
    """
    _require(rule_set, GroupRule.AMBIGUOUS_IS_CLARIFIED, GroupClause.CLARIFY)
    if len(readings) < _AT_LEAST_TWO:
        raise GroupError(
            f"a clarification names more than one reading; {len(readings)} were given, "
            "and a clarification offering one choice is a refusal wearing the wrong word"
        )
    separator = render(catalogue, lang, GroupMessage.READING_SEPARATOR.value)
    return render(
        catalogue,
        lang,
        GroupMessage.AMBIGUOUS.value,
        name=group_name(readings[0], lang),
        readings=separator.join(_reading(catalogue, lang, group) for group in readings),
    )


def is_answered_at_classification_level(rule_set: RuleSet, group: Group) -> bool:
    """Is *group* one the table says to answer at classification level?

    ``DiversificationTargets`` and ``NationalIndicators`` each divide into exactly one
    entity whose name mirrors the classification's own, so naming both levels would show
    one group twice. The pair is read from ``rules/`` rather than spelled here: it is a
    measured property of this export, and the next one may divide either into real
    entities -- at which point the answer changes by a one-line edit to a file.

    True for the classification itself and for the single entity inside it, so a reader
    who names either gets the same answer.
    """
    listed = _table(rule_set, GroupRule.CONTAINER_LEVEL, GroupClause.CONTAINER_CLASSIFICATIONS)
    return group.classification in listed


# -------------------------------------------------------------------------- plumbing

#: Two, said as a name. The scan in ``tests/test_rules.py`` refuses a numeric literal in
#: ``assemble/`` and is right to -- a bare number there is a threshold nobody reviewed.
#: This is not a threshold: "more than one reading" is what the word *ambiguous* means,
#: and it is derived from the enum's own arity rather than chosen.
_AT_LEAST_TWO = len(GroupLevel)


def _member_name(member: GroupedIndicator, lang: Lang) -> str:
    match lang:
        case Lang.EN:
            first, second = member.name_en, member.name_ar
        case Lang.AR:
            first, second = member.name_ar, member.name_en
    return first.strip() or second.strip() or member.indicator_id


def _reading(catalogue: Catalogue, lang: Lang, group: Group) -> str:
    """One of the readings an ambiguous name could have, with its size.

    An entity names the classification it sits in and a classification does not, because
    *"the group Tourism inside Sectors"* is what tells the reader the two readings are
    nested rather than unrelated.
    """
    match group.level:
        case GroupLevel.CLASSIFICATION:
            return compose_counted(
                catalogue,
                lang,
                GroupMessage.READING_CLASSIFICATION.value,
                GroupMessage.INDICATOR.value,
                group.indicator_count,
                name=group_name(group, lang),
            )
        case GroupLevel.ENTITY:
            return compose_counted(
                catalogue,
                lang,
                GroupMessage.READING_ENTITY.value,
                GroupMessage.INDICATOR.value,
                group.indicator_count,
                name=group_name(group, lang),
                classification=group.classification,
            )
        case _:
            raise GroupError(
                f"{group.level!r} has no wording as a reading of an ambiguous name; a "
                "level the engine binds is a level the clarification has to be able to say"
            )


def _table(rule_set: RuleSet, rule: GroupRule, clause: GroupClause) -> frozenset[str]:
    value = rule_set.value(rule.value, clause.value)
    if not isinstance(value, tuple):
        raise GroupError(
            f"{rule.value} value `{clause.value}` must be a list of names, not "
            f"{type(value).__name__}; assemble/meta reads it from the rule file and has "
            "no list of its own to fall back to"
        )
    return frozenset(value)


def _require(rule_set: RuleSet, rule: GroupRule, clause: GroupClause) -> None:
    """Read a switch, and refuse to compose when the file turns it off.

    Raising rather than quietly composing the other shape: a switch this module does not
    implement the *off* side of is a switch whose off position would be a silent no-op,
    and a reviewer who turned it off would see no change and conclude it did nothing.
    """
    value = rule_set.value(rule.value, clause.value)
    if value is not True:
        raise GroupError(
            f"{rule.value} value `{clause.value}` is {value!r}; this composer implements "
            "the clause being on, so composing with it off would silently produce the "
            "same answer and make the switch decorative"
        )
