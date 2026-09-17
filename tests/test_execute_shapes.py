"""Session L: the execution shapes beyond one figure.

``execute.value`` fetches one figure by exact key and refuses every other operation
before it fetches anything, which left the composers Epics 3, 4 and 5 built with no data
to compose. These are the shapes that feed them, and what is asserted here is the
property each one exists to keep rather than the shape of its fields:

* **AD-3 still holds.** Every figure, in every shape, names the datapoint row it was read
  from. A comparison is a union of exact-key fetches and never a query that ranked; the
  ordering is applied afterwards, over figures that already exist.
* **An absence is stated, not shortened.** A span with a hole in it comes back with the
  readings it found and the hole left for ``series_over`` to state; a union member that
  published nothing stays in the union as a stated absence rather than being dropped from
  the set it is a member of.
* **An unimplemented operation is not a fault.** It is ``question-not-supported``, never
  ``data-could-not-be-reached`` -- the one code that should page someone stays spendable.
* **One common period.** A comparison resolves the period once and reads every member at
  it, so FR-22's common period is a property of the fetch rather than a repair applied to
  it afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.readmodel.startup import engine_for
from askai.adapters.store.provision import Databases, provision
from askai.api.engine import Engine
from askai.compile.binding import (
    Binding,
    BoundBy,
    CompiledQuestion,
    Precedence,
    SpecField,
    UnboundReason,
)
from askai.domain.period import Period
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Deferred,
    Exact,
    LastN,
    Latest,
    Measure,
    Operation,
    PeriodSpec,
    QuerySpec,
    Range,
    Unbound,
    requires_data_to_resolve,
)
from askai.execute.shapes import (
    Coverage,
    Executed,
    PairExecution,
    SpanExecution,
    UnionExecution,
    execute_operation,
)
from askai.execute.value import Execution, FigureCause
from askai.narrate.refusal import RefusalCode, refusal_for
from askai.observability.degradations import Failed, Found
from askai.ports.datapoints import DatapointRow, DatapointsUnavailable

TODAY = date(2026, 9, 15)
DETAIL = "D"

#: The reviewed CMS export the deployed engine is loaded from.
EXPORT_ROOT = Path(__file__).resolve().parent.parent / "data"


# ------------------------------------------------------------------------- the fixtures


class Fake:
    """A ``DatapointsPort`` holding exactly the rows it was given."""

    def __init__(self, *rows: DatapointRow, broken: bool = False) -> None:
        self._rows = rows
        self._broken = broken

    def _check(self) -> None:
        if self._broken:
            raise DatapointsUnavailable("the read model is not answering")

    def publishes(self, detail_id: str) -> bool:
        self._check()
        return any(row.detail_id == detail_id for row in self._rows)

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        self._check()
        return tuple(
            row.period
            for row in self._rows
            if row.detail_id == detail_id and row.country_id == country_id
        )

    def row(self, detail_id: str, period: Period, country_id: str | None) -> DatapointRow | None:
        self._check()
        for row in self._rows:
            if (row.detail_id, row.period, row.country_id) == (detail_id, period, country_id):
                return row
        return None


def a_row(
    period: str,
    actual: str | None = None,
    *,
    detail_id: str = DETAIL,
    country_id: str | None = None,
) -> DatapointRow:
    return DatapointRow(
        detail_id=detail_id,
        period=Period(period),
        country_id=country_id,
        source_datapoint_id=f"{detail_id}:{period}:{country_id}",
        actual=actual,
        target=None,
        baseline=None,
    )


def _bindings(spec: QuerySpec) -> tuple[Binding, ...]:
    made: list[Binding] = []
    for field in SpecField:
        state = getattr(spec, field.value)
        unbound = isinstance(state, Unbound)
        made.append(
            Binding(
                field=field,
                precedence=Precedence.UNBOUND if unbound else Precedence.NAMED_IN_QUESTION,
                bound_by=None if unbound else BoundBy.READER,
            )
        )
    return tuple(made)


def _period_field(request: PeriodSpec) -> Bound[PeriodSpec] | Deferred[PeriodSpec]:
    return (
        Deferred(request=request)
        if requires_data_to_resolve(request)
        else Bound(request)
    )


def a_question(
    period: PeriodSpec | Unbound,
    operation: Operation,
    *,
    detail: str | Unbound = DETAIL,
    scope: CountryScope | None = None,
    measure: Measure = Measure.ACTUAL,
) -> CompiledQuestion:
    spec = QuerySpec(
        detail=detail if isinstance(detail, Unbound) else Bound(detail),
        period=period if isinstance(period, Unbound) else _period_field(period),
        country_scope=Bound(National() if scope is None else scope),
        measure=Bound(measure),
        operation=Bound(operation),
        today=TODAY,
    )
    return CompiledQuestion(spec=spec, bindings=_bindings(spec))


def a_span(start: str = "2019", end: str = "2025") -> Range:
    return Range(start=Period(start), end=Period(end))


def span_of(executed: Executed) -> SpanExecution:
    assert isinstance(executed, SpanExecution), executed
    return executed


def union_of(executed: Executed) -> UnionExecution:
    assert isinstance(executed, UnionExecution), executed
    return executed


# --------------------------------------------------------------------- the value shape


def test_a_value_question_is_still_answered_by_the_function_it_always_was() -> None:
    """The shape Epic 1 shipped is delegated, not reimplemented beside it.

    The whole risk of a dispatching entry point is that the commonest path acquires a
    second implementation that drifts from the first. It does not: ``execute_operation``
    hands a value question straight to ``execute_value``, and what comes back is an
    ``Execution`` carrying the same figure from the same row.
    """
    datapoints = Fake(a_row("2025", "0.54316"))
    executed = execute_operation(
        a_question(Exact(period=Period("2025")), Operation.VALUE), datapoints
    )
    assert isinstance(executed, Execution)
    assert isinstance(executed.outcome, Found)
    figure = executed.figure
    assert figure is not None
    assert figure.value == Decimal("0.54316")
    assert figure.source_datapoint_id == "D:2025:None"


# ---------------------------------------------------------------------- the span shape


def test_a_span_returns_every_reading_it_found_each_from_its_own_row() -> None:
    """FR-16: a series is the readings of the span, and every one names its row (AD-3)."""
    datapoints = Fake(
        a_row("2019", "1.0"), a_row("2020", "2.0"), a_row("2021", "3.0")
    )
    span = span_of(
        execute_operation(
            a_question(a_span("2019", "2021"), Operation.SERIES), datapoints
        )
    )
    assert [reading.period.value for reading in span.readings] == ["2021", "2020", "2019"]
    assert [reading.figure.value for reading in span.readings] == [
        Decimal("3.0"),
        Decimal("2.0"),
        Decimal("1.0"),
    ]
    for reading in span.readings:
        assert reading.figure.source_datapoint_id == f"D:{reading.period.value}:None"
    assert span.cause is None


def test_a_span_leaves_a_hole_where_a_period_published_nothing() -> None:
    """FR-17: the gap is left for the composer to state, never closed up here.

    The readings come back short and the span comes back whole, which is what lets
    ``series_over`` place one against the other and word the missing period. A shape that
    returned only the periods it found would have thrown away the question.
    """
    datapoints = Fake(a_row("2019", "1.0"), a_row("2021", "3.0"))
    span = span_of(
        execute_operation(
            a_question(a_span("2019", "2021"), Operation.SERIES), datapoints
        )
    )
    assert [reading.period.value for reading in span.readings] == ["2021", "2019"]
    assert span.span == a_span("2019", "2021")
    assert span.cause is None, "a hole in a span is a gap to state, not a cause to refuse"


def test_a_span_over_a_detail_that_publishes_words_says_so_rather_than_reporting_a_gap() -> None:
    """21 details publish a rating rather than a number, and a run of those is not a series.

    The distinction has to survive the fetch: an empty run and a run of published words
    reach the composer as different causes, so a present-but-textual indicator is never
    reported as a span of missing data.
    """
    datapoints = Fake(a_row("2019", "Tier 1"), a_row("2020", "Tier 2"))
    span = span_of(
        execute_operation(
            a_question(a_span("2019", "2020"), Operation.SERIES), datapoints
        )
    )
    assert span.cause is FigureCause.VALUE_IS_NOT_A_FIGURE
    assert span.readings == ()


def test_a_span_that_found_nothing_states_which_nothing_it_is() -> None:
    datapoints = Fake(a_row("2010", "1.0"))
    span = span_of(
        execute_operation(
            a_question(a_span("2019", "2021"), Operation.SERIES), datapoints
        )
    )
    assert span.readings == ()
    assert span.cause is FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD


def test_a_series_asked_at_a_single_period_is_refused_rather_than_answered_as_one_point() -> None:
    """AD-1: the request is not reinterpreted into the one this shape can serve."""
    datapoints = Fake(a_row("2025", "1.0"))
    executed = execute_operation(
        a_question(Exact(period=Period("2025")), Operation.SERIES), datapoints
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.OPERATION_IS_NOT_A_VALUE


def test_a_series_over_more_than_one_country_is_refused_as_not_one_series() -> None:
    datapoints = Fake(a_row("2019", "1.0"))
    executed = execute_operation(
        a_question(
            a_span(), Operation.SERIES, scope=Named(countries=frozenset({"SG", "AE"}))
        ),
        datapoints,
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.SCOPE_IS_NOT_ONE_SERIES


# ---------------------------------------------------------------------- the pair shape


def test_a_change_carries_two_readings_and_the_later_row_it_is_selected_from() -> None:
    """AD-4: the published change column is selected off the row, never computed here.

    The row travels with the pair for exactly that reason. A shape that handed the
    composer a subtraction would have made the decision the rules make -- which column
    matches this grain and this basis -- in the layer that cannot read them.
    """
    datapoints = Fake(a_row("2026-03", "2.0"), a_row("2026-04", "3.5"))
    executed = execute_operation(
        a_question(LastN(n=2, grain=Period("2026-04").grain), Operation.CHANGE), datapoints
    )
    assert isinstance(executed, PairExecution)
    assert executed.later is not None and executed.later.period == Period("2026-04")
    assert executed.earlier is not None and executed.earlier.period == Period("2026-03")
    assert executed.later_row is not None
    assert executed.later_row.source_datapoint_id == "D:2026-04:None"


def test_a_change_reads_the_actual_at_each_end_even_when_the_spec_names_the_change() -> None:
    """``Measure.CHANGE`` names a published column, and the two ends are still actuals.

    Fetching the change measure at each end would be asking for the column twice and
    calling the pair a change; the pair is what the change is *measured over*.
    """
    datapoints = Fake(a_row("2026-03", "2.0"), a_row("2026-04", "3.5"))
    executed = execute_operation(
        a_question(
            LastN(n=2, grain=Period("2026-04").grain),
            Operation.CHANGE,
            measure=Measure.CHANGE,
        ),
        datapoints,
    )
    assert isinstance(executed, PairExecution)
    assert executed.later is not None
    assert executed.later.figure.measure is Measure.ACTUAL


def test_a_change_with_nothing_to_measure_against_states_the_missing_half() -> None:
    datapoints = Fake(a_row("2026-04", "3.5"))
    executed = execute_operation(
        a_question(LastN(n=2, grain=Period("2026-04").grain), Operation.CHANGE), datapoints
    )
    assert isinstance(executed, PairExecution)
    assert executed.later is not None
    assert executed.earlier is None, "the absent half is stated, never back-filled"


# --------------------------------------------------------------------- the union shape


def test_a_comparison_is_a_union_of_exact_key_fetches_one_per_covered_country() -> None:
    """AD-3, FR-22: every member is a keyed fetch, and nothing ranked anything."""
    datapoints = Fake(
        a_row("2026-Q1", "2.0"),
        a_row("2026-Q1", "1.0", country_id="SG"),
        a_row("2026-Q1", "4.0", country_id="AE"),
    )
    union = union_of(
        execute_operation(
            a_question(Exact(period=Period("2026-Q1")), Operation.COMPARISON),
            datapoints,
            coverage=Coverage(national=True, codes=("SG", "AE")),
        )
    )
    assert [fetch.country_id for fetch in union.fetches] == [None, "SG", "AE"]
    assert [figure.value for figure in union.figures] == [
        Decimal("2.0"),
        Decimal("1.0"),
        Decimal("4.0"),
    ]
    for figure in union.figures:
        assert figure.source_datapoint_id.startswith("D:2026-Q1:")


def test_a_country_that_published_nothing_stays_in_the_union_as_a_stated_absence() -> None:
    """A member dropped from the set it belongs to is a comparison silently narrowed.

    FR-110's half of F-001: the reader named a country, and what they get back says what
    happened to it. An absent member that vanished would leave a two-country answer to a
    three-country question, reading exactly like a complete one.
    """
    datapoints = Fake(a_row("2026-Q1", "2.0"), a_row("2026-Q1", "1.0", country_id="SG"))
    union = union_of(
        execute_operation(
            a_question(Exact(period=Period("2026-Q1")), Operation.COMPARISON),
            datapoints,
            coverage=Coverage(national=True, codes=("SG", "AE")),
        )
    )
    assert len(union.fetches) == 3
    absent = union.fetches[2]
    assert absent.country_id == "AE"
    assert absent.figure is None
    assert absent.cause is FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD


def test_every_member_of_a_comparison_is_read_at_one_common_period() -> None:
    """FR-22: the period resolves once, and no member is read at its own latest.

    Singapore's newest row here is a quarter ahead of the home series'. A per-country
    "latest" would line those two up and call it a comparison; the union reads both at
    the one period the request resolved to.
    """
    datapoints = Fake(
        a_row("2026-Q1", "2.0"),
        a_row("2026-Q1", "1.0", country_id="SG"),
        a_row("2026-Q2", "9.9", country_id="SG"),
    )
    union = union_of(
        execute_operation(
            a_question(Latest(), Operation.COMPARISON),
            datapoints,
            coverage=Coverage(national=True, codes=("SG",)),
        )
    )
    assert union.period == Period("2026-Q1")
    assert {figure.period for figure in union.figures} == {Period("2026-Q1")}
    assert Decimal("9.9") not in [figure.value for figure in union.figures]


def test_a_comparison_nobody_decided_the_coverage_of_is_refused_not_guessed() -> None:
    """The selection is a published-rule decision and is made above this layer.

    Fetching a set this module chose for itself would be FR-9's prohibition broken in the
    one place that cannot read the rule: naming a country filters the declared benchmark
    set and never widens it, and a union assembled here would have nothing to filter
    against. F-001 is a two-country question that returned six.
    """
    datapoints = Fake(a_row("2026-Q1", "2.0"))
    executed = execute_operation(
        a_question(Exact(period=Period("2026-Q1")), Operation.COMPARISON),
        datapoints,
        coverage=None,
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.SCOPE_IS_NOT_ONE_SERIES


def test_a_coverage_cannot_name_one_country_twice() -> None:
    with pytest.raises(ValueError, match="names each country once"):
        Coverage(codes=("SG", "SG"))


# ------------------------------------------- an operation with no shape is not a fault


@pytest.mark.parametrize(
    "operation",
    [Operation.LIST, Operation.COUNT, Operation.EXPLANATION, Operation.DEFINITION],
)
def test_an_operation_with_no_execution_is_unsupported_and_never_a_failure(
    operation: Operation,
) -> None:
    """The sixth refusal means *a fault in the engine* and is the one that should page.

    Spending it on a feature nobody has built makes it useless as a signal: an operator
    watching that rate would see a reader asking for a definition and a read model that
    had fallen over as the same event. An unimplemented operation is cause five.
    """
    datapoints = Fake(a_row("2025", "1.0"))
    executed = execute_operation(
        a_question(Exact(period=Period("2025")), operation), datapoints
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.OPERATION_IS_NOT_A_VALUE
    assert refusal_for(executed.cause) is RefusalCode.QUESTION_NOT_SUPPORTED


@pytest.mark.parametrize(
    "operation", [Operation.SERIES, Operation.CHANGE, Operation.COMPARISON]
)
def test_an_unbound_field_is_never_repaired_by_any_shape(operation: Operation) -> None:
    """AD-1: ``compile/`` has the last word on every field, in every shape."""
    datapoints = Fake(a_row("2025", "1.0"))
    executed = execute_operation(
        a_question(
            a_span(),
            operation,
            detail=Unbound(reason=UnboundReason.NO_DETAIL_NAMED),
        ),
        datapoints,
        coverage=Coverage(national=True),
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.DETAIL_NOT_BOUND


# ------------------------------------------------- a read model that will not answer


@pytest.mark.parametrize(
    "operation", [Operation.SERIES, Operation.CHANGE, Operation.COMPARISON]
)
def test_a_dead_read_model_is_a_failure_in_every_shape_and_never_an_absence(
    operation: Operation,
) -> None:
    """AD-15: the adapter not working is never worded as "nothing is published".

    Asserted for each shape rather than for one, because the handler is per-shape and a
    shape that forgot it would report an outage as a data gap -- findings 23, 128 and 150,
    which is the failure the closed ``Outcome`` exists to make unrepresentable.
    """
    executed = execute_operation(
        a_question(a_span(), operation),
        Fake(broken=True),
        coverage=Coverage(national=True),
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.LOOKUP_FAILED
    assert isinstance(executed.outcome, Failed)
    assert executed.degradations != ()
    assert refusal_for(executed.cause) is RefusalCode.DATA_COULD_NOT_BE_REACHED


# --------------------------------------------------------------- the shapes agree on
# --------------------------------------------------------------- the three questions


@pytest.mark.parametrize(
    ("operation", "coverage"),
    [
        (Operation.VALUE, None),
        (Operation.SERIES, None),
        (Operation.CHANGE, None),
        (Operation.COMPARISON, Coverage(national=True, codes=("SG",))),
    ],
)
def test_every_shape_answers_the_same_three_questions(
    operation: Operation, coverage: Coverage | None
) -> None:
    """Is there a figure, what did the period resolve to, what degraded.

    The property that lets one composition path read any shape. A member that answered
    two of the three would force a branch at every call site, which is the per-operation
    ladder the dispatching entry point exists to avoid.
    """
    datapoints = Fake(
        a_row("2019", "1.0"),
        a_row("2025", "2.0"),
        a_row("2025", "3.0", country_id="SG"),
    )
    executed = execute_operation(
        a_question(a_span("2019", "2025"), operation), datapoints, coverage=coverage
    )
    assert hasattr(executed, "figure")
    assert executed.resolution is not None
    assert isinstance(executed.degradations, tuple)


def test_the_declared_benchmark_scope_is_not_a_single_series() -> None:
    """A scope that selects a set is not answered by fetching one row from it."""
    datapoints = Fake(a_row("2019", "1.0"))
    executed = execute_operation(
        a_question(a_span(), Operation.SERIES, scope=DeclaredBenchmarks()), datapoints
    )
    assert isinstance(executed, Execution)
    assert executed.cause is FigureCause.SCOPE_IS_NOT_ONE_SERIES


# ------------------------------------------- the admission the deployed engine runs


@pytest.fixture(scope="module")
def databases() -> Iterator[Databases]:
    with provision() as estate:
        ingest_published_layer(estate.read_model, CmsExport.rooted(EXPORT_ROOT))
        yield estate


@pytest.fixture(scope="module")
def deployed(databases: Databases, tmp_path_factory: pytest.TempPathFactory) -> Engine:
    return engine_for(databases, tmp_path_factory.mktemp("estate") / "refresh_state.json")


def test_the_deployed_engine_admits_a_catalogue_reference_and_not_only_a_datapoint(
    databases: Databases, deployed: Engine
) -> None:
    """The defect behind *"What does inflation mean?"* answering ``data-could-not-be-reached``.

    An answer carries two shapes of reference. A figure names
    ``detail|period|country|source``; a quoted definition, a group's count and a
    capability statement name ``catalogue|kind|key``. The engine was wired with the
    datapoint resolver alone, so every catalogue element failed AD-7's admission, every
    element of a definition answer was refused, and ``narrate.structured`` reported the
    empty result as the sixth refusal -- *a fault in the engine* -- for a composer that
    had worked perfectly.

    That is the one code that should page someone, and this is what keeps it spendable:
    the admission the **deployed** engine runs has to cover what the composers actually
    build. Asserting it on ``engine_for`` rather than on the port is the whole point --
    ``EitherSource`` was built, tested, and simply never reached a deployment.
    """
    row = databases.read_model.execute("SELECT detail_id FROM detail LIMIT 1").fetchone()
    assert row is not None, "the loaded export publishes at least one detail"
    detail_id = str(row[0])

    sources = deployed.sources
    assert sources.resolves(f"catalogue:detail:{detail_id}") is True
    assert sources.resolves("catalogue:catalogue:catalogue") is True
    assert sources.resolves("catalogue:detail:no-such-detail") is False
    assert sources.resolves("catalogue:no-such-kind:anything") is False
