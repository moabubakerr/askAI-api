"""Selecting the published change column, and the one case where computing is allowed.

Purity: pure. Reads its three tables from ``rules/`` and holds no constant of its own.

AD-4 and DATA-CONTRACT FACT 2 say the same thing twice: *change values are selected from
the published column matching ``(grain x basis)``, never recomputed*. The export carries
ten such columns -- MoM on monthly rows, QoQ on quarterly rows and YoY on all three
grains, each in a percent and a percentage-point flavour -- and the read model carries
six cells per row because YoY collapses to one pair once the row's own grain is known.

Three things make the rule structural rather than remembered.

**Selection and computation are different types.** ``SelectedChange`` names the column it
came from and cannot be constructed without one; ``ComputedChange`` names the two
readings it was computed from and cannot be constructed without both. Each carries its
own ``ElementClass`` as a property, so an element classed ``measured`` carrying a
computed change is not something a composer has to remember not to write -- there is no
value it could write it from.

**The basis is not the grain.** A quarterly row publishes both QoQ and YoY, so *"how much
did it change in 2025-Q2"* has two correct answers and the question decides between them.
``R-CHANGE-BASIS-BY-GRAIN`` says which bases each grain may carry and which one a
question that names none falls back to; nothing here infers a basis from a period.

**The flavour is declared, never inferred.** ``R-CHANGE-FLAVOUR-FROM-PUBLISHED-UNIT``
maps the detail's published unit to the quantity its change is in, and the value is never
looked at: 2.0 is 2% or 2 pp depending entirely on which column it was read from, and
deciding from the magnitude is the F-005/F-029 defect with an extra step. The two
percentage types are built in ``domain/change.py`` and in no other place --
``tests/test_assemble.py`` scans this package for a constructor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.domain.calendar import a_year_earlier, preceding
from askai.domain.change import (
    Basis,
    ChangeFlavour,
    ChangeValue,
    computed_change,
    flavour_of,
    read_change,
)
from askai.domain.element import ElementClass
from askai.domain.normalise import normalise
from askai.domain.period import Grain, Period
from askai.execute.value import Figure
from askai.rules import RuleSet

__all__ = [
    "Change",
    "ChangeClause",
    "ChangeRule",
    "ChangeTableError",
    "ChangeTables",
    "ComputedChange",
    "PublishedChange",
    "SelectedChange",
    "column_identity",
    "compute_change",
    "paired_with",
    "select_change",
]


class ChangeRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    PUBLISHED_COLUMN_IS_SELECTED = "R-CHANGE-PUBLISHED-COLUMN-IS-SELECTED"
    BASIS_BY_GRAIN = "R-CHANGE-BASIS-BY-GRAIN"
    FLAVOUR_FROM_PUBLISHED_UNIT = "R-CHANGE-FLAVOUR-FROM-PUBLISHED-UNIT"
    CARRIES_BASIS_AND_PERIODS = "R-CHANGE-CARRIES-BASIS-AND-PERIODS"


class ChangeClause(StrEnum):
    """The clause names read off those rules."""

    RECOMPUTE_A_PUBLISHED_COLUMN = "recompute_a_published_column"
    COMPUTE_WHEN_NO_COLUMN_MATCHES = "compute_when_no_column_matches"

    MONTHLY_BASES = "monthly_bases"
    QUARTERLY_BASES = "quarterly_bases"
    YEARLY_BASES = "yearly_bases"
    MONTHLY_DEFAULT = "monthly_default"
    QUARTERLY_DEFAULT = "quarterly_default"
    YEARLY_DEFAULT = "yearly_default"

    PERCENT_UNITS = "percent_units"
    PERCENT_UNIT = "percent_unit"
    POINTS_UNIT = "points_unit"

    BASIS_IS_REQUIRED = "basis_is_required"
    BOTH_PERIODS_ARE_REQUIRED = "both_periods_are_required"
    LATER_READING_IS_REQUIRED = "later_reading_is_required"


class ChangeTableError(LookupError):
    """The change tables cannot be acted on, or were asked something they do not answer.

    Raised rather than defaulted, in every case. A grain with no basis list would fall
    through to "no published column matches" and compute a change the export already
    publishes, which is the one outcome AD-4 exists to prevent.
    """


# ------------------------------------------------------------------ the published cells


@dataclass(frozen=True, slots=True)
class PublishedChange:
    """The six change cells a published row carries, exactly as published.

    Text, never parsed numbers, for the same reason ``DatapointRow`` holds its value
    columns as text: a published decimal read back through a float is the rounding defect
    arriving through the storage layer. ``None`` is a cell the row does not publish, which
    is the common case -- a monthly row publishes no QoQ at all.
    """

    mom_percent: str | None = None
    mom_pp: str | None = None
    qoq_percent: str | None = None
    qoq_pp: str | None = None
    yoy_percent: str | None = None
    yoy_pp: str | None = None

    def cell(self, basis: Basis, flavour: ChangeFlavour) -> str | None:
        """The published text of one column, or ``None`` when the row publishes none.

        Exhaustive over both axes on purpose: a basis or a flavour added later raises
        here rather than silently selecting the year-on-year percent, which would serve
        one quantity under another quantity's name.
        """
        match (basis, flavour):
            case (Basis.MOM, ChangeFlavour.PERCENT):
                return self.mom_percent
            case (Basis.MOM, ChangeFlavour.PERCENTAGE_POINTS):
                return self.mom_pp
            case (Basis.QOQ, ChangeFlavour.PERCENT):
                return self.qoq_percent
            case (Basis.QOQ, ChangeFlavour.PERCENTAGE_POINTS):
                return self.qoq_pp
            case (Basis.YOY, ChangeFlavour.PERCENT):
                return self.yoy_percent
            case (Basis.YOY, ChangeFlavour.PERCENTAGE_POINTS):
                return self.yoy_pp
            case _:
                raise ChangeTableError(
                    f"no published column holds {basis} in {flavour}; the export carries "
                    "each basis in a percent and a percentage-point flavour and no third"
                )


def column_identity(basis: Basis, flavour: ChangeFlavour) -> str:
    """The read model's own name for one change column -- ``change_yoy_pp`` and friends.

    Composed from the two axes rather than listed, so the identity a corpus entry asserts
    on is derived from the same pair the selection was made by and cannot drift from it.
    Story 3.4's failing case is an entry that asserts on the rendered number alone; this
    is what it asserts on instead.
    """
    return f"change_{basis.value}_{flavour.value}"


# --------------------------------------------------------------------- the two results


@dataclass(frozen=True, slots=True)
class SelectedChange:
    """A change read out of the published column that matches the grain and the basis.

    Carries the column it was selected from, and refuses to exist without one. That is
    the whole enforcement of *"an element classed measured can never carry a computed
    change"*: ``element_class`` is a property rather than a field, so there is no
    constructor argument to pass ``derived`` to and no computed value to pass in.
    """

    basis: Basis
    value: ChangeValue
    column: str
    #: The row the column sits on -- the later of the two periods, and the reading the
    #: change moved *to* (R-168).
    later: Figure
    earlier: Period

    def __post_init__(self) -> None:
        if not self.column.strip():
            raise ChangeTableError(
                "a selected change names the published column it came from; one that "
                "cannot is a computed change wearing a selected change's label (AD-4)"
            )
        if self.later.period.grain is not self.earlier.grain:
            raise ChangeTableError(
                f"a change runs between two periods at one grain, and {self.later.period} "
                f"to {self.earlier} names two; the basis says which pairing was published"
            )

    @property
    def flavour(self) -> ChangeFlavour:
        """Read off the value's type, which the selected column declared."""
        return flavour_of(self.value)

    @property
    def element_class(self) -> ElementClass:
        """``measured``: it is a published cell, read from the row it sits on."""
        return ElementClass.MEASURED


