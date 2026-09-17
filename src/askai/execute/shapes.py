"""The execution shapes beyond one figure: a span, a pair, and a union.

Purity: IO, via ports only.

Session L. ``execute.value`` produces exactly one shape -- one figure by exact key -- and
refuses every operation that is not ``value`` before it fetches anything. Epics 3, 4 and 5
built the composers that answer the other ten operations and left them unreachable, not
because the composers are wrong but because nothing produced the data they take. This is
that data.

**AD-3 holds without exception.** Every figure here still comes out of
``execute.value.walk_readings``, which fetches by exact key on ``(detail, period,
country)``. Nothing in this module scores a row, computes a value, or invents a period:

- a **span** is the readings a ``Range`` resolves to, each one a keyed fetch, with the
  periods that published nothing left out rather than filled in -- ``assemble.change.
  series.series_over`` is what turns the gaps into stated gaps, and it needs the readings
  to do it;
- a **pair** is two keyed fetches at two periods, and the later row travels with them so
  that ``assemble.change.selection`` can select the *published* change column off it.
  AD-4's "selected, never computed" is why the row is carried and not a subtraction;
- a **union** is one keyed fetch per selected country, run one country at a time. It is
  emphatically **not** a query that ranks: the ordering an extremum needs is applied by
  ``assemble.compare.extrema`` over figures that already exist, and the alternative --
  asking the store for the lowest -- would be a figure originating outside ``execute/``.

**Who decides what to fetch is not this module.** ``assemble.compare.selection.select``
decides which countries a cross-country answer covers, and ``assemble/`` sits *above*
``execute/`` in the layer contract, so it cannot be called from here. The caller computes
the selection and passes it in as ``Coverage``. That is the layering working rather than
being worked around: the selection is a published-rule decision, the fetch is an IO one,
and this module does the second.

**Every shape states its own absence.** A union whose countries all published nothing is
not an empty tuple, and a span with no readings is not a short one: each carries a
``FigureCause`` for the same reason ``Execution`` does, so ``narrate/`` is never handed a
shape whose emptiness it has to interpret.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.compile.binding import CompiledQuestion, SpecField
from askai.domain.degradation import Degradation
from askai.domain.period import Period
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Exact,
    FieldState,
    Measure,
    Operation,
    PeriodSpec,
    QuerySpec,
    Range,
    Unbound,
    requires_data_to_resolve,
)
from askai.execute.latest import readings_wanted
from askai.execute.value import (
    Execution,
    Figure,
    FigureCause,
    PeriodResolution,
    Reading,
    execute_value,
    failed_execution,
    nothing_executed,
    resolution_of,
    walk_readings,
)
from askai.observability.degradations import Absent, Found, Outcome
from askai.ports.datapoints import DatapointRow, DatapointsPort, DatapointsUnavailable

__all__ = [
    "CountryFetch",
    "Coverage",
    "Executed",
    "PairExecution",
    "SpanExecution",
    "UnionExecution",
    "execute_operation",
    "operation_of",
]


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which series a cross-country execution fetches, decided above this layer.

    ``national`` is a flag and not a country id, because national scope is the *absence*
    of a country (AD-5): there is no code to put in ``codes`` for it and nowhere here for
    one to be invented. ``codes`` is ordered so that two executions of the same coverage
    fetch in the same order and produce the same union, which is what makes an answer
    reproducible from the record (AD-17).
    """

    national: bool = False
    codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.codes)) != len(self.codes):
            raise ValueError(
                "a coverage names each country once; a repeated code would fetch one "
                "series twice and show it twice in the comparison it is a member of"
            )

    @property
    def covered(self) -> int:
        """How many series this fetches, the national one included."""
        return len(self.codes) + int(self.national)


