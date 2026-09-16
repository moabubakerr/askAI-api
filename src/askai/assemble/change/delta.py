"""The change element: what moved, on what basis, between which two periods.

Purity: pure. Every word from ``messages/``, every figure through the single
``Formatter``, every decision from ``rules/``.

Stories 3.4, 3.5 and 3.6 are one composer because they are one element. A selected column
with no basis on it is not a safer answer than a computed one -- it is the same
undefendable figure with better provenance. So the label is not something this module
adds after building the element; it is the condition on which the element may be built.

**The label is enforced against the catalogue, not against a habit.**
``R-CHANGE-CARRIES-BASIS-AND-PERIODS`` says a change is shown with its basis, both
periods and the reading it moved to. What that means in practice is that the message
template has to *have somewhere to put them*, so the composer checks the message's own
parameter set before rendering it. A wording edit that dropped ``{basis}`` from
``change.selected`` would otherwise produce a perfectly fluent unlabelled growth figure,
in one language only, and pass every test that looked at the number.

**The basis is a word, not an abbreviation.** FR-63: ``change.basis.yoy`` is authored in
both languages, so the Arabic answer says the Arabic phrase rather than a transliterated
``YoY``. There is no path here that spells a ``Basis`` member into reader-facing text.

**Selected and computed are different sentences and different classes.** A selected change
is ``measured`` and says what moved; a computed one is ``derived``, says so, and names the
two published readings it came from (FR-19). Neither class is chosen here -- each is read
off the value's own type -- so an element classed ``measured`` carrying a computed change
is unrepresentable rather than merely avoided.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.change.selection import (
    Change,
    ChangeTables,
    ComputedChange,
    SelectedChange,
)
from askai.assemble.elements import build
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.change import Basis
from askai.messages import Catalogue, CatalogueError, Lang, render, render_period
from askai.ports.presentation import PublishedDetail

__all__ = [
    "ChangeComposition",
    "ChangeMessage",
    "ChangeRefusal",
    "ComposedChange",
    "NoChangePublished",
    "UnlabelledChange",
    "basis_words",
    "change_composition",
    "no_change_published",
]


class ChangeMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    SELECTED = "change.selected"
    COMPUTED = "change.computed"
    NOT_PUBLISHED = "change.not_published"

    BASIS_YOY = "change.basis.yoy"
    BASIS_QOQ = "change.basis.qoq"
    BASIS_MOM = "change.basis.mom"


class ChangeRefusal(StrEnum):
    """Why a change question reaches no figure. A closed set, never a sentence."""

    NO_PUBLISHED_COLUMN = "no-published-change-column-for-this-pairing"
    """No column matches the grain and the basis, and either the readings to compute one
    from are not both published or computing is not allowed. Distinct from "the
    indicator publishes nothing": the indicator is here and this particular pairing is
    not."""


class UnlabelledChange(CatalogueError):
    """A change would have been shown without something the rules require it to carry.

    A subclass of ``CatalogueError`` because that is what it always is in practice: the
    template lost a field. Raised rather than patched over, because FR-20's *"an
    unlabelled growth figure is a failing test, not a cosmetic issue"* is only true if
    something fails.
    """


# ---------------------------------------------------------------------- the two results


@dataclass(frozen=True, slots=True)
class ComposedChange:
    """The change element, and the value it was composed from.

    Both, so a corpus entry can assert on the **selected column identity** rather than on
    the rendered number alone -- which is the assertion Story 3.4 asks for, and the one
    that would have caught F-005 and F-029.
    """

    placed: Placed
    change: Change

    @property
    def basis(self) -> Basis:
        return self.change.basis

    @property
    def column(self) -> str | None:
        """The published column this came from, or ``None`` where it was computed."""
        return self.change.column if isinstance(self.change, SelectedChange) else None

    @property
    def was_computed(self) -> bool:
        return isinstance(self.change, ComputedChange)


@dataclass(frozen=True, slots=True)
class NoChangePublished:
    """No change figure is available for this pairing, and this says so to the reader."""

    reason: ChangeRefusal
    basis: Basis
    statement: str


#: What composing a change reaches. Closed, so a caller that handles the figure and
#: forgets the "none is published" case does not type-check.
type ChangeComposition = ComposedChange | NoChangePublished


def basis_words(catalogue: Catalogue, lang: Lang, basis: Basis) -> str:
    """*basis*, as the language writes it (FR-63).

    Exhaustive on the enum with no fallback: a basis the engine selects a column for is a
    basis the answer has to be able to name, and a default here would put one basis's
    word on another basis's figure -- which is the same class of defect as showing a
    percentage as percentage points, one level up.
    """
    match basis:
        case Basis.YOY:
            message = ChangeMessage.BASIS_YOY
        case Basis.QOQ:
            message = ChangeMessage.BASIS_QOQ
        case Basis.MOM:
            message = ChangeMessage.BASIS_MOM
        case _:
            raise CatalogueError(
                f"{basis!r} has no phrase in the catalogue; a basis the engine answers on "
                "is a basis the answer has to be able to name in both languages"
            )
    return render(catalogue, lang, message.value)


def change_composition(
    change: Change,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: ChangeTables,
    lang: Lang,
) -> ComposedChange:
    """Compose *change* into its element, labelled with everything the rules require.

    The mode is asked for by role and never named here (AD-18, FR-48); the class is read
    off the value and never chosen here (FR-19); the basis and both periods are checked
    against the message's own parameters before a word is rendered (FR-20).
    """
    role = Role.DELTA
    mode = placement.mode_for(role)
    message = (
        ChangeMessage.SELECTED if isinstance(change, SelectedChange) else ChangeMessage.COMPUTED
    )
    _check_the_label_carries_what_the_rules_require(catalogue, tables, message)

    detail_format = PublishedFormat(unit=published.unit, spec=published.value_format)
    # The change is written to the indicator's own published precision, in the change's
    # own unit. Its unit is not the indicator's -- an inflation rate is published in %
    # and its movement is shown in pp -- but the number of decimals a reader expects is
    # the one the indicator is published to, so the Format field carries across and the
    # unit does not.
    change_format = PublishedFormat(
        unit=tables.unit_for(change.flavour), spec=published.value_format
    )
    later = formatter.format(change.later.value, detail_format, mode, lang)
    movement = formatter.format(change.value, change_format, mode, lang)

    provenance = Provenance(
        detail_id=change.later.detail_id,
        period=change.later.period,
        country=change.later.country_id,
        source_id=published.source_id,
    )
    if isinstance(change, SelectedChange):
        content = render(
            catalogue,
            lang,
            message.value,
            detail=published.name,
            value=later.value,
            unit=later.unit,
            later=render_period(catalogue, lang, change.later.period),
            change=movement.value,
            change_unit=movement.unit,
            basis=basis_words(catalogue, lang, change.basis),
            earlier=render_period(catalogue, lang, change.earlier),
        )
    else:
        # The published reading the movement was computed from, written at the same
        # precision as the one it moved to, so a reader can check the arithmetic against
        # the two numbers actually shown.
        earlier_written = formatter.format(change.earlier.value, detail_format, mode, lang)
        content = render(
            catalogue,
            lang,
            message.value,
            detail=published.name,
            value=later.value,
            unit=later.unit,
            later=render_period(catalogue, lang, change.later.period),
            earlier_value=earlier_written.value,
            earlier=render_period(catalogue, lang, change.earlier.period),
            change=movement.value,
            change_unit=movement.unit,
            basis=basis_words(catalogue, lang, change.basis),
        )
    return ComposedChange(
        placed=Placed(element=build(content, change.element_class, provenance), role=role),
        change=change,
    )


def no_change_published(
    published: PublishedDetail, catalogue: Catalogue, lang: Lang, basis: Basis
) -> NoChangePublished:
    """*"No published change figure is available for this indicator, year on year."*

    A stated outcome rather than a blank, and it names the basis it was asked for --
    because *"no change is published"* and *"no **quarter-on-quarter** change is
    published"* are different facts and only the second is true of a yearly series.
    """
    return NoChangePublished(
        reason=ChangeRefusal.NO_PUBLISHED_COLUMN,
        basis=basis,
        statement=render(
            catalogue,
            lang,
            ChangeMessage.NOT_PUBLISHED.value,
            detail=published.name,
            basis=basis_words(catalogue, lang, basis),
        ),
    )


def _check_the_label_carries_what_the_rules_require(
    catalogue: Catalogue, tables: ChangeTables, message: ChangeMessage
) -> None:
    """Refuse to render a change whose wording has nowhere to put its label.

    Checked against the catalogue's own parameter set, which is the union across both
    languages, so a field dropped from one half of the catalogue is caught here rather
    than reaching only Arabic readers. This is FR-20's *"an unlabelled growth figure is a
    failing test"* made into a test that cannot be forgotten to write.
    """
    fields = catalogue.parameters(message.value)
    required: list[str] = []
    if tables.must_name_the_basis():
        required.append("basis")
    if tables.must_name_both_periods():
        required += ["later", "earlier"]
    if tables.must_carry_the_later_reading():
        required.append("value")
    missing = sorted(field for field in required if field not in fields)
    if missing:
        raise UnlabelledChange(
            f"message {message.value!r} does not carry {missing}, which "
            f"R-CHANGE-CARRIES-BASIS-AND-PERIODS requires every change figure to be shown "
            "with; a growth figure the reader cannot place is not a shorter answer, it is "
            "an undefendable one (FR-20, R-168)"
        )
