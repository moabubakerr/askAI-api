"""Targets and baselines -- published columns, labelled as what they are.

Purity: pure.

FR-37 asks for a figure against its published target, *"without a forecast anyone
invented"*. Everything in this module follows from targets and baselines being published
columns rather than computed ones: there is no projection here, no interpolation, and no
path that reaches an actual.

**Labelled, never presented as an actual.** ``target.value`` and ``baseline.value`` are
separate messages from ``answer.value`` and each says which quantity it is showing. F-015
is what the absence of that looks like -- a target row at a different period presented as
the measured figure -- so the label is part of the sentence rather than a field a
renderer may drop.

**Read from the detail, not from the datapoint.** ``datapoint.baseline`` is NULL on all
8,127 rows, deliberately: the export publishes one baseline per detail, and Story 1.8 left
the column empty rather than filling one declared value down into thousands of rows that
would then look measured. ``DeclaredTarget`` is therefore the detail's own declaration,
and ``R-TARGET-BASELINE-IS-DECLARED-ON-THE-DETAIL`` is read here so that a build which
changed its mind fails rather than quietly reporting "no baseline published" for all 135
details that publish one.

**A future-dated target is answerable; a future-dated actual is not.** FR-8 excludes
future rows from being the latest *actual*, and 289 of the 322 future-dated rows are
targets running out to 2030 -- so reading FR-8 as governing everything would hide the
only thing a target is for. The two halves are one rule with two clauses
(``R-TARGET-FUTURE-DATED-IS-ANSWERABLE``), read together, because a build where they
disagree is one where somebody generalised the wrong one.

**Not published is the commoner answer.** Targets reach 98 of 289 published details and
baselines 135 of 289, so the refusal is composed here with the same care as the figure and
says which of the two is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from askai.assemble.elements import measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.period import Period
from askai.domain.spec import Measure
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.presentation import PublishedDetail
from askai.rules import RuleSet

__all__ = [
    "ComposedDeclared",
    "DeclaredTarget",
    "NotPublished",
    "TargetClause",
    "TargetComposition",
    "TargetError",
    "TargetMessage",
    "TargetRule",
    "TargetTables",
    "baseline_element",
    "declared_element",
    "target_element",
]


class TargetRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    IS_LABELLED = "R-TARGET-IS-LABELLED-NEVER-AN-ACTUAL"
    FUTURE_DATED_IS_ANSWERABLE = "R-TARGET-FUTURE-DATED-IS-ANSWERABLE"
    DECLARED_ON_THE_DETAIL = "R-TARGET-BASELINE-IS-DECLARED-ON-THE-DETAIL"


class TargetClause(StrEnum):
    """The clause names read off those rules."""

    MAY_BE_SHOWN_AS_AN_ACTUAL = "may_be_shown_as_an_actual"
    FUTURE_DATED_TARGET_IS_ELIGIBLE = "future_dated_target_is_eligible"
    FUTURE_DATED_ACTUAL_IS_ELIGIBLE = "future_dated_actual_is_eligible"
    READ_FROM_A_DATAPOINT = "read_from_a_datapoint"


class TargetMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    TARGET = "target.value"
    TARGET_NOT_PUBLISHED = "target.not_published"
    BASELINE = "baseline.value"
    BASELINE_NOT_PUBLISHED = "baseline.not_published"


class TargetError(ValueError):
    """A target or baseline composition was asked for something it does not answer."""


@dataclass(frozen=True, slots=True)
class DeclaredTarget:
    """A detail's published target and baseline, as the detail declares them.

    Each is a value and the period it is declared against, and neither can be half
    present: a target value with no year is a number with nothing to aim at, and a year
    with no value is an aim with no number. Both are ``None`` together or neither is,
    which is checked here rather than left to every reader of the pair.

    ``Decimal``, never ``float`` -- a published value that has been through binary
    floating point is no longer the published value (AD-4).
    """

    detail_id: str
    target: Decimal | None = None
    target_period: Period | None = None
    baseline: Decimal | None = None
    baseline_period: Period | None = None

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise TargetError("a declaration belongs to a detail; this one names none")
        if (self.target is None) is not (self.target_period is None):
            raise TargetError(
                f"{self.detail_id} declares a target value of {self.target} against period "
                f"{self.target_period}; a target is a number and the period it is aimed "
                "at, and half of one is not answerable as either"
            )
        if (self.baseline is None) is not (self.baseline_period is None):
            raise TargetError(
                f"{self.detail_id} declares a baseline value of {self.baseline} against "
                f"period {self.baseline_period}; a baseline is a number and the period it "
                "was measured in, and half of one cannot be labelled"
            )

    @property
    def publishes_a_target(self) -> bool:
        return self.target is not None

    @property
    def publishes_a_baseline(self) -> bool:
        return self.baseline is not None


@dataclass(frozen=True, slots=True)
class TargetTables:
    """The target rules, read through the rule set they live in."""

    rule_set: RuleSet

    def may_be_shown_as_an_actual(self) -> bool:
        """FR-37's prohibition, read rather than assumed. Expected to be ``False``."""
        return self._switch(TargetRule.IS_LABELLED, TargetClause.MAY_BE_SHOWN_AS_AN_ACTUAL)

    def future_dated_target_is_eligible(self) -> bool:
        """Whether a target dated after today is still answerable as a target (FR-8)."""
        return self._switch(
            TargetRule.FUTURE_DATED_IS_ANSWERABLE, TargetClause.FUTURE_DATED_TARGET_IS_ELIGIBLE
        )

    def future_dated_actual_is_eligible(self) -> bool:
        """The other half of the same rule. Expected to be ``False`` (FR-8)."""
        return self._switch(
            TargetRule.FUTURE_DATED_IS_ANSWERABLE, TargetClause.FUTURE_DATED_ACTUAL_IS_ELIGIBLE
        )

    def baseline_is_read_from_a_datapoint(self) -> bool:
        """Expected to be ``False``: the export declares a baseline per detail."""
        return self._switch(
            TargetRule.DECLARED_ON_THE_DETAIL, TargetClause.READ_FROM_A_DATAPOINT
        )

    def _switch(self, rule: TargetRule, clause: TargetClause) -> bool:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, bool):
            raise TargetError(
                f"{rule.value} value `{clause.value}` must be a yes or a no, not "
                f"{type(value).__name__}; the target composition reads its rules from the "
                "rule files and has none of its own to fall back to"
            )
        return value