@dataclass(frozen=True, slots=True)
class CountryFetch:
    """One member of a union: the series asked for, and what the exact-key fetch found.

    ``country_id`` is ``None`` for the national half. ``outcome`` is the same closed
    three-state the single-figure path returns, so a country that published nothing is a
    stated absence that stays *in* the union rather than a member quietly dropped from it
    -- which is what ``assemble.compare.readings.CountryReading`` is built to say.
    """

    country_id: str | None
    outcome: Outcome[Figure]
    cause: FigureCause | None = None

    def __post_init__(self) -> None:
        if isinstance(self.outcome, Found) is not (self.cause is None):
            raise ValueError(
                f"a {type(self.outcome).__name__} fetch carrying cause {self.cause}; a "
                "figure has no cause and anything else states one"
            )

    @property
    def figure(self) -> Figure | None:
        return self.outcome.value if isinstance(self.outcome, Found) else None


@dataclass(frozen=True, slots=True)
class SpanExecution:
    """The readings a named span resolved to, newest first, gaps left out.

    Left out rather than filled with a blank: ``assemble.change.series.series_over`` is
    handed the span *and* the readings and places one against the other, so a period that
    published nothing becomes a stated gap there, in the layer that has the catalogue to
    word it. A ``None`` in a tuple here would be the same gap with nothing to say about
    it.
    """

    detail_id: str
    span: Range
    country_id: str | None
    readings: tuple[Reading, ...]
    resolution: PeriodResolution
    cause: FigureCause | None = None
    degradations: tuple[Degradation, ...] = ()

    @property
    def figure(self) -> Figure | None:
        """The newest reading's figure, for the record and for a caller that wants one."""
        return self.readings[0].figure if self.readings else None


@dataclass(frozen=True, slots=True)
class PairExecution:
    """Two readings and the later row, for a change that is selected and never computed.

    ``later_row`` is the whole ``DatapointRow`` and not a value off it, because AD-4 says
    a change is *selected from the published column matching the grain and the basis* --
    which column that is, is ``assemble.change.selection``'s decision, read from the
    rules. Handing it a number chosen here would be this module making that decision.

    ``earlier`` is ``None`` when the paired period publishes nothing; the composer states
    that rather than falling back to a subtraction.
    """

    detail_id: str
    country_id: str | None
    later: Reading | None
    earlier: Reading | None
    later_row: DatapointRow | None
    resolution: PeriodResolution
    cause: FigureCause | None = None
    degradations: tuple[Degradation, ...] = ()

    @property
    def figure(self) -> Figure | None:
        return None if self.later is None else self.later.figure


@dataclass(frozen=True, slots=True)
class UnionExecution:
    """One keyed fetch per covered country, and never a query that ranked them.

    The period is resolved **once**, against the national calendar where the coverage
    includes it and against the first covered country's otherwise, and every member is
    then fetched at that one period. FR-22's common period is that single resolution: a
    per-country "latest" would line up readings from different periods and call them a
    comparison, which ``assemble.compare.readings.at_period`` exists to undo and which is
    better not to produce.
    """

    detail_id: str
    period: Period | None
    fetches: tuple[CountryFetch, ...]
    resolution: PeriodResolution
    cause: FigureCause | None = None
    degradations: tuple[Degradation, ...] = ()

    @property
    def figures(self) -> tuple[Figure, ...]:
        """Every member that published, in coverage order. The rest stay in ``fetches``."""
        return tuple(
            fetch.figure for fetch in self.fetches if fetch.figure is not None
        )

    @property
    def figure(self) -> Figure | None:
        """The first member that published.

        Present so that every ``Executed`` answers the same three questions -- is there a
        figure, what did the period resolve to, what degraded -- and a caller composing
        one shape cannot reach for a field another shape does not have. It is **not** the
        answer to a comparison: the answer is the union, and a caller that shows only this
        has shown one country and called it a comparison.
        """
        figures = self.figures
        return figures[0] if figures else None


#: What one question executes to. Closed, and closed for the reason ``Outcome`` is: a
#: caller that composes the value shape and forgets the span does not type-check, which
#: is the foreclosure rather than a convention about which branches to remember.
type Executed = Execution | SpanExecution | PairExecution | UnionExecution


def operation_of(state: FieldState[Operation]) -> Operation | None:
    """The bound operation, or ``None``. Never repaired and never defaulted (AD-1)."""
    return state.value if isinstance(state, Bound) else None


def _bound[T](state: FieldState[T]) -> T | None:
    return state.value if isinstance(state, Bound) else None


