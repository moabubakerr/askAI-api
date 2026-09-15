"""``Role`` -- the job an element does, and the two decisions that follow from it.

Purity: pure. Reads its two tables from ``rules/``; holds no lens list and no mode of
its own.

``domain/element.py`` models ``class`` and stops: *"Role is not modelled here -- it
arrives with the lens mapping in rules/."* This is that arrival. The two axes stay
independent -- ``class`` asks where the content came from and governs what the element
may contain, ``role`` asks what job it does and governs where it goes -- so ``Role`` is
a separate value and ``Placed`` pairs the two rather than a single field forcing them
together.

**Role is assigned in ``assemble/`` and read everywhere else.** A composer says what job
the element it just built does; it does not say which lens shows it and it does not say
at what precision its figures are written. Both of those are read off
``R-ROLE-LENS-MAPPING`` and ``R-ROLE-FORMAT-MODE``:

* **The lens mapping** (AD-23). The lens is a view over one answer, never an input to
  it, so which elements each lens shows is a table a reviewer edits -- not a parameter,
  and not a field repeated on every element. ``scope`` is in both lenses, which is the
  clause FR-59b rests on.
* **The mode mapping** (AD-18, FR-48). *"The mode is a property of the position in the
  answer, decided once, not chosen per composer."* A position is a role, so
  ``mode_for`` is the one place a ``FormatMode`` is chosen and no composer names one.

The three mode lists are checked to **partition** the roles on every read. A role in
none of them would leave the mode to whichever composer reached it first; a role in two
would render one published row two ways on one card. Neither can be a schema constraint
-- the loader sees three independent clauses -- so it is checked here, and a role added
to the file without a mode fails on the first answer rather than on the first card
nobody looked at.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.format import FormatMode
from askai.domain.element import Element
from askai.rules import RuleSet

__all__ = [
    "Lens",
    "Placed",
    "Placement",
    "PlacementClause",
    "PlacementError",
    "PlacementRule",
    "Role",
]


class Role(StrEnum):
    """What job an element does in the answer (the spine's response shape).

    Closed, and spelled here rather than in the rule file: the file says what each role
    *implies*, and a role it names that the engine does not know is a typo, not a new
    member. ``Role(name)`` raising on one is how the typo is found.
    """

    HEADLINE = "headline"
    """The figure the reader reads first."""

    SERIES = "series"
    """The run of published readings behind the headline."""

    DELTA = "delta"
    """The movement, with the two readings it was computed from."""

    EVIDENCE = "evidence"
    """A published row shown as published, so the headline can be checked against it."""

    ANALYSIS = "analysis"
    """Analyst text bound to a datapoint, or the statement that none is published."""

    COMMENTARY = "commentary"
    """Published editorial -- an article, which is bound to no indicator."""

    SCOPE = "scope"
    """What the answer did: the grain, the period and the country scope it used (FR-56)."""

    NOTE = "note"
    """A caveat the reader is entitled to before acting on the figure."""


class Lens(StrEnum):
    """The two renderings of one answer. A view, never a request parameter (AD-23)."""

    EXECUTIVE = "executive"
    """The answer, its basis and its provenance, short."""

    EXPLORE = "explore"
    """The same bound answer with the depth added back."""


class PlacementRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    LENS_MAPPING = "R-ROLE-LENS-MAPPING"
    FORMAT_MODE = "R-ROLE-FORMAT-MODE"


class PlacementClause(StrEnum):
    """The clause names read off those rules."""

    EXECUTIVE_ROLES = "executive_roles"
    EXPLORE_ROLES = "explore_roles"
    HEADLINE_ROLES = "headline_roles"
    EVIDENCE_ROLES = "evidence_roles"
    UNFIGURED_ROLES = "unfigured_roles"


class PlacementError(LookupError):
    """The role tables cannot be acted on, or were asked something they do not answer.

    Raised rather than defaulted, in every case. A missing role silently taking evidence
    precision is the F-004 defect arriving through an omission, and a role missing from
    both lenses would be an element composed, admitted, and then shown to nobody.
    """


@dataclass(frozen=True, slots=True)
class Placed:
    """One element, and the job it does in the answer.

    Two values held side by side rather than one field on ``Element``: the class is set
    at construction and travels with the content wherever it goes (AD-6), while the role
    is a statement about *this* answer's shape. Collapsing them would lose the
    distinction FR-96 exists to keep -- an ``analysis`` role is class ``attributed``
    when it is filled from a datapoint note and class ``article`` when it is filled from
    an article.
    """

    element: Element
    role: Role


@dataclass(frozen=True, slots=True)
class Placement:
    """The role tables, read through the rule set they live in.

    A value constructed with the rule set rather than a module of functions reading a
    cached global -- the same reason ``Formatter`` is a value: a module-level rule set
    would be ambient state, and the tables are handed in by whoever assembled the answer.
    """

    rule_set: RuleSet

    def mode_for(self, role: Role) -> FormatMode:
        """The ``FormatMode`` figures in a *role* are written at (AD-18, FR-48).

        The one place a mode is chosen. A composer holds a role and asks; it never names
        ``HEADLINE`` or ``EVIDENCE`` itself, which is what makes *"decided once by the
        element's position"* true rather than intended.
        """
        headline = self._roles(PlacementRule.FORMAT_MODE, PlacementClause.HEADLINE_ROLES)
        evidence = self._roles(PlacementRule.FORMAT_MODE, PlacementClause.EVIDENCE_ROLES)
        unfigured = self._roles(PlacementRule.FORMAT_MODE, PlacementClause.UNFIGURED_ROLES)
        _check_partition(headline, evidence, unfigured)
        if role in headline:
            return FormatMode.HEADLINE
        if role in evidence:
            return FormatMode.EVIDENCE
        raise PlacementError(
            f"{PlacementRule.FORMAT_MODE.value} lists `{role.value}` as carrying no "
            "figure, so it has no display mode; an element of this role states "
            "something rather than showing a published value"
        )

    def carries_a_figure(self, role: Role) -> bool:
        """Whether *role* is one the mode table gives a mode to.

        The way a caller asks before asking, so ``mode_for`` can stay total-or-raise
        rather than returning ``None`` -- a ``None`` mode is a mode waiting for a
        default, and the default is how a headline acquires evidence precision.
        """
        unfigured = self._roles(PlacementRule.FORMAT_MODE, PlacementClause.UNFIGURED_ROLES)
        return role not in unfigured

    def lenses_for(self, role: Role) -> frozenset[Lens]:
        """Every lens that shows *role* (AD-23).

        Refuses a role no lens names: an element composed, admitted and then shown in
        neither lens is the silent drop AD-7 spends its whole design preventing,
        arriving one layer later.
        """
        showing = frozenset(lens for lens in Lens if role in self.roles_in(lens))
        if not showing:
            raise PlacementError(
                f"{PlacementRule.LENS_MAPPING.value} names `{role.value}` in no lens, so "
                "an element of this role would be composed and then shown to nobody; "
                "every role belongs to at least one lens"
            )
        return showing

    def roles_in(self, lens: Lens) -> frozenset[Role]:
        """The roles *lens* shows, as the mapping declares them."""
        match lens:
            case Lens.EXECUTIVE:
                clause = PlacementClause.EXECUTIVE_ROLES
            case Lens.EXPLORE:
                clause = PlacementClause.EXPLORE_ROLES
            case _:
                raise PlacementError(
                    f"{lens!r} has no clause in {PlacementRule.LENS_MAPPING.value}; a "
                    "lens the engine offers is a lens the mapping has to place"
                )
        return self._roles(PlacementRule.LENS_MAPPING, clause)

    def shows(self, lens: Lens, role: Role) -> bool:
        """Whether *lens* shows *role*. The reader's toggle, applied."""
        return lens in self.lenses_for(role)

    def _roles(self, rule: PlacementRule, clause: PlacementClause) -> frozenset[Role]:
        value = self.rule_set.value(rule.value, clause.value)
        if not isinstance(value, tuple):
            raise PlacementError(
                f"{rule.value} value `{clause.value}` must be a list of role names, not "
                f"{type(value).__name__}; assemble/ reads its roles from the rule file "
                "and has no list of its own to fall back to"
            )
        return frozenset(_role(name, rule, clause) for name in value)


def _role(name: str, rule: PlacementRule, clause: PlacementClause) -> Role:
    try:
        return Role(name)
    except ValueError:
        known = ", ".join(role.value for role in Role)
        raise PlacementError(
            f"{rule.value} value `{clause.value}` names `{name}`, which is not a role; "
            f"the roles are {known}"
        ) from None


def _check_partition(*groups: Iterable[Role]) -> None:
    """Every role named exactly once across the mode lists, or nothing is answered.

    Checked on every read rather than at load because the loader sees three independent
    clauses and has nothing to compare them against. The cost is a set operation per
    call; the alternative is a role whose mode is decided by call order.
    """
    listed = [frozenset(group) for group in groups]
    missing = sorted(role.value for role in Role if not any(role in group for group in listed))
    twice = sorted(
        role.value for role in Role if sum(1 for group in listed if role in group) > 1
    )
    if missing or twice:
        raise PlacementError(
            f"{PlacementRule.FORMAT_MODE.value} must name every role exactly once: "
            f"named by no clause {missing or 'nothing'}, named twice {twice or 'nothing'}"
            "; a role with no mode leaves the precision to whichever composer reaches it "
            "first, and a role with two renders one row two ways on one card"
        )