@dataclass(frozen=True, slots=True)
class ComposedDeclared:
    """The figure, labelled as the measure it is, with the period it is declared against."""

    placed: Placed
    measure: Measure
    period: Period

    def __post_init__(self) -> None:
        if self.measure not in (Measure.TARGET, Measure.BASELINE):
            raise TargetError(
                f"{self.measure.value} is not a declared measure; a target and a baseline "
                "are declared on the detail, and an actual is fetched from a row"
            )


@dataclass(frozen=True, slots=True)
class NotPublished:
    """This detail declares no such measure, said as a fact about the published data."""

    measure: Measure
    statement: str


#: What composing a target or a baseline reaches. Closed, so a caller that handles the
#: figure and forgets the commoner case does not type-check.
type TargetComposition = ComposedDeclared | NotPublished


def declared_element(
    measure: Measure,
    declared: DeclaredTarget,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: TargetTables,
    lang: Lang,
    country_id: str | None,
) -> TargetComposition:
    """Compose the answer for a spec whose ``measure`` bound to ``target`` or ``baseline``.

    AD-1's arm of this story: the whole answer is composed from that single binding, so
    the dispatch happens once, here, and neither branch can reach the other's column.
    ``Measure.ACTUAL`` and ``Measure.CHANGE`` are refused outright rather than falling
    through -- an actual is fetched from a row and a change is selected from a column, and
    each has its own composition.
    """
    match measure:
        case Measure.TARGET:
            return target_element(
                declared, published, catalogue, formatter, placement, tables, lang, country_id
            )
        case Measure.BASELINE:
            return baseline_element(
                declared, published, catalogue, formatter, placement, tables, lang, country_id
            )
        case Measure.ACTUAL | Measure.CHANGE:
            raise TargetError(
                f"{measure.value} is not declared on a detail; an actual is fetched by "
                "exact key and a change is selected from a published column, and neither "
                "is answered from the target declaration"
            )