def _requested(spec: QuerySpec) -> PeriodSpec | None:
    match spec.period:
        case Bound(value=request):
            return request
        case Unbound():
            return None
        case _:
            return spec.period.request


def _one_country(scope: CountryScope) -> tuple[str | None, bool]:
    """The country id a single-series shape fetches by, and whether this scope is one."""
    match scope:
        case National():
            return None, True
        case DeclaredBenchmarks():
            return None, False
        case Named(countries=countries):
            if len(countries) == 1:
                return next(iter(countries)), True
            return None, False


def execute_operation(
    question: CompiledQuestion,
    datapoints: DatapointsPort,
    coverage: Coverage | None = None,
) -> Executed:
    """Execute *question* in the shape its bound operation asks for.

    One path, parameterised by the closed ``Operation`` -- not a ladder of per-operation
    entry points with their own guards to keep agreeing. ``value`` is delegated to
    ``execute_value`` unchanged, so the shape Epic 1 shipped is produced by the same
    function it has always been produced by and this module cannot drift from it.

    An operation with no execution shape is returned as the single-figure path's own
    refusal, carrying ``OPERATION_IS_NOT_A_VALUE`` -- which is *"this engine does not
    perform that query"* and is said to a reader as ``question-not-supported``. It is
    never a failure: an unimplemented operation is not the read model breaking, and
    spending the one code that should page someone on it makes that code useless.
    """
    operation = operation_of(question.spec.operation)
    if operation is None or operation is Operation.VALUE:
        return execute_value(question, datapoints)
    match operation:
        case Operation.SERIES:
            return _span(question, datapoints)
        case Operation.CHANGE:
            return _pair(question, datapoints)
        case Operation.COMPARISON | Operation.EXTREMUM | Operation.RANK | Operation.SPREAD:
            return _union(question, datapoints, coverage)
        case _:
            # definition, list, count and explanation need no figure at all; they are
            # composed from the catalogue, and the router above decides that. The value
            # path's refusal is what a caller that asks for a figure anyway gets.
            return execute_value(question, datapoints)


def _unready(question: CompiledQuestion) -> tuple[FigureCause, str] | None:
    """The states in which there is nothing to fetch, whatever shape was asked for."""
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
    return None


# ------------------------------------------------------------------------- the span


def _span(question: CompiledQuestion, datapoints: DatapointsPort) -> Executed:
    """Every reading of a named span, each fetched by exact key (FR-16, FR-17)."""
    spec = question.spec
    request = _requested(spec)
    unready = _unready(question)
    if unready is not None:
        return nothing_executed(unready[0], unready[1], request)
    detail_id = _bound(spec.detail)
    measure = _bound(spec.measure)
    scope = _bound(spec.country_scope)
    assert detail_id is not None and measure is not None and scope is not None
    assert request is not None

    if not isinstance(request, Range):
        # A series is over a span. A question binding `series` at a single period asked
        # for one reading, and answering it with a one-point series would be this layer
        # deciding the request meant something else (AD-1).
        return nothing_executed(
            FigureCause.OPERATION_IS_NOT_A_VALUE,
            f"{detail_id}: a series runs over a named span and this question bound "
            f"{type(request).__name__}, which asks for no span",
            request,
        )
    country_id, one_series = _one_country(scope)
    if not one_series:
        return nothing_executed(
            FigureCause.SCOPE_IS_NOT_ONE_SERIES,
            f"{detail_id}: a series runs over one series, and {type(scope).__name__} "
            "selects more than one country",
            request,
        )

    try:
        if not datapoints.publishes(detail_id):
            return nothing_executed(
                FigureCause.DETAIL_PUBLISHES_NOTHING,
                f"{detail_id} publishes no datapoint at any period or country",
                request,
            )
        published = datapoints.periods(detail_id, country_id)
        if not published:
            return nothing_executed(
                FigureCause.SCOPE_PUBLISHES_NOTHING,
                f"{detail_id} publishes no row in this country scope",
                request,
            )
        walk = walk_readings(
            request, datapoints, detail_id, measure, country_id, published, spec.today, None
        )
    except DatapointsUnavailable as error:
        return failed_execution(
            f"the read model could not answer the span for {detail_id}: "
            f"{type(error).__name__}: {error}",
            request,
        )
    readings = walk.readings
    # The walk's own stop is carried rather than returned in place of the span. A run
    # that stopped because the detail publishes a rating rather than a number is *not a
    # series*, and the composer says so from the catalogue -- but only if it is handed
    # the span and the cause. Returning the single-figure refusal here instead would
    # lose which of the two nothings this is.
    stopped = None if walk.stopped is None else walk.stopped.cause
    cause = stopped if stopped is not None else None
    if cause is None and not readings:
        cause = FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD
    return SpanExecution(
        detail_id=detail_id,
        span=request,
        country_id=country_id,
        readings=readings,
        resolution=resolution_of(request, tuple(one.period for one in readings)),
        cause=cause,
    )


