"""The one place a figure is produced, and it is produced by exact key (AD-3).

Purity: IO, via ports only.

Story 1.12. A ``CompiledQuestion`` arrives with its ``QuerySpec`` frozen; this module
resolves whatever ``compile/`` deferred, fetches by exact key on
``(detail, period, country)``, and returns an ``Outcome`` -- the figure, a stated absence,
or a stated failure. There is no fourth answer and, in particular, no empty value:
*"a figure that cannot be traced to a row does not exist"*, and a detail that publishes
nothing is a stated outcome rather than a blank.

**Nothing on the spec is set, widened or reinterpreted here** (AD-1). An ``Unbound``
field is not repaired, not defaulted and not guessed at -- it becomes a cause. The only
field this module resolves is the one AD-1 reserved for it: a ``Deferred`` period, whose
request is determinate and whose answer needs the data. What it resolved to travels back
on ``Execution.resolution``, so the answer and the audit record state the same period
rather than each deciding one (FR-8, AD-16).

**The scan is over periods; the fetch is by key.** Choosing which period is the latest
reads the series' calendar, which carries no values at all, and then fetches candidates
by exact key until one carries a published reading. So every number that exists came out
of a single keyed row, and FR-8's placeholder clause is applied to a row rather than to a
guess about one.

**Absence and failure are different answers** (AD-15). ``Absent`` is a well-founded
nothing -- this detail publishes no row, no reading has happened yet, the newest reading
is not a number -- and it always names its cause. ``Failed`` is the adapter not working,
and carries a counted ``Degradation``. Because ``Outcome`` is a closed union, a caller
that handles the first and forgets the second does not type-check, which is the
foreclosure rather than a convention about how to write the ``else``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from askai.compile.binding import CompiledQuestion, SpecField
from askai.domain.degradation import Degradation
from askai.domain.period import Grain, Period
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Deferred,
    FieldState,
    Measure,
    Operation,
    PeriodSpec,
    QuerySpec,
    Unbound,
    requires_data_to_resolve,
)
from askai.domain.text import is_published_text
from askai.execute.latest import (
    FetchRule,
    candidate_periods,
    latest_measure,
    placeholder_rows_are_eligible,
    readings_wanted,
)
from askai.observability.degradations import (
    Absent,
    DegradationKind,
    Failed,
    Found,
    Outcome,
    degradations_of,
    degrade,
)
from askai.ports.datapoints import DatapointRow, DatapointsPort, DatapointsUnavailable

__all__ = [
    "Execution",
    "Figure",
    "FigureCause",
    "Reading",
    "Where",
    "execute_value",
]


class Where(StrEnum):
    """The address a degradation carries, so a rising rate has somewhere to point."""

    EXECUTE = "execute.value"


class FigureCause(StrEnum):
    """Why an execution did not produce a figure -- a closed set, never a sentence.

    Every member is a *cause*, not an apology: the answer package states it, the record
    keeps it, and a reader is told which of these happened rather than being shown an
    empty space. Composing the reader-facing wording from these is ``narrate/``'s job,
    from the bilingual catalogue, which is why there is no reader-facing prose here.

    The cause is carried on ``Execution`` **and** spelled into the ``Absent`` reason, the
    same way ``compile/`` spells an ``UnboundReason`` into ``Unbound`` -- a code stays
    exact where a sentence drifts, and the reason field is what an operator reads.
    """

    # The question never bound this field, so there is nothing to fetch.
    DETAIL_NOT_BOUND = "detail-not-bound"
    PERIOD_NOT_BOUND = "period-not-bound"
    COUNTRY_SCOPE_NOT_BOUND = "country-scope-not-bound"
    MEASURE_NOT_BOUND = "measure-not-bound"
    OPERATION_NOT_BOUND = "operation-not-bound"

    # The bound query is not the single-figure fetch this module performs.
    OPERATION_IS_NOT_A_VALUE = "operation-is-not-a-value"
    SCOPE_IS_NOT_ONE_SERIES = "country-scope-is-not-one-series"
    CHANGE_IS_A_PUBLISHED_COLUMN = "change-is-selected-not-fetched"

    # The data answered, and what it said was "nothing here".
    DETAIL_PUBLISHES_NOTHING = "detail-publishes-no-datapoints"
    SCOPE_PUBLISHES_NOTHING = "detail-publishes-nothing-in-this-country-scope"
    NO_READING_AT_OR_BEFORE_TODAY = "no-actual-at-or-before-today"
    NO_ROW_FOR_THE_NAMED_PERIOD = "no-row-for-the-named-period"
    MEASURE_NOT_PUBLISHED = "measure-not-published-for-this-row"

    #: The row exists and publishes something that is not a number. 126 rows across 21
    #: details publish a bilingual value -- a rating, a tier, a band -- rather than a
    #: figure. That is an absence *of a figure*, not a broken row and not a failure.
    VALUE_IS_NOT_A_FIGURE = "published-value-is-not-a-number"

    #: The read model itself did not answer. The only cause that is a ``Failed``.
    LOOKUP_FAILED = "read-model-lookup-failed"


@dataclass(frozen=True, slots=True)
class Figure:
    """One published number, and the row it came from.

    There is no constructor that omits the source row, so *"an untraceable figure does
    not exist"* is a property of the type rather than a rule someone has to follow.

    ``value`` is a ``Decimal`` parsed from the published digits -- never a float, which
    is the rounding defect arriving through the storage layer.
    """

    detail_id: str
    period: Period
    #: ``None`` is the national marker: the row carries no country at all (AD-5).
    country_id: str | None
    measure: Measure
    value: Decimal
    source_datapoint_id: str

    @property
    def grain(self) -> Grain:
        """Read off the period. There is no grain field here to disagree with it."""
        return self.period.grain

    @property
    def is_national(self) -> bool:
        return self.country_id is None


@dataclass(frozen=True, slots=True)
class Reading:
    """One resolved period and the figure at it, for a request asking for several."""

    period: Period
    figure: Figure


@dataclass(frozen=True, slots=True)
class PeriodResolution:
    """What the period field resolved to, and whether it needed the data to resolve.

    AD-1 requires ``execute/`` to record what it resolved a deferred request to. This is
    that record: the request as ``compile/`` froze it, the periods it came out as, and
    the rule that decided. The answer states it and the audit record keeps it, from one
    value rather than from two readings of the same question.
    """

    request: PeriodSpec | None
    was_deferred: bool
    periods: tuple[Period, ...]
    #: The rule that resolved a deferred request, or ``None`` when nothing was deferred.
    resolved_by: str | None

    @property
    def period(self) -> Period | None:
        """The single period a value question was answered at, if it reached one."""
        return self.periods[0] if self.periods else None


@dataclass(frozen=True, slots=True)
class Execution:
    """What the fetch did: the outcome, what the period resolved to, what degraded.

    ``outcome`` is the closed three-state ``Outcome``; ``cause`` is the closed code for
    why it is not a figure. They agree by construction -- a figure has no cause and a
    non-figure always has one -- so an answer cannot be composed from an outcome whose
    reason nobody recorded.
    """

    outcome: Outcome[Figure]
    resolution: PeriodResolution
    cause: FigureCause | None = None
    #: Every reading a multi-reading request resolved to, newest first.
    readings: tuple[Reading, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.outcome, Found) is not (self.cause is None):
            raise ValueError(
                f"the outcome is {type(self.outcome).__name__} and the cause is "
                f"{self.cause}; a figure has no cause and anything else states one"
            )

    @property
    def figure(self) -> Figure | None:
        """The figure, or ``None``.

        Reading this is never how a cause gets dropped: ``outcome`` and ``cause`` carry
        it, and they are what the answer is composed from.
        """
        return self.outcome.value if isinstance(self.outcome, Found) else None

    @property
    def degradations(self) -> tuple[Degradation, ...]:
        """What went wrong producing this -- empty for a figure and for an absence."""
        return degradations_of(self.outcome)


# ------------------------------------------------------------------ reading the spec


def _bound[T](state: FieldState[T]) -> T | None:
    """The value of a bound field, or ``None``. Never a default, never a repair."""
    return state.value if isinstance(state, Bound) else None


def _requested(spec: QuerySpec) -> PeriodSpec | None:
    """The period request, whether ``compile/`` bound it or deferred it.

    Both states carry a determinate request; only ``Unbound`` carries none. Reading them
    together is not widening the field -- neither branch changes what the request is, and
    a deferred one is still resolved against the data rather than assumed.
    """
    match spec.period:
        case Bound(value=request) | Deferred(request=request):
            return request
        case Unbound():
            return None


def _country_of(scope: CountryScope) -> tuple[str | None, bool]:
    """The country id to fetch by, and whether this scope is a single series.

    National scope is the *absence* of a country, so it maps to ``None`` -- there is no
    name to construct and nothing to compare a name against (AD-5). A named set of one
    is a single series; a named set of several, and the declared benchmark set, are a
    cross-country selection, which is a different query assembled in one place.
    """
    match scope:
        case National():
            return None, True
        case DeclaredBenchmarks():
            return None, False
        case Named(countries=countries):
            if len(countries) == 1:
                return next(iter(countries)), True
            return None, False


def _scope_name(country_id: str | None) -> str:
    return "the national scope" if country_id is None else f"country {country_id}"


def _unanswerable(question: CompiledQuestion) -> tuple[FigureCause, str] | None:
    """The states in which there is nothing to fetch, each named by its own cause.

    An ``Unbound`` field is never repaired here. AD-1 gives ``compile/`` the last word on
    every field, so the answer to "the reader was not specific enough" is a clarification
    or a refusal, not a fetch against a value this layer chose.
    """
    for field, cause in (
        (SpecField.DETAIL, FigureCause.DETAIL_NOT_BOUND),
        (SpecField.PERIOD, FigureCause.PERIOD_NOT_BOUND),
        (SpecField.COUNTRY_SCOPE, FigureCause.COUNTRY_SCOPE_NOT_BOUND),
        (SpecField.MEASURE, FigureCause.MEASURE_NOT_BOUND),
        (SpecField.OPERATION, FigureCause.OPERATION_NOT_BOUND),
    ):
        state = question.state_of(field)
        if isinstance(state, Unbound):
            return cause, f"{field.value}: {state.reason}"

    spec = question.spec
    operation = _bound(spec.operation)
    if operation is not Operation.VALUE:
        return (
            FigureCause.OPERATION_IS_NOT_A_VALUE,
            f"{operation} is not the single-figure fetch this selection performs",
        )
    if _bound(spec.measure) is Measure.CHANGE:
        return (
            FigureCause.CHANGE_IS_A_PUBLISHED_COLUMN,
            (
                "a change value is selected from the published column matching the "
                "grain and the basis, never fetched as a measure or computed (AD-4)"
            ),
        )
    return None


# ------------------------------------------------------------------ reading the rows


def _read(text: str) -> Decimal | None:
    """The published digits as a ``Decimal``, or ``None`` when they are not a number."""
    try:
        return Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None


def _figure(row: DatapointRow, measure: Measure, value: Decimal) -> Figure:
    return Figure(
        detail_id=row.detail_id,
        period=row.period,
        country_id=row.country_id,
        measure=measure,
        value=value,
        source_datapoint_id=row.source_datapoint_id,
    )


def _carries_a_reading(row: DatapointRow) -> bool:
    """Does this row carry a published actual, rather than a placeholder? (FR-8.)

    The engine's single emptiness predicate decides, because the export spells absence
    four ways at once and a fetch agreeing with only one of them would serve the others
    as values.
    """
    published = row.cell(latest_measure())
    if placeholder_rows_are_eligible():
        return published is not None
    return is_published_text(published)


def _resolution(
    request: PeriodSpec, deferred: bool, periods: tuple[Period, ...]
) -> PeriodResolution:
    return PeriodResolution(
        request=request,
        was_deferred=deferred,
        periods=periods,
        resolved_by=FetchRule.MOST_RECENT_ACTUAL.value if deferred else None,
    )


def _nothing(cause: FigureCause, particulars: str, request: PeriodSpec | None) -> Execution:
    """An absence reached before any row was read, so nothing resolved."""
    return _absent(
        cause,
        particulars,
        PeriodResolution(
            request=request,
            was_deferred=request is not None and requires_data_to_resolve(request),
            periods=(),
            resolved_by=None,
        ),
    )


def _absent(cause: FigureCause, particulars: str, resolution: PeriodResolution) -> Execution:
    """A well-founded nothing, stating which nothing it is."""
    return Execution(
        outcome=Absent(reason=f"{cause.value}: {particulars}"),
        resolution=resolution,
        cause=cause,
    )


def _failed(particulars: str, request: PeriodSpec | None) -> Execution:
    """The read model did not answer. Counted as a degradation, never shown as absence.

    ``ADAPTER_UNAVAILABLE`` is the taxonomy's member for an adapter's own typed failure
    converted at the boundary -- which is exactly what a read model that cannot return a
    row is. The kind is deliberately not a new member invented here: the taxonomy is
    closed, and widening it is a reviewable act in the module that owns it.
    """
    return Execution(
        outcome=Failed(
            degradations=(
                degrade(DegradationKind.ADAPTER_UNAVAILABLE, Where.EXECUTE.value, particulars),
            )
        ),
        resolution=PeriodResolution(
            request=request,
            was_deferred=request is not None and requires_data_to_resolve(request),
            periods=(),
            resolved_by=None,
        ),
        cause=FigureCause.LOOKUP_FAILED,
    )


# ------------------------------------------------------------------------- the fetch


def execute_value(question: CompiledQuestion, datapoints: DatapointsPort) -> Execution:
    """Fetch the single figure the compiled question asks for, by exact key.

    The whole of AD-3's "figures originate only in ``execute/``" is this function and the
    port behind it: nothing scores a row, nothing computes a value, and every number
    returned names the datapoint it was read from.
    """
    spec = question.spec
    request = _requested(spec)

    refusal = _unanswerable(question)
    if refusal is not None:
        return _nothing(refusal[0], refusal[1], request)

    detail_id = _bound(spec.detail)
    measure = _bound(spec.measure)
    scope = _bound(spec.country_scope)
    # `_unanswerable` has already refused every state in which one of these is missing;
    # the assertion tells the type checker so, rather than checking a second time.
    assert detail_id is not None and measure is not None and scope is not None
    assert request is not None

    country_id, one_series = _country_of(scope)
    if not one_series:
        return _nothing(
            FigureCause.SCOPE_IS_NOT_ONE_SERIES,
            f"{detail_id}: {type(scope).__name__} selects more than one country, and a "
            "cross-country result is the union of two selections, assembled elsewhere",
            request,
        )

    # The port is the boundary AD-15 allows a broad handler at: everything past it is a
    # value, so a read model that cannot answer arrives as `Failed` rather than as a
    # stack trace -- and never as "this detail has no data".
    try:
        if not datapoints.publishes(detail_id):
            return _nothing(
                FigureCause.DETAIL_PUBLISHES_NOTHING,
                f"{detail_id} publishes no datapoint at any period or country",
                request,
            )
        published = datapoints.periods(detail_id, country_id)
        if not published:
            return _nothing(
                FigureCause.SCOPE_PUBLISHES_NOTHING,
                f"{detail_id} publishes no row in {_scope_name(country_id)}",
                request,
            )
        return _walk(spec, datapoints, detail_id, measure, country_id, published)
    except DatapointsUnavailable as error:
        return _failed(
            f"the read model could not answer for {detail_id} in "
            f"{_scope_name(country_id)}: {type(error).__name__}: {error}",
            request,
        )


def _walk(
    spec: QuerySpec,
    datapoints: DatapointsPort,
    detail_id: str,
    measure: Measure,
    country_id: str | None,
    published: tuple[Period, ...],
) -> Execution:
    """Try the candidate periods in order, fetching each by its exact key."""
    request = _requested(spec)
    assert request is not None
    deferred = requires_data_to_resolve(request)
    wanted = readings_wanted(request)

    readings: list[Reading] = []
    for period in candidate_periods(request, published, spec.today):
        row = datapoints.row(detail_id, period, country_id)
        if row is None:
            continue
        # FR-8's placeholder clause governs the *resolution* of a deferred request: a
        # placeholder row is not the latest reading, so the walk goes on past it. A
        # period the reader named outright is answered as published, absence included.
        if deferred and not _carries_a_reading(row):
            continue
        text = row.cell(measure)
        if text is None or not is_published_text(text):
            if deferred:
                continue
            return _absent(
                FigureCause.MEASURE_NOT_PUBLISHED,
                f"{detail_id} {period} {_scope_name(country_id)}: {measure.value}",
                _resolution(request, deferred, (period,)),
            )
        value = _read(text)
        if value is None:
            # A published value that is not a number. The row is intact and the engine
            # read it correctly: what is absent is a *figure*, which is a fact about the
            # indicator rather than a failure, so the walk stops and says so instead of
            # reaching further back for an older row of the same kind.
            return _absent(
                FigureCause.VALUE_IS_NOT_A_FIGURE,
                f"{detail_id} {period} {_scope_name(country_id)} publishes "
                f"{measure.value}={text!r}, which is not a number",
                _resolution(request, deferred, (period,)),
            )
        readings.append(Reading(period=period, figure=_figure(row, measure, value)))
        if wanted is not None and len(readings) >= wanted:
            break

    return _answer(request, deferred, readings, detail_id, country_id)


def _answer(
    request: PeriodSpec,
    deferred: bool,
    readings: Sequence[Reading],
    detail_id: str,
    country_id: str | None,
) -> Execution:
    """The outcome of a completed walk: the newest reading, or the cause there is none."""
    resolution = _resolution(request, deferred, tuple(found.period for found in readings))
    if readings:
        return Execution(
            outcome=Found(value=readings[0].figure),
            resolution=resolution,
            readings=tuple(readings),
        )
    cause = (
        FigureCause.NO_READING_AT_OR_BEFORE_TODAY
        if deferred
        else FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD
    )
    return _absent(cause, f"{detail_id} in {_scope_name(country_id)}: {request}", resolution)