@dataclass(frozen=True, slots=True)
class ComputedChange:
    """A change computed here, because no published column matched the pairing asked for.

    Holds both ``Figure``s rather than two numbers, so *"states its inputs"* (FR-19) is a
    property of the value: the composer cannot state a computed change without having the
    two published readings it was computed from, each naming its own row.
    """

    basis: Basis
    value: ChangeValue
    later: Figure
    earlier: Figure

    def __post_init__(self) -> None:
        if self.later.period.grain is not self.earlier.period.grain:
            raise ChangeTableError(
                f"a change runs between two periods at one grain, and "
                f"{self.later.period} to {self.earlier.period} names two"
            )
        if self.later.period.start <= self.earlier.period.start:
            raise ChangeTableError(
                f"a change runs from the earlier reading to the later one, and "
                f"{self.earlier.period} does not precede {self.later.period}"
            )

    @property
    def flavour(self) -> ChangeFlavour:
        return flavour_of(self.value)

    @property
    def element_class(self) -> ElementClass:
        """``derived``: computed here, from published inputs, with the inputs stated."""
        return ElementClass.DERIVED


#: What a change question reaches. A closed union, so a composer that handles the
#: selected case and forgets the computed one does not type-check.
type Change = SelectedChange | ComputedChange


# ----------------------------------------------------------------------- the tables