# ------------------------------------------------------------------------- the pair


def _pair(question: CompiledQuestion, datapoints: DatapointsPort) -> Executed:
    """The later reading, its row, and the reading the change is measured against (AD-4).

    The earlier period is **not** chosen here. ``assemble.change.selection.paired_with``
    reads the basis off the published rules and says which period pairs with the later
    one; this fetches the two the spec already determines and hands the row over so that
    the pairing and the column selection stay in the layer that reads the rules.
    """
    spec = question.spec
    request = _requested(spec)
    unready = _unready(question)
    if unready is not None:
        return nothing_executed(unready[0], unready[1], request)
    detail_id = _bound(spec.detail)
    measure = _bound(spec.measure)
    scope = _bound(spec.country_scope)
    assert detail_id is not None and measure is not None and scope is not None
    assert request is not None

    country_id, one_series = _one_country(scope)
    if not one_series:
        return nothing_executed(
            FigureCause.SCOPE_IS_NOT_ONE_SERIES,
            f"{detail_id}: a change is over one series, and {type(scope).__name__} "
            "selects more than one country",
            request,
        )
    # A change reads the actual at each end. `Measure.CHANGE` names the published change
    # column, which is selected from the later row rather than fetched as a measure --
    # so the two readings are of the actual whatever the spec's measure says.
    reading_measure = Measure.ACTUAL if measure is Measure.CHANGE else measure

    try:
        if not datapoints.publishes(detail_id):
            return nothing_executed(
                FigureCause.DETAIL_PUBLISHES_NOTHING,
                f"{detail_id} publishes no datapoint at any period or country",
                request,
            )
        published = datapoints.periods(detail_id, country_id)
        if not published:
            return nothing_executed(
                FigureCause.SCOPE_PUBLISHES_NOTHING,
                f"{detail_id} publishes no row in this country scope",
                request,
            )
        walk = walk_readings(
            request,
            datapoints,
            detail_id,
            reading_measure,
            country_id,
            published,
            spec.today,
            readings_wanted(request),
        )
        later = walk.readings[0] if walk.readings else None
        earlier = walk.readings[1] if len(walk.readings) > 1 else None
        later_row = (
            None
            if later is None
            else datapoints.row(detail_id, later.period, country_id)
        )
    except DatapointsUnavailable as error:
        return failed_execution(
            f"the read model could not answer the change for {detail_id}: "
            f"{type(error).__name__}: {error}",
            request,
        )
    if later is None:
        return walk.stopped if walk.stopped is not None else nothing_executed(
            FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD,
            f"{detail_id}: nothing published at the period the change is asked at",
            request,
        )
    return PairExecution(
        detail_id=detail_id,
        country_id=country_id,
        later=later,
        earlier=earlier,
        later_row=later_row,
        resolution=resolution_of(request, tuple(one.period for one in walk.readings)),
    )


# ------------------------------------------------------------------------ the union