def target_element(
    declared: DeclaredTarget,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: TargetTables,
    lang: Lang,
    country_id: str | None,
) -> TargetComposition:
    """The published target, labelled as a target -- future-dated or not."""
    _check_the_rules_still_say_what_this_composer_does(tables)
    if declared.target is None or declared.target_period is None:
        return NotPublished(
            measure=Measure.TARGET,
            statement=render(
                catalogue,
                lang,
                TargetMessage.TARGET_NOT_PUBLISHED.value,
                detail=published.name,
            ),
        )
    if not tables.future_dated_target_is_eligible():
        raise TargetError(
            f"{TargetRule.FUTURE_DATED_IS_ANSWERABLE.value} no longer makes a future-dated "
            "target answerable; this composer cannot tell which targets it may now show, "
            "because a target dated after today is what a target usually is"
        )
    return _composed(
        Measure.TARGET,
        TargetMessage.TARGET,
        declared.detail_id,
        declared.target,
        declared.target_period,
        published,
        catalogue,
        formatter,
        placement,
        lang,
        country_id,
    )


def baseline_element(
    declared: DeclaredTarget,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: TargetTables,
    lang: Lang,
    country_id: str | None,
) -> TargetComposition:
    """The published baseline, labelled as a baseline, with the year it is measured in."""
    _check_the_rules_still_say_what_this_composer_does(tables)
    if tables.baseline_is_read_from_a_datapoint():
        raise TargetError(
            f"{TargetRule.DECLARED_ON_THE_DETAIL.value} now says a baseline is read from a "
            "datapoint; this composer reads the detail's declaration, and the datapoint "
            "column is NULL on every published row"
        )
    if declared.baseline is None or declared.baseline_period is None:
        return NotPublished(
            measure=Measure.BASELINE,
            statement=render(
                catalogue,
                lang,
                TargetMessage.BASELINE_NOT_PUBLISHED.value,
                detail=published.name,
            ),
        )
    return _composed(
        Measure.BASELINE,
        TargetMessage.BASELINE,
        declared.detail_id,
        declared.baseline,
        declared.baseline_period,
        published,
        catalogue,
        formatter,
        placement,
        lang,
        country_id,
    )


def _composed(
    measure: Measure,
    message: TargetMessage,
    declared_id: str,
    value: Decimal,
    period: Period,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
    country_id: str | None,
) -> ComposedDeclared:
    """One declared figure, written through the single formatter and labelled by message.

    The role is ``headline``: a question about a target is answered by the target, and it
    is the figure the reader reads first. The label is not the role -- it is the message
    id, which is why a target can be a headline without ever being an actual.
    """
    role = Role.HEADLINE
    written = formatter.format(
        value,
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        lang,
    )
    content = render(
        catalogue,
        lang,
        message.value,
        detail=published.name,
        value=written.value,
        unit=written.unit,
        period=render_period(catalogue, lang, period),
    )
    provenance = Provenance(
        detail_id=_declared_detail(published, declared_id),
        period=period,
        country=country_id,
        source_id=published.source_id,
    )
    return ComposedDeclared(
        placed=Placed(element=measured(content, provenance), role=role),
        measure=measure,
        period=period,
    )


def _declared_detail(published: PublishedDetail, declared_id: str) -> str:
    """The detail a declaration belongs to, checked against the detail being presented.

    A one-line guard with a name, because the failure it prevents is silent: composing a
    target from one detail's declaration while naming and formatting another detail's
    published record would produce a sentence that is wrong in every part except the
    number.
    """
    if published.detail_id != declared_id:
        raise TargetError(
            f"the declaration belongs to {declared_id} and the detail being presented is "
            f"{published.detail_id}; a target is answered from its own detail's columns"
        )
    return published.detail_id


def _check_the_rules_still_say_what_this_composer_does(tables: TargetTables) -> None:
    """Refuse to compose where the published rules contradict what is about to happen."""
    if tables.may_be_shown_as_an_actual():
        raise TargetError(
            f"{TargetRule.IS_LABELLED.value} now permits a target to be shown as an "
            "actual; every sentence this composer renders says which of the two it is, so "
            "the file and the composer disagree about what a target is (F-015)"
        )
    if tables.future_dated_actual_is_eligible():
        raise TargetError(
            f"{TargetRule.FUTURE_DATED_IS_ANSWERABLE.value} now makes a future-dated "
            "actual eligible, which is FR-8's exclusion removed rather than scoped; 322 "
            "rows are dated after today and 42 of them carry a placeholder actual"
        )