@dataclass(frozen=True, slots=True)
class ChangeTables:
    """The change rules, read through the rule set they live in.

    A value constructed with the rule set rather than a module of functions reading a
    cached global -- the same reason ``Formatter`` and ``Placement`` are values.
    """

    rule_set: RuleSet

    # ------------------------------------------------------------------ basis by grain

    def bases_for(self, grain: Grain) -> frozenset[Basis]:
        """Every basis *grain* may be asked for, as the published table declares them."""
        match grain:
            case Grain.MONTHLY:
                clause = ChangeClause.MONTHLY_BASES
            case Grain.QUARTERLY:
                clause = ChangeClause.QUARTERLY_BASES
            case Grain.YEARLY:
                clause = ChangeClause.YEARLY_BASES
            case _:
                raise ChangeTableError(
                    f"{grain!r} has no basis list in {ChangeRule.BASIS_BY_GRAIN.value}; a "
                    "grain the engine answers at is a grain the table has to place"
                )
        return frozenset(
            _basis(name, ChangeRule.BASIS_BY_GRAIN, clause)
            for name in self._spellings(ChangeRule.BASIS_BY_GRAIN, clause)
        )

    def default_basis(self, grain: Grain) -> Basis:
        """The basis a question that names none falls back to, for *grain*.

        Read rather than inferred. A default chosen in code would be a reader-affecting
        decision living in a diff, and it is the decision that turns *"how much did it
        change in April"* into a month-on-month answer rather than a year-on-year one.
        """
        match grain:
            case Grain.MONTHLY:
                clause = ChangeClause.MONTHLY_DEFAULT
            case Grain.QUARTERLY:
                clause = ChangeClause.QUARTERLY_DEFAULT
            case Grain.YEARLY:
                clause = ChangeClause.YEARLY_DEFAULT
            case _:
                raise ChangeTableError(
                    f"{grain!r} has no default basis in {ChangeRule.BASIS_BY_GRAIN.value}"
                )
        chosen = _basis(
            self._phrase(ChangeRule.BASIS_BY_GRAIN, clause), ChangeRule.BASIS_BY_GRAIN, clause
        )
        if chosen not in self.bases_for(grain):
            raise ChangeTableError(
                f"{ChangeRule.BASIS_BY_GRAIN.value} makes `{chosen.value}` the default for "
                f"{grain.value} and does not list it among the bases that grain publishes; "
                "a default nothing publishes is a change question that can never be answered"
            )
        return chosen

    def publishes(self, basis: Basis, period: Period) -> bool:
        """Whether a row at *period* may carry *basis* at all, by the published table."""
        return basis in self.bases_for(period.grain)

    # --------------------------------------------------------------------- the flavour

    def flavour_for(self, unit: str) -> ChangeFlavour:
        """The quantity a change on an indicator published in *unit* is in (FR-21).

        The unit decides and the value is never consulted. Matched through the engine's
        single text fold, so a published ``"% "`` with a trailing space does not quietly
        become a percentage-change indicator.
        """
        spellings = self._spellings(
            ChangeRule.FLAVOUR_FROM_PUBLISHED_UNIT, ChangeClause.PERCENT_UNITS
        )
        folded = normalise(unit)
        if any(folded == normalise(spelling) for spelling in spellings):
            return ChangeFlavour.PERCENTAGE_POINTS
        return ChangeFlavour.PERCENT

    def unit_for(self, flavour: ChangeFlavour) -> str:
        """The unit a change of *flavour* is shown with -- ``%`` or ``pp``.

        A different question from what the indicator is measured in: an inflation rate is
        published in ``%`` and its movement is shown in ``pp``, which is the whole of
        FR-21 in one sentence.
        """
        match flavour:
            case ChangeFlavour.PERCENT:
                clause = ChangeClause.PERCENT_UNIT
            case ChangeFlavour.PERCENTAGE_POINTS:
                clause = ChangeClause.POINTS_UNIT
            case _:
                raise ChangeTableError(f"{flavour!r} has no unit spelling in the change rules")
        return self._phrase(ChangeRule.FLAVOUR_FROM_PUBLISHED_UNIT, clause)

    # ----------------------------------------------------------------- what is allowed

    def may_recompute_a_published_column(self) -> bool:
        """AD-4's prohibition, read rather than assumed. Expected to be ``False``."""
        return self._switch(
            ChangeRule.PUBLISHED_COLUMN_IS_SELECTED, ChangeClause.RECOMPUTE_A_PUBLISHED_COLUMN
        )

    def may_compute_when_nothing_matches(self) -> bool:
        """Whether a change with no published column may be computed at all (FR-19)."""
        return self._switch(
            ChangeRule.PUBLISHED_COLUMN_IS_SELECTED, ChangeClause.COMPUTE_WHEN_NO_COLUMN_MATCHES
        )

    def must_name_the_basis(self) -> bool:
        return self._switch(
            ChangeRule.CARRIES_BASIS_AND_PERIODS, ChangeClause.BASIS_IS_REQUIRED
        )

    def must_name_both_periods(self) -> bool:
        return self._switch(
            ChangeRule.CARRIES_BASIS_AND_PERIODS, ChangeClause.BOTH_PERIODS_ARE_REQUIRED
        )

    def must_carry_the_later_reading(self) -> bool:
        """R-168: a percentage alone makes the reader ask *"from what?"*."""
        return self._switch(
            ChangeRule.CARRIES_BASIS_AND_PERIODS, ChangeClause.LATER_READING_IS_REQUIRED
        )

    # --------------------------------------------------------------- reading the file

    def _spellings(self, rule: ChangeRule, clause: ChangeClause) -> tuple[str, ...]:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, tuple):
            raise ChangeTableError(_wrong_shape(rule, clause, "a list of published names", value))
        return value

    def _phrase(self, rule: ChangeRule, clause: ChangeClause) -> str:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, str):
            raise ChangeTableError(_wrong_shape(rule, clause, "a word", value))
        return value

    def _switch(self, rule: ChangeRule, clause: ChangeClause) -> bool:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, bool):
            raise ChangeTableError(_wrong_shape(rule, clause, "a yes or a no", value))
        return value