def _union(
    question: CompiledQuestion,
    datapoints: DatapointsPort,
    coverage: Coverage | None,
) -> Executed:
    """One exact-key fetch per covered country, at one common period (FR-22).

    A comparison is a **union of selections**, never a widened filter and never a ranking
    query. What ranks the result is ``assemble.compare.extrema``, over figures that
    already exist; what this produces is the figures.
    """
    spec = question.spec
    request = _requested(spec)
    unready = _unready(question)
    if unready is not None:
        return nothing_executed(unready[0], unready[1], request)
    detail_id = _bound(spec.detail)
    measure = _bound(spec.measure)
    assert detail_id is not None and measure is not None
    assert request is not None

    if coverage is None or coverage.covered == 0:
        return nothing_executed(
            FigureCause.SCOPE_IS_NOT_ONE_SERIES,
            f"{detail_id}: nothing decided which countries this comparison covers, and "
            "a union with no members is not a comparison",
            request,
        )

    try:
        if not datapoints.publishes(detail_id):
            return nothing_executed(
                FigureCause.DETAIL_PUBLISHES_NOTHING,
                f"{detail_id} publishes no datapoint at any period or country",
                request,
            )
        period = _common_period(
            spec, request, datapoints, detail_id, measure, coverage
        )
        if period is None:
            return nothing_executed(
                FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD,
                f"{detail_id}: no period is published across the countries this "
                "comparison covers, so there is no common period to line them up at",
                request,
            )
        fetches = tuple(
            _member(datapoints, detail_id, measure, country_id, period)
            for country_id in _members(coverage)
        )
    except DatapointsUnavailable as error:
        return failed_execution(
            f"the read model could not answer the comparison for {detail_id}: "
            f"{type(error).__name__}: {error}",
            request,
        )
    published = tuple(fetch for fetch in fetches if fetch.figure is not None)
    return UnionExecution(
        detail_id=detail_id,
        period=period,
        fetches=fetches,
        resolution=resolution_of(request, (period,)),
        cause=None if published else FigureCause.SCOPE_PUBLISHES_NOTHING,
    )


def _members(coverage: Coverage) -> tuple[str | None, ...]:
    """The country ids to fetch, national first. ``None`` is the national half (AD-5)."""
    national: tuple[str | None, ...] = (None,) if coverage.national else ()
    return (*national, *coverage.codes)


def _common_period(
    spec: QuerySpec,
    request: PeriodSpec,
    datapoints: DatapointsPort,
    detail_id: str,
    measure: Measure,
    coverage: Coverage,
) -> Period | None:
    """The one period every member is read at.

    A named period is that period, and nothing resolves. A deferred one resolves against
    the **first covered series' own calendar** and is then applied to every member, so
    the comparison states one period rather than one per country. A country with no row
    there is a stated absence, which is the honest answer to *"compare these at the
    latest"* when one of them has not published yet.
    """
    if isinstance(request, Exact):
        return request.period
    if not requires_data_to_resolve(request):
        return None
    for country_id in _members(coverage):
        published = datapoints.periods(detail_id, country_id)
        if not published:
            continue
        walk = walk_readings(
            request, datapoints, detail_id, measure, country_id, published, spec.today, 1
        )
        if walk.readings:
            return walk.readings[0].period
    return None


def _member(
    datapoints: DatapointsPort,
    detail_id: str,
    measure: Measure,
    country_id: str | None,
    period: Period,
) -> CountryFetch:
    """One member of the union, fetched by exact key and stated either way."""
    try:
        row = datapoints.row(detail_id, period, country_id)
    except DatapointsUnavailable as error:
        return CountryFetch(
            country_id=country_id,
            outcome=Absent(reason=f"{FigureCause.LOOKUP_FAILED.value}: {error}"),
            cause=FigureCause.LOOKUP_FAILED,
        )
    if row is None:
        return CountryFetch(
            country_id=country_id,
            outcome=Absent(
                reason=(
                    f"{FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD.value}: {detail_id} at "
                    f"{period.value}"
                )
            ),
            cause=FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD,
        )
    walk = walk_readings(
        Exact(period=period),
        datapoints,
        detail_id,
        measure,
        country_id,
        (period,),
        period.end,
        1,
    )
    if not walk.readings:
        cause = FigureCause.MEASURE_NOT_PUBLISHED
        if walk.stopped is not None and walk.stopped.cause is not None:
            cause = walk.stopped.cause
        return CountryFetch(
            country_id=country_id,
            outcome=Absent(reason=f"{cause.value}: {detail_id} at {period.value}"),
            cause=cause,
        )
    return CountryFetch(
        country_id=country_id, outcome=Found(value=walk.readings[0].figure)
    )
