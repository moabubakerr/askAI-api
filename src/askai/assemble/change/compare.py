"""Comparing one indicator at two named periods -- a comparison whose dimension is time.

Purity: pure.

FR-23's defect is the engine turning a question about time into a question about
countries. The guard is that the dimension is **derived from the entities the question
named** and from nothing else: two periods and one detail is a period comparison; two
countries and one period is a country comparison and is Epic 4's, answered by a different
composition. Neither is a default, and there is no branch here that reaches a country.

``compile/periods.py`` already did the hard half. *"Between X and Y"* and *"compare X and
Y"* deliberately do **not** bind as a ``Range``: a comparison of two readings (FR-23) and
a run of readings across them (FR-16) are different questions, so the period field arrives
``Unbound`` carrying ``more-than-one-period-named`` with the two periods spelled into its
particulars. ``named_periods`` reads them back out. That is why this composer takes an
unbound field and is not a contradiction of AD-1: nothing is re-bound, widened or
reinterpreted -- the two periods the reader named are read from the account ``compile/``
already wrote, and the answer is composed from them.

**A published column is preferred, and only where it actually spans the pairing.**
``paired_with`` says which two periods a basis column covers, so *"2024 against 2025"* on
a yearly series is answered from the published YoY column and *"2022 against 2025"* is
computed and says so. The difference is checked, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from askai.assemble.change.delta import ComposedChange, change_composition
from askai.assemble.change.selection import (
    Change,
    ChangeTables,
    PublishedChange,
    compute_change,
    paired_with,
    select_change,
)
from askai.assemble.elements import measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.compile.binding import UnboundReason
from askai.domain.change import Basis
from askai.domain.period import Period, PeriodFormatError
from askai.domain.spec import Bound, Deferred, FieldState, PeriodSpec, Unbound
from askai.execute.value import Figure
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.presentation import PublishedDetail

__all__ = [
    "CompareMessage",
    "ComparisonDimension",
    "ComparisonError",
    "PeriodComparison",
    "compare_periods",
    "comparison_dimension",
    "named_periods",
]


class CompareMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    READING = "answer.value"
    """Each period's own reading, said the way a single value is said -- deliberately the
    same id, because it is the same sentence and a second one would drift from it."""


class ComparisonDimension(StrEnum):
    """What a comparison is across. Derived from the question, never defaulted (FR-23)."""

    PERIOD = "period"
    """One detail, two named periods."""


class ComparisonError(ValueError):
    """A period comparison was asked for over something that is not one."""


def named_periods(state: FieldState[PeriodSpec]) -> tuple[Period, ...]:
    """The periods a question named, where it named more than one; otherwise empty.

    Empty for every other state, and that is the FR-23 guard in one line: a question that
    bound a single period, deferred one, or was refused for any other reason is not a
    period comparison, and nothing here turns it into one.
    """
    match state:
        case Unbound(reason=reason):
            # The code is read off `compile/`'s own enum rather than restated here. The
            # binder owns the classification, and a second spelling of it would be a
            # comparison composer that silently stops recognising its own case the day
            # the code changes -- with nothing failing, because the string still parses.
            code, _, particulars = reason.partition(": ")
            if code != UnboundReason.MORE_THAN_ONE_PERIOD_NAMED.value:
                return ()
            try:
                return tuple(
                    Period(spelling.strip())
                    for spelling in particulars.split(",")
                    if spelling.strip()
                )
            except PeriodFormatError:
                # The binder spells published periods into the particulars, so anything
                # else means the account was written by something other than compile/.
                # Reported as "this is not a period comparison" rather than repaired.
                return ()
        case Bound() | Deferred():
            return ()


def comparison_dimension(state: FieldState[PeriodSpec]) -> ComparisonDimension | None:
    """``PERIOD`` when the question named two periods for one detail, else ``None``.

    ``None`` is not "no comparison": it is *"not a comparison across time"*. A question
    naming countries binds a country scope and is answered by Epic 4's composition; the
    two are never conflated, and this function cannot return the other one because the
    other one is not a member here.
    """
    # Matched as a shape rather than counted, so "a pair" is spelled as a pair. A count
    # here would be a numeric literal in `assemble/`, which is banned for good reason:
    # every other number in this layer is a decision a reader is entitled to read in
    # `rules/`, and an exemption for this one would be the first crack in that.
    match named_periods(state):
        case (_, _):
            return ComparisonDimension.PERIOD
        case _:
            return None


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    """Both readings, named alongside their figures, and the movement between them."""

    dimension: ComparisonDimension
    readings: tuple[Placed, ...]
    change: ComposedChange

    @property
    def periods(self) -> tuple[Period, Period]:
        """Both periods, earlier first -- read off the change, which owns the pairing.

        A selected change carries the earlier period and a computed one carries the
        earlier *reading*; both name the same period, and reading it from the change
        rather than storing it again is what stops the two disagreeing.
        """
        movement = self.change.change
        earlier = movement.earlier
        return (
            earlier if isinstance(earlier, Period) else earlier.period,
            movement.later.period,
        )

    @property
    def was_computed(self) -> bool:
        return self.change.was_computed


def compare_periods(
    earlier: Figure,
    later: Figure,
    published: PublishedDetail,
    published_change: PublishedChange,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    tables: ChangeTables,
    lang: Lang,
) -> PeriodComparison:
    """Compare one detail at two named periods, preferring a published change column.

    Both readings are composed as evidence, each naming its own period, because *"both
    periods are named alongside their figures"* (FR-23) is what makes the movement
    checkable. The movement itself is selected where a published column spans exactly this
    pairing and computed otherwise -- and a computed one says so, in its own sentence and
    in its element class.
    """
    if earlier.period.grain is not later.period.grain:
        raise ComparisonError(
            f"a comparison across time runs at one grain, and {earlier.period} against "
            f"{later.period} names two; no adjacent grain is ever substituted (FR-6)"
        )
    if later.period.start <= earlier.period.start:
        raise ComparisonError(
            f"{earlier.period} does not precede {later.period}; a comparison across time "
            "is stated from the earlier reading to the later one"
        )

    change = _change_between(earlier, later, published, published_change, tables)
    return PeriodComparison(
        dimension=ComparisonDimension.PERIOD,
        readings=tuple(
            _reading(figure, published, catalogue, formatter, placement, lang)
            for figure in (earlier, later)
        ),
        change=change_composition(
            change, published, catalogue, formatter, placement, tables, lang
        ),
    )


def _change_between(
    earlier: Figure,
    later: Figure,
    published: PublishedDetail,
    published_change: PublishedChange,
    tables: ChangeTables,
) -> Change:
    """The published column spanning this exact pairing, or the computed movement.

    Every basis the later row's grain may carry is tried, in the published order, and a
    basis is only tried at all where ``paired_with`` says its column covers these two
    periods. So the preference for a published column is exercised rather than asserted,
    and the fallback happens only where the export genuinely has nothing.
    """
    for basis in sorted(tables.bases_for(later.period.grain)):
        if paired_with(basis, later.period) != earlier.period:
            continue
        selected = select_change(
            tables, published_change, later, earlier.period, published.unit, basis
        )
        if selected is not None:
            return selected
    span_basis = _basis_for_the_span(tables, later)
    return compute_change(tables, later, earlier, published.unit, span_basis)


def _basis_for_the_span(tables: ChangeTables, later: Figure) -> Basis:
    """Which basis a computed movement across an arbitrary span is labelled with.

    The grain's own default. A computed change between 2022 and 2025 is not year on year
    in the published sense, and the sentence it appears in says it was computed and names
    both periods -- so the basis word describes the grain the comparison ran at rather
    than claiming a published column the answer has already said it did not use.
    """
    return tables.default_basis(later.period.grain)


def _reading(
    figure: Figure,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
) -> Placed:
    """One of the two readings, shown as published so the movement can be checked."""
    role = Role.EVIDENCE
    written = formatter.format(
        figure.value,
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        lang,
    )
    content = render(
        catalogue,
        lang,
        CompareMessage.READING.value,
        detail=published.name,
        value=written.value,
        unit=written.unit,
        period=render_period(catalogue, lang, figure.period),
    )
    provenance = Provenance(
        detail_id=figure.detail_id,
        period=figure.period,
        country=figure.country_id,
        source_id=published.source_id,
    )
    return Placed(element=measured(content, provenance), role=role)