def _basis(name: str, rule: ChangeRule, clause: ChangeClause) -> Basis:
    try:
        return Basis(name)
    except ValueError:
        known = ", ".join(basis.value for basis in Basis)
        raise ChangeTableError(
            f"{rule.value} value `{clause.value}` names `{name}`, which is not a basis; "
            f"the published bases are {known}"
        ) from None


def _wrong_shape(rule: ChangeRule, clause: ChangeClause, wanted: str, found: object) -> str:
    return (
        f"{rule.value} value `{clause.value}` must be {wanted}, not "
        f"{type(found).__name__}; the change composition reads its tables from the rule "
        "files and has none of its own to fall back to"
    )


# ------------------------------------------------------------------------ the selection


def paired_with(basis: Basis, later: Period) -> Period:
    """The period a published *basis* column on *later*'s row measures against.

    This is what makes *"the published column spanning exactly those two periods"* a
    checkable claim rather than an assumption. A year-on-year column on the 2025 row
    spans 2025 and 2024 and no other pairing, so a reader asking about 2022 against 2025
    is not answered from it -- that question has no published column and is computed,
    with the computation stated (Story 3.7, FR-19).
    """
    match basis:
        case Basis.YOY:
            return a_year_earlier(later)
        case Basis.MOM | Basis.QOQ:
            # Both step one period back at the row's own grain, which is what they mean:
            # the basis list in `R-CHANGE-BASIS-BY-GRAIN` is what keeps a month-on-month
            # column from ever being asked for on a quarterly row.
            return preceding(later)
        case _:
            raise ChangeTableError(
                f"{basis!r} names no pairing; a basis the engine selects a column for is "
                "one it can say which two periods that column spans"
            )


def select_change(
    tables: ChangeTables,
    published: PublishedChange,
    later: Figure,
    earlier: Period,
    unit: str,
    basis: Basis,
) -> SelectedChange | None:
    """The published change for *basis* on *later*'s row, or ``None`` if none is published.

    ``None`` is *"this row publishes no such column"*, which is a fact about the data and
    the precondition for computing one. It is never *"the change is nothing"*: a cell
    holding a published zero comes back as a selected change of zero.

    The flavour is chosen from *unit* before the cell is read, so the column that is
    looked at is already the right quantity -- the value never gets a chance to decide.
    """
    if not tables.publishes(basis, later.period):
        return None
    if earlier != paired_with(basis, later.period):
        # The column exists on this row but does not span the pairing asked about. AD-4
        # forbids recomputing a published change; it does not license answering one
        # question with another question's column, which is the F-005 failure in its
        # other direction.
        return None
    flavour = tables.flavour_for(unit)
    value = read_change(flavour, published.cell(basis, flavour))
    if value is None:
        return None
    return SelectedChange(
        basis=basis,
        value=value,
        column=column_identity(basis, flavour),
        later=later,
        earlier=earlier,
    )


def compute_change(
    tables: ChangeTables, later: Figure, earlier: Figure, unit: str, basis: Basis
) -> ComputedChange:
    """The change between two published readings, for the case where no column matches.

    Refuses outright when the rules still allow a published column to answer: AD-4's
    prohibition is on *recomputing what is published*, so the guard is here, at the only
    function that can produce a computed value, rather than in each caller's conscience.
    """
    if not tables.may_compute_when_nothing_matches():
        raise ChangeTableError(
            f"{ChangeRule.PUBLISHED_COLUMN_IS_SELECTED.value} does not allow a change to "
            "be computed; where no published column matches, the answer is that none is "
            "published"
        )
    flavour = tables.flavour_for(unit)
    return ComputedChange(
        basis=basis,
        value=computed_change(flavour, later.value, earlier.value),
        later=later,
        earlier=earlier,
    )
