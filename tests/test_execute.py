"""Story 1.12: "latest" resolved against the data, and the figure fetched by exact key.

Asserted against the **real export** in ``data/``, ingested into the databases the schema
step actually builds. The counts in the story are measurements, so a disagreement here is
evidence about the data rather than an expectation to relax.

``today`` is pinned to 2026-09-30 throughout. FR-8 is a statement about a boundary, so a
test that read the clock would assert a different fact every day and would go green on
the day the boundary moved past the defect. 2026-09-30 is the date the data contract
measured its counts against -- *"322 datapoints have a period ending after 2026-09"*.

Everything runs in memory: no database service, no export service, no model, and -- for
the tests that say so -- no socket at all (NFR-6, AD-9a).
"""

from __future__ import annotations

import ast
import csv
import socket
import sqlite3
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import IngestReport, ingest_published_layer
from askai.adapters.store.provision import TABLE_OWNERS, Databases, provision
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import (
    Binding,
    BoundBy,
    CompiledQuestion,
    Precedence,
    SpecField,
)
from askai.compile.catalogue import CatalogueDetail, snapshot
from askai.domain.period import Grain, Period
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
    Unbound,
    period_field,
)
from askai.domain.text import is_published_text
from askai.execute.latest import (
    Boundary,
    Clause,
    FetchRule,
    candidate_periods,
    future_rows_are_eligible,
    has_happened,
    latest_measure,
    newest_first,
    placeholder_rows_are_eligible,
    readings_wanted,
    tie_goes_coarser,
)
from askai.execute.readmodel import ReadModelDatapoints, UnreadablePeriod
from askai.execute.value import (
    Execution,
    Figure,
    FigureCause,
    PeriodResolution,
    execute_value,
)
from askai.observability.degradations import (
    Absent,
    DegradationKind,
    Failed,
    Found,
    classify,
)
from askai.ports.datapoints import (
    DatapointRow,
    DatapointsPort,
    DatapointsUnavailable,
    UnpublishedMeasure,
)
from askai.rules import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXECUTE_ROOT: Final = PACKAGE_ROOT / "execute"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: The date FR-8 is measured against. See the module docstring.
TODAY: Final = date(2026, 9, 30)

# The story's measured facts, restated from the export itself. A number here that has to
# change is a number a reviewer sees changing.
DATAPOINTS: Final = 8_127
NATIONAL_ROWS: Final = 5_263
COUNTRY_BEARING_ROWS: Final = 2_864
FUTURE_DATED_ROWS: Final = 322
FUTURE_DATED_ACTUALS: Final = 42
DETAILS_WITH_NO_DATAPOINTS: Final = 28

# Measured here, and the reason this story exists: on this export, "the most recent row"
# and "the most recent actual at or before today" are different answers for 78 of the
# details that produce a national figure at all.
NEWEST_ROW_IS_NOT_THE_ANSWER: Final = 78
#: Details whose newest *eligible* national row publishes no actual, so the walk goes on.
PLACEHOLDER_SKIPPED: Final = 20
#: Details that publish nationally and have no actual at or before today at all.
NO_NATIONAL_READING: Final = 12
#: Rows whose published ``Actual`` is text rather than a number -- a rating, a tier, a
#: band, published as ``{"en": ..., "ar": ...}``. Found in this story; see the report.
NON_NUMERIC_ACTUALS: Final = 126
NON_NUMERIC_DETAILS: Final = 21

#: One detail is named exactly this in the whole catalogue (DATA-CONTRACT FACT 6).
INFLATION: Final = "Inflation"


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def export() -> CmsExport:
    return CmsExport.rooted(EXPORT_ROOT)


@pytest.fixture(scope="module")
def ingested(export: CmsExport) -> Iterator[tuple[Databases, IngestReport]]:
    with provision() as databases:
        report = ingest_published_layer(databases.read_model, export)
        yield databases, report


@pytest.fixture(scope="module")
def read_model(ingested: tuple[Databases, IngestReport]) -> sqlite3.Connection:
    return ingested[0].read_model


@pytest.fixture(scope="module")
def datapoints(read_model: sqlite3.Connection) -> ReadModelDatapoints:
    return ReadModelDatapoints(read_model)


@pytest.fixture(scope="module")
def report(ingested: tuple[Databases, IngestReport]) -> IngestReport:
    return ingested[1]


# ---------------------------------------------------------------------------- helpers


def _bindings(spec: QuerySpec) -> tuple[Binding, ...]:
    """One binder per field, agreeing with the state the spec carries."""
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


def a_question(
    detail: str | Unbound,
    period: PeriodSpec | Unbound,
    *,
    scope: CountryScope | None = None,
    measure: Measure = Measure.ACTUAL,
    operation: Operation = Operation.VALUE,
    today: date = TODAY,
) -> CompiledQuestion:
    """A compiled question in whatever state a binder could legitimately have left it.

    Built directly rather than through ``compile_question`` so that a state the English
    corpus does not happen to produce -- a named country set of three, an unbound detail
    -- can still be put in front of the fetch.
    """
    spec = QuerySpec(
        detail=detail if isinstance(detail, Unbound) else Bound(detail),
        period=period if isinstance(period, Unbound) else period_field(period),
        country_scope=Bound(National() if scope is None else scope),
        measure=Bound(measure),
        operation=Bound(operation),
        today=today,
    )
    return CompiledQuestion(spec=spec, bindings=_bindings(spec))


def a_detail(connection: sqlite3.Connection, name: str) -> str:
    row = connection.execute("SELECT detail_id FROM detail WHERE name_en = ?", (name,)).fetchone()
    assert row is not None, f"no detail named {name!r}"
    return str(row[0])


def every_detail(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute("SELECT detail_id FROM detail ORDER BY detail_id")
    )


def figure_of(execution: Execution) -> Figure:
    assert isinstance(execution.outcome, Found), execution.outcome
    figure = execution.figure
    assert figure is not None
    return figure


def cause_of(execution: Execution) -> FigureCause | None:
    return execution.cause


class Fake:
    """A ``DatapointsPort`` holding exactly the rows it was given.

    For the cases the real export does not contain -- a year and its own December both
    carrying a reading, a store that will not answer. Everything the export *does*
    contain is asserted against the export.
    """

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
    detail_id: str = "D",
    country_id: str | None = None,
    target: str | None = None,
) -> DatapointRow:
    return DatapointRow(
        detail_id=detail_id,
        period=Period(period),
        country_id=country_id,
        source_datapoint_id=f"{detail_id}:{period}:{country_id}",
        actual=actual,
        target=target,
        baseline=None,
    )


def _modules(root: Path) -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(root.rglob("*.py"))
    ]


def _is_future(period: str) -> bool:
    return not has_happened(Period(period), TODAY)


# ------------------------------------------------- the export, as this story measures it


def test_the_export_is_the_one_the_story_was_written_against(report: IngestReport) -> None:
    assert report.datapoints == DATAPOINTS
    assert report.national_rows == NATIONAL_ROWS
    assert report.country_rows == COUNTRY_BEARING_ROWS


def test_the_future_dated_rows_are_there_to_be_excluded(read_model: sqlite3.Connection) -> None:
    """FACT 5, measured rather than quoted: 322 rows end after today, 42 carry an Actual.

    The 42 are the whole reason FR-8 is a requirement. Most of them are zero -- the QC
    sheet's own known item, *"2029 zeros for Import/Export Time are a known client-data
    issue"* -- so a naive "the newest row" answers a briefing with a placeholder.
    """
    rows = read_model.execute("SELECT period, actual FROM datapoint").fetchall()
    future = [(Period(str(period)), actual) for period, actual in rows if _is_future(str(period))]
    assert len(future) == FUTURE_DATED_ROWS
    assert sum(1 for _, actual in future if is_published_text(actual)) == FUTURE_DATED_ACTUALS
    assert [actual for _, actual in future if actual == "0"], "most of them are zero"


def test_the_future_rows_cannot_be_found_by_comparing_period_strings(
    read_model: sqlite3.Connection,
) -> None:
    """Why the comparison is by calendar and not by spelling.

    ``'2026' < '2026-09'`` as text, so a string comparison calls the 60 yearly rows for
    2026 "past" -- and a year that has not finished is exactly the kind of row FR-8 is
    about. The two counts differ on this export, which is what makes this a measurement.
    """
    lexical = read_model.execute("SELECT COUNT(*) FROM datapoint WHERE period > '2026-09'")
    row = lexical.fetchone()
    assert row is not None
    assert int(row[0]) != FUTURE_DATED_ROWS


def test_twenty_eight_details_publish_no_datapoint(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    empty = [
        detail_id for detail_id in every_detail(read_model) if not datapoints.publishes(detail_id)
    ]
    assert len(empty) == DETAILS_WITH_NO_DATAPOINTS


# ------------------------------------------------------------ FR-8, over the whole export


def test_no_latest_answer_anywhere_in_the_export_is_a_future_row(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """The acceptance criterion, asserted over every detail rather than over one.

    Not a sample: every published detail is asked for its latest national reading, and
    every figure that comes back must be a period that has finished. One future answer
    anywhere fails this.
    """
    served: list[str] = []
    for detail_id in every_detail(read_model):
        execution = execute_value(a_question(detail_id, Latest()), datapoints)
        figure = execution.figure
        if figure is None:
            continue
        served.append(figure.source_datapoint_id)
        assert has_happened(figure.period, TODAY), f"{detail_id} answered with {figure.period}"
    assert served, "the sweep must actually have produced figures"


def test_the_forty_two_future_actuals_are_never_the_figure(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """Including the 42, named individually.

    The rows that carry an ``Actual`` in the future are the ones a period filter alone
    would not catch, so they are collected by id and each one is checked against every
    figure the engine will serve for "latest" -- nationally and per country.
    """
    forbidden = {
        str(source)
        for period, actual, source in read_model.execute(
            "SELECT period, actual, source_datapoint_id FROM datapoint"
        )
        if _is_future(str(period)) and is_published_text(actual)
    }
    assert len(forbidden) == FUTURE_DATED_ACTUALS

    for detail_id in every_detail(read_model):
        scopes: tuple[CountryScope, ...] = (National(), *_country_scopes(read_model, detail_id))
        for scope in scopes:
            execution = execute_value(a_question(detail_id, Latest(), scope=scope), datapoints)
            figure = execution.figure
            if figure is not None:
                assert figure.source_datapoint_id not in forbidden


def _country_scopes(connection: sqlite3.Connection, detail_id: str) -> tuple[Named, ...]:
    return tuple(
        Named(countries=frozenset({str(row[0])}))
        for row in connection.execute(
            "SELECT DISTINCT country_id FROM datapoint "
            "WHERE detail_id = ? AND country_id IS NOT NULL",
            (detail_id,),
        )
    )


def test_the_newest_row_is_the_wrong_answer_for_seventy_eight_details(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """The defect this story forecloses, measured rather than argued.

    If the two rules agreed on this export, every assertion above would pass against an
    implementation that just took ``max(period)``. They disagree for 78 of the details
    that produce a national figure at all.
    """
    diverged = 0
    for detail_id in every_detail(read_model):
        published = datapoints.periods(detail_id, None)
        if not published:
            continue
        figure = execute_value(a_question(detail_id, Latest()), datapoints).figure
        if figure is None:
            continue
        if figure.period != newest_first(published)[0]:
            diverged += 1
    assert diverged == NEWEST_ROW_IS_NOT_THE_ANSWER


def test_a_placeholder_row_is_walked_past_rather_than_served(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """FR-8's other clause: *with a non-placeholder value*.

    20 details publish a row whose period has ended and whose ``Actual`` is blank. The
    fetch walks past it to the reading behind it instead of serving an empty figure.
    """
    skipped = 0
    for detail_id in every_detail(read_model):
        published = datapoints.periods(detail_id, None)
        candidates = candidate_periods(Latest(), published, TODAY)
        if not candidates:
            continue
        figure = execute_value(a_question(detail_id, Latest()), datapoints).figure
        if figure is not None and figure.period != candidates[0]:
            newest = datapoints.row(detail_id, candidates[0], None)
            assert newest is not None
            assert not is_published_text(newest.actual), "it was skipped for a reason"
            skipped += 1
    assert skipped == PLACEHOLDER_SKIPPED


def test_a_detail_with_no_reading_at_or_before_today_says_so(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """12 details publish nationally and have nothing eligible. That is a stated cause."""
    stated = [
        detail_id
        for detail_id in every_detail(read_model)
        if datapoints.periods(detail_id, None)
        and cause_of(execute_value(a_question(detail_id, Latest()), datapoints))
        is FigureCause.NO_READING_AT_OR_BEFORE_TODAY
    ]
    assert len(stated) == NO_NATIONAL_READING


def test_the_twenty_eight_empty_details_are_an_explicit_cause(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """*"An explicit no-data outcome carrying that cause, not an empty value."*"""
    empty = [
        detail_id
        for detail_id in every_detail(read_model)
        if cause_of(execute_value(a_question(detail_id, Latest()), datapoints))
        is FigureCause.DETAIL_PUBLISHES_NOTHING
    ]
    assert len(empty) == DETAILS_WITH_NO_DATAPOINTS
    for detail_id in empty:
        execution = execute_value(a_question(detail_id, Latest()), datapoints)
        assert isinstance(execution.outcome, Absent)
        assert detail_id in execution.outcome.reason
        assert FigureCause.DETAIL_PUBLISHES_NOTHING.value in execution.outcome.reason
        assert execution.figure is None
        assert not execution.degradations, "an absence is not a failure"


def test_a_published_value_that_is_not_a_number_is_an_absence_with_its_own_cause(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """Found while writing this story, and reported rather than papered over.

    126 rows across 21 details publish an ``Actual`` that is a bilingual text value --
    ``{"en": "Tier 1", "ar": "Tier 1"}``, ``{"en": "Emerging", "ar": "..."}`` -- rather
    than a number. They are ratings and bands, not broken rows, so the outcome is an
    ``Absent`` naming the value it found, never a ``Failed``, and never an older row of
    the same kind dressed up as the latest reading.
    """
    rows = read_model.execute("SELECT actual FROM datapoint WHERE actual IS NOT NULL").fetchall()
    assert sum(1 for (actual,) in rows if _is_not_a_number(str(actual))) == NON_NUMERIC_ACTUALS

    stated = [
        detail_id
        for detail_id in every_detail(read_model)
        if cause_of(execute_value(a_question(detail_id, Latest()), datapoints))
        is FigureCause.VALUE_IS_NOT_A_FIGURE
    ]
    assert len(stated) == NON_NUMERIC_DETAILS
    execution = execute_value(a_question(stated[0], Latest()), datapoints)
    assert isinstance(execution.outcome, Absent)
    assert not execution.degradations
    assert execution.resolution.period is not None, "it still says which row it looked at"


def _is_not_a_number(text: str) -> bool:
    if not is_published_text(text):
        return False
    try:
        Decimal(text.strip())
    except ArithmeticError:
        return True
    return False


# --------------------------------------------------------- the one question in the spine


def test_what_is_inflation_now(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """AD-1's own example, end to end: exactly one detail is named ``Inflation``.

    It publishes at all three grains, and its latest actual is a different period at each
    -- 2026-04 monthly, 2026-Q1 quarterly, 2025 yearly. All true, all different, which is
    why the grain is bound before the fetch rather than by whichever row is newest.
    """
    detail_id = a_detail(read_model, INFLATION)
    latest = execute_value(a_question(detail_id, Latest()), datapoints)
    assert figure_of(latest).period == Period("2026-04")

    at_each_grain = {
        grain: figure_of(
            execute_value(a_question(detail_id, LastN(n=1, grain=grain)), datapoints)
        ).period
        for grain in Grain
    }
    assert at_each_grain == {
        Grain.MONTHLY: Period("2026-04"),
        Grain.QUARTERLY: Period("2026-Q1"),
        Grain.YEARLY: Period("2025"),
    }


def test_the_grain_the_request_carries_is_the_grain_answered_at(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """FR-5 inside the fetch: a newer row at another grain never overrules the request.

    90 details publish at more than one grain, so a fetch that took the newest row would
    answer a yearly question with a monthly figure 90 times over.
    """
    checked = 0
    for detail_id in every_detail(read_model):
        grains = {found.grain for found in datapoints.periods(detail_id, None)}
        if len(grains) < 2:
            continue
        for grain in grains:
            figure = execute_value(
                a_question(detail_id, LastN(n=1, grain=grain)), datapoints
            ).figure
            if figure is not None:
                assert figure.grain is grain
                checked += 1
    assert checked > len(Grain), "the sweep must actually have fetched at several grains"


def test_last_n_returns_n_readings_newest_first(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """"The last five years" resolves to five periods, and they are the five it means."""
    detail_id = a_detail(read_model, INFLATION)
    execution = execute_value(a_question(detail_id, LastN(n=5, grain=Grain.YEARLY)), datapoints)
    assert [str(period) for period in execution.resolution.periods] == [
        "2025",
        "2024",
        "2023",
        "2022",
        "2021",
    ]
    assert figure_of(execution).period == Period("2025"), "the figure is the newest of them"
    assert len(execution.readings) == 5


# -------------------------------------------------- what the deferred field resolved to


def test_a_deferred_period_records_what_it_resolved_to(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """*"The period it resolved to is recorded on the answer."*

    The answer and the record read one value, so a card saying "April 2026" and a record
    saying something else is not a thing that can happen.
    """
    detail_id = a_detail(read_model, INFLATION)
    question = a_question(detail_id, Latest())
    assert isinstance(question.spec.period, Deferred)

    execution = execute_value(question, datapoints)
    resolution = execution.resolution
    assert resolution.was_deferred is True
    assert resolution.request == Latest()
    assert resolution.period == figure_of(execution).period
    assert resolution.resolved_by == FetchRule.MOST_RECENT_ACTUAL.value


def test_a_period_the_reader_named_is_not_recorded_as_resolved(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """``Exact`` needed no data, so nothing resolved it and the record says so."""
    detail_id = a_detail(read_model, INFLATION)
    execution = execute_value(a_question(detail_id, Exact(Period("2026-03"))), datapoints)
    assert execution.resolution.was_deferred is False
    assert execution.resolution.resolved_by is None
    assert figure_of(execution).period == Period("2026-03")


def test_a_named_future_period_is_still_answered(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """FR-8 governs "latest", not every question.

    289 of the 322 future-dated rows are targets, and a target for 2030 is a legitimate
    published row the reader may ask for by name. What must never happen is it arriving
    as *the latest value*.
    """
    row = read_model.execute(
        "SELECT detail_id, period FROM datapoint "
        "WHERE country_id IS NULL AND target IS NOT NULL AND period >= '2027' LIMIT 1"
    ).fetchone()
    assert row is not None
    detail_id, period = str(row[0]), Period(str(row[1]))
    assert not has_happened(period, TODAY)

    execution = execute_value(
        a_question(detail_id, Exact(period), measure=Measure.TARGET), datapoints
    )
    figure = figure_of(execution)
    assert figure.period == period
    assert figure.measure is Measure.TARGET


# ------------------------------------------------------------- AD-3: only by exact key


def test_every_figure_names_the_row_it_came_from(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """*"A figure that cannot be traced to a row does not exist."*

    Each served figure is taken back to the read model by its own key, and the row found
    there must be the row it claims: same source id, same published digits.
    """
    traced = 0
    for detail_id in every_detail(read_model):
        figure = execute_value(a_question(detail_id, Latest()), datapoints).figure
        if figure is None:
            continue
        row = read_model.execute(
            "SELECT source_datapoint_id, actual FROM datapoint "
            "WHERE detail_id = ? AND period = ? AND country_id IS NULL",
            (figure.detail_id, figure.period.value),
        ).fetchone()
        assert row is not None, f"{figure.source_datapoint_id} names no row"
        assert str(row[0]) == figure.source_datapoint_id
        assert Decimal(str(row[1])) == figure.value
        traced += 1
    assert traced > len(Grain)


def test_the_port_offers_no_way_to_ask_for_the_newest_value() -> None:
    """The structural half of AD-3.

    One method returns a value and it takes the whole key; the other two return a yes/no
    and a calendar. There is nothing on this port to score, rank or approximate with, so
    a fetch cannot reach a figure except by naming the row.
    """
    surface = {name for name in vars(DatapointsPort) if not name.startswith("_")}
    assert surface == {"publishes", "periods", "row"}
    assert DatapointsPort.periods.__annotations__["return"] == "tuple[Period, ...]"
    assert DatapointsPort.row.__annotations__["return"] == "DatapointRow | None"


def test_the_key_is_the_whole_key(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """A key naming a period the detail does not publish finds nothing -- not a
    neighbour, not the nearest, not the newest."""
    detail_id = a_detail(read_model, INFLATION)
    assert datapoints.row(detail_id, Period("1999-01"), None) is None
    assert datapoints.row("not-a-detail", Period("2026-04"), None) is None


def test_a_figure_is_a_decimal_parsed_from_the_published_digits(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """Never a float: a published decimal read back through one is the rounding defect."""
    detail_id = a_detail(read_model, INFLATION)
    figure = figure_of(execute_value(a_question(detail_id, Exact(Period("2026-03"))), datapoints))
    assert isinstance(figure.value, Decimal)
    assert str(figure.value) == "4.169", "the exact published digits, not a rounding of them"


# ---------------------------------------------------------- AD-5: national is an absence


def test_the_national_scope_selects_the_rows_with_no_country(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """A national figure comes off a row carrying no country at all.

    The home country appears in none of the 8,127 rows, so a scope that had resolved to
    a country name would have matched nothing while looking entirely correct.
    """
    detail_id = a_detail(read_model, INFLATION)
    figure = figure_of(execute_value(a_question(detail_id, Latest()), datapoints))
    assert figure.country_id is None
    assert figure.is_national
    marker = read_model.execute(
        "SELECT country_id FROM datapoint WHERE source_datapoint_id = ?",
        (figure.source_datapoint_id,),
    ).fetchone()
    assert marker is not None and marker[0] is None


def test_a_named_country_selects_that_country_s_own_rows(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    row = read_model.execute(
        "SELECT detail_id, country_id FROM datapoint WHERE country_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    detail_id, country_id = str(row[0]), str(row[1])
    execution = execute_value(
        a_question(detail_id, Latest(), scope=Named(countries=frozenset({country_id}))),
        datapoints,
    )
    figure = execution.figure
    if figure is not None:
        assert figure.country_id == country_id
        assert not figure.is_national


def test_a_country_with_no_rows_for_this_detail_is_a_stated_cause(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """Distinguished from "this detail publishes nothing", because they are different facts."""
    detail_id = a_detail(read_model, INFLATION)
    country = read_model.execute("SELECT country_id FROM ref_country LIMIT 1").fetchone()
    assert country is not None
    execution = execute_value(
        a_question(detail_id, Latest(), scope=Named(countries=frozenset({str(country[0])}))),
        datapoints,
    )
    assert cause_of(execution) is FigureCause.SCOPE_PUBLISHES_NOTHING


def test_a_cross_country_scope_is_refused_rather_than_answered_with_one_row(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """FR-15 asks for *a* figure for *a* country. Two countries is a different query."""
    detail_id = a_detail(read_model, INFLATION)
    several = Named(countries=frozenset({"a", "b"}))
    for scope in (several, DeclaredBenchmarks()):
        execution = execute_value(a_question(detail_id, Latest(), scope=scope), datapoints)
        assert cause_of(execution) is FigureCause.SCOPE_IS_NOT_ONE_SERIES


# ------------------------------------------------------ AD-1: nothing here rebinds a field


def test_an_unbound_field_is_a_cause_and_never_a_default(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """``compile/`` has the last word. The fetch does not repair a field it was not given."""
    detail_id = a_detail(read_model, INFLATION)
    unbound = Unbound(reason="detail-name-is-shared: two details")
    assert cause_of(execute_value(a_question(unbound, Latest()), datapoints)) is (
        FigureCause.DETAIL_NOT_BOUND
    )
    assert cause_of(execute_value(a_question(detail_id, unbound), datapoints)) is (
        FigureCause.PERIOD_NOT_BOUND
    )


def test_an_operation_that_is_not_a_value_is_refused_by_name(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """Never approximated: a series request is not answered with one figure."""
    detail_id = a_detail(read_model, INFLATION)
    execution = execute_value(
        a_question(detail_id, Latest(), operation=Operation.SERIES), datapoints
    )
    assert cause_of(execution) is FigureCause.OPERATION_IS_NOT_A_VALUE


def test_change_is_never_fetched_as_a_measure(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """AD-4: a change value is *selected* from the published column, never computed here."""
    detail_id = a_detail(read_model, INFLATION)
    execution = execute_value(a_question(detail_id, Latest(), measure=Measure.CHANGE), datapoints)
    assert cause_of(execution) is FigureCause.CHANGE_IS_A_PUBLISHED_COLUMN
    with pytest.raises(UnpublishedMeasure):
        a_row("2026-04", "1").cell(Measure.CHANGE)


def test_a_measure_the_row_does_not_publish_is_an_absence_with_a_cause(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """A named period whose target is blank is "no target published", not a zero."""
    detail_id = a_detail(read_model, INFLATION)
    execution = execute_value(
        a_question(detail_id, Exact(Period("2026-03")), measure=Measure.TARGET), datapoints
    )
    assert cause_of(execution) is FigureCause.MEASURE_NOT_PUBLISHED


# -------------------------------------------------- the cases the export does not contain


def test_a_tie_on_the_end_date_goes_to_the_coarser_grain() -> None:
    """"2025" and "2025-12" both end on 31 December. The published rule decides, not the
    order the rows came back in."""
    port = Fake(a_row("2025", "1.5"), a_row("2025-12", "2.5"))
    execution = execute_value(a_question("D", Latest()), port)
    assert tie_goes_coarser()
    assert figure_of(execution).period == Period("2025")
    assert figure_of(execution).grain is Grain.YEARLY


def test_the_walk_passes_a_placeholder_in_every_spelling_absence_takes() -> None:
    """A blank cell, a whitespace cell and a bare dash are one fact, not three."""
    port = Fake(a_row("2026-04", None), a_row("2026-03", "   "), a_row("2026-02", "-"),
                a_row("2026-01", "2.5"))
    execution = execute_value(a_question("D", Latest()), port)
    assert figure_of(execution).period == Period("2026-01")
    assert execution.resolution.periods == (Period("2026-01"),)


def test_a_store_that_will_not_answer_is_a_failure_and_never_an_absence() -> None:
    """AD-15's shape: *a failure must never be indistinguishable from absence*.

    ``Failed`` is a different type from ``Absent``, so a caller that renders one as the
    other does not type-check -- and the degradation it carries is a member of the
    closed taxonomy, so it is counted rather than lost.
    """
    execution = execute_value(a_question("D", Latest()), Fake(broken=True))
    assert isinstance(execution.outcome, Failed)
    assert cause_of(execution) is FigureCause.LOOKUP_FAILED
    assert [classify(item.kind) for item in execution.degradations] == [
        DegradationKind.ADAPTER_UNAVAILABLE
    ]
    assert execution.degradations[0].where.startswith("execute")
    assert execution.figure is None


def test_a_degradation_travels_on_the_result_rather_than_in_a_collector() -> None:
    """Two fetches do not see each other's failures, because there is nowhere shared to
    put one (AD-15, AD-2)."""
    broken = execute_value(a_question("D", Latest()), Fake(broken=True))
    clean = execute_value(a_question("D", Latest()), Fake(a_row("2026-04", "1")))
    assert broken.degradations and not clean.degradations


def test_an_outcome_that_is_not_a_figure_always_states_a_cause() -> None:
    """The invariant that keeps the answer and the record from disagreeing."""
    with pytest.raises(ValueError, match="states one"):
        Execution(
            outcome=Absent(reason="nothing, with no cause recorded"),
            resolution=PeriodResolution(
                request=Latest(), was_deferred=True, periods=(), resolved_by=None
            ),
        )


# ------------------------------------------------------------------ the resolution rules


def test_the_fetch_rules_are_data_and_reachable_by_name() -> None:
    rule_set = rules()
    assert rule_set.value(FetchRule.COMPLETED_PERIOD, Clause.BOUNDARY) == Boundary.PERIOD_END
    assert rule_set.value(FetchRule.COMPLETED_PERIOD, Clause.FUTURE_ROWS_ELIGIBLE) is False
    assert rule_set.value(FetchRule.PLACEHOLDER, Clause.PLACEHOLDER_ROWS_ELIGIBLE) is False
    for rule in FetchRule:
        assert rule_set.get(rule.value).source_file.is_file()


def test_the_constants_the_fetch_reads_come_out_of_those_rules() -> None:
    assert latest_measure() is Measure.ACTUAL
    assert future_rows_are_eligible() is False
    assert placeholder_rows_are_eligible() is False
    assert tie_goes_coarser() is True


def test_the_boundary_falls_on_the_end_of_the_period() -> None:
    """A period still running has not finished being measured.

    Measured on this export against 2026-09-30: the period's end excludes 322 rows and
    the period's start would admit 60 of them, 33 carrying a placeholder ``Actual``.
    """
    assert has_happened(Period("2026-09"), TODAY)
    assert not has_happened(Period("2026"), TODAY), "the year has not finished"
    assert not has_happened(Period("2026-Q4"), TODAY)
    assert has_happened(Period("2026-Q3"), TODAY)


def test_the_candidates_are_the_periods_that_exist_and_nothing_else() -> None:
    published = (Period("2025"), Period("2026-04"), Period("2030"))
    assert candidate_periods(Latest(), published, TODAY) == (Period("2026-04"), Period("2025"))
    assert candidate_periods(Exact(Period("2030")), published, TODAY) == (Period("2030"),)
    assert candidate_periods(Exact(Period("2019")), published, TODAY) == ()
    assert candidate_periods(LastN(n=1, grain=Grain.YEARLY), published, TODAY) == (Period("2025"),)


def test_readings_wanted_reads_the_count_off_the_request() -> None:
    assert readings_wanted(LastN(n=5, grain=Grain.YEARLY)) == 5
    assert readings_wanted(Latest()) == 1
    assert readings_wanted(Exact(Period("2025"))) == 1


def test_an_unknown_period_request_fails_loudly_rather_than_resolving_to_nothing() -> None:
    """An empty tuple would be "no data" wearing an omission's clothes."""
    with pytest.raises(TypeError, match="PeriodSpec"):
        candidate_periods("2025", (), TODAY)  # type: ignore[arg-type]


# ------------------------------------------------------------- compile and execute join up


def test_a_question_compiled_from_words_is_fetched_without_a_second_reading(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """The two layers meet on the frozen spec and nothing else.

    ``compile/`` leaves the period ``Deferred``; ``execute/`` resolves exactly that and
    nothing more -- the detail it was given, the scope it was given, the measure it was
    given.
    """
    detail_id = a_detail(read_model, INFLATION)
    catalogue = snapshot(details=[CatalogueDetail(detail_id=detail_id, names=(INFLATION,))])
    compiled = compile_question(
        CompileInput(question="What is inflation now?", today=TODAY), catalogue
    )
    assert isinstance(compiled.spec.period, Deferred)

    execution = execute_value(compiled, datapoints)
    figure = figure_of(execution)
    assert figure.detail_id == detail_id
    assert figure.period == Period("2026-04")
    assert figure.is_national


def test_a_question_with_no_period_at_all_is_the_same_fetch(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    detail_id = a_detail(read_model, INFLATION)
    catalogue = snapshot(details=[CatalogueDetail(detail_id=detail_id, names=(INFLATION,))])
    compiled = compile_question(CompileInput(question="inflation", today=TODAY), catalogue)
    assert figure_of(execute_value(compiled, datapoints)).period == Period("2026-04")


# ------------------------------------------------ AD-9a and NFR-6: nothing leaves the box


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the answer path opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_the_whole_corpus_compiles_with_the_network_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-9a: no synchronous call to the indicator service on the answer path."""
    from corpus_runner import run_corpus

    _no_network(monkeypatch)
    assert run_corpus() > 0


def test_the_fetch_answers_with_the_network_unavailable(
    monkeypatch: pytest.MonkeyPatch, export: CmsExport
) -> None:
    """The whole path -- provision, ingest, compile, fetch -- with no socket available.

    Provisioned inside the test rather than reusing the module fixture, so the ingest
    itself is covered by the same prohibition.
    """
    _no_network(monkeypatch)
    with provision() as databases:
        ingest_published_layer(databases.read_model, export)
        port = ReadModelDatapoints(databases.read_model)
        detail_id = a_detail(databases.read_model, INFLATION)
        assert figure_of(execute_value(a_question(detail_id, Latest()), port)).value


def test_the_answer_path_needs_no_database_service(export: CmsExport) -> None:
    """NFR-6: in memory, built by the same schema step the real startup runs."""
    with provision() as databases:
        ingest_published_layer(databases.read_model, export)
        execution = execute_value(
            a_question(a_detail(databases.read_model, INFLATION), Latest()),
            ReadModelDatapoints(databases.read_model),
        )
        assert execution.figure is not None


# ------------------------------------------------------------- structural, over execute/


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """The string constants that are documentation rather than code.

    Scanned for by identity, so the test below reads *statements* and not prose: a
    docstring saying "this never writes" must not be able to fail a check for writes,
    and a check that could not tell the difference would be a grep with a test's name on.
    """
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def test_execute_writes_nothing() -> None:
    """AD-20: every table has one owning module, and none of them is this one.

    Every string the package actually executes is read: not one of them is a write, and
    the SQL there is must be a ``SELECT``.
    """
    verbs = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "REPLACE", "ALTER")
    statements: list[tuple[str, str]] = []
    for path, tree in _modules(EXECUTE_ROOT):
        documentation = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in documentation:
                continue
            text = node.value.strip().upper()
            if text.startswith(verbs):
                statements.append((f"{path.name}:{node.lineno}", text))
    assert statements, "the scan found no SQL at all; it has stopped working"
    for where, text in statements:
        assert text.startswith("SELECT"), f"execute/ writes at {where}: {text}"
    assert "askai.execute" not in set(TABLE_OWNERS.values())


def test_execute_reaches_io_through_a_port_and_never_through_a_later_layer() -> None:
    """AD-2 at module level, so a failure names the import rather than the contract."""
    forbidden = ("askai.assemble", "askai.narrate", "askai.respond", "askai.api")
    offenders = [
        f"{path.name}:{node.lineno} {node.module}"
        for path, tree in _modules(EXECUTE_ROOT)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(forbidden)
    ]
    assert not offenders, "execute/ reaches past its layer: " + ", ".join(offenders)


def test_nothing_in_execute_opens_a_socket_or_speaks_http() -> None:
    """AD-9a, structurally: there is nothing here that could call a service."""
    networked = ("httpx", "requests", "urllib", "socket", "http", "aiohttp")
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, tree in _modules(EXECUTE_ROOT)
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
        if name.split(".")[0] in networked
    ]
    assert not offenders, "execute/ imports a network library: " + ", ".join(offenders)


def test_the_fetch_derives_no_default_grain_from_the_datapoints() -> None:
    """FR-5 and AD-19 at once.

    The declared default grain is bound in ``compile/``, from the catalogue port, and
    exactly one binder owns the period field. A fetch that read a default grain -- from
    the catalogue or, far worse, off the newest row -- would be the second binder, and
    FR-5's defect is precisely the newest row overruling the declaration.
    """
    for path, _ in _modules(EXECUTE_ROOT):
        source = path.read_text(encoding="utf-8")
        assert "default_grain" not in source, path.name
        assert "declared_grain" not in source, path.name
        assert "CataloguePort" not in source, path.name


def test_the_home_country_is_named_nowhere_in_the_fetch() -> None:
    """AD-5. The national marker is an absence; there is no name to compare."""
    for path, _ in _modules(EXECUTE_ROOT):
        assert "qatar" not in path.read_text(encoding="utf-8").lower(), path.name


def test_the_fetch_declares_its_purity() -> None:
    doc = ast.get_docstring(ast.parse((EXECUTE_ROOT / "value.py").read_text(encoding="utf-8")))
    assert doc is not None
    assert "Purity: IO, via ports only" in doc


def test_no_broad_exception_handler_lives_in_the_fetch() -> None:
    """AD-15: the adapter's failure is typed, so nothing here catches ``Exception``."""
    for path, tree in _modules(EXECUTE_ROOT):
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = node.type
            assert caught is not None, f"{path.name}:{node.lineno} bare except"
            assert not (
                isinstance(caught, ast.Name) and caught.id in {"Exception", "BaseException"}
            ), f"{path.name}:{node.lineno} catches broadly"


# ----------------------------------------------------- the read model, as the fetch reads it


def test_the_declared_default_grain_is_a_declaration_and_not_a_fact_about_the_rows() -> None:
    """The gap Story 1.11 flagged, pinned to the shape its fix must take.

    ``CataloguePort.default_grain`` still has nothing behind it in the read model, and
    the two obvious ways to give it one are both wrong in a way this measures:

    * **Not a column.** ``tests/test_schema.py::test_grain_is_not_a_column_anywhere``
      forbids a ``*grain*`` column in the read model outright -- a period owns its grain
      and a column would be a second opinion.
    * **Not the datapoints.** That is FR-5's defect exactly: the newest row's grain
      overruling the declared one.

    What is left is the declaration itself, which the export publishes in ``P06``: one
    row per detail and interval, with the role it is declared for. This reads it and
    measures what it actually says, so the fix is a one-table ingest rather than a
    judgement call -- and so the ambiguity in it is on the record: 90 of the 289 details
    declare **more than one** actual interval, so "the declared default" needs the
    published coarser tie-break to become a single grain.
    """
    intervals = _published_intervals()
    actual = {
        row["PublishedIndicatorDetailId"]: row["IntervalCode"].strip()
        for row in intervals
        if row["IntervalRole"] == "Actual"
    }
    declared: dict[str, set[str]] = {}
    for row in intervals:
        if row["IntervalRole"] == "Actual":
            declared.setdefault(row["PublishedIndicatorDetailId"], set()).add(
                row["IntervalCode"].strip()
            )
    assert len(declared) == 289, "every published detail declares an actual interval"
    assert sum(1 for codes in declared.values() if len(codes) > 1) == 90
    assert set(actual.values()) <= {grain.value for grain in Grain}


def _published_intervals() -> list[dict[str, str]]:
    """``P06``, read here because no accessor exposes it yet. See the test above."""
    path = next((EXPORT_ROOT / "cms").glob("P06_Published_Intervals*.csv"))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{str(key): str(value or "") for key, value in row.items()} for row in
                csv.DictReader(handle)]


def test_the_read_model_holds_no_grain_column_for_the_fetch_to_read(
    read_model: sqlite3.Connection,
) -> None:
    """The other half of the same decision, from the fetch's side.

    There is no grain column to select on, so the grain of an answer is always the grain
    of the period it was answered at -- never a second field that could disagree.
    """
    for table in ("detail", "datapoint", "catalogue"):
        columns = [str(row[1]) for row in read_model.execute(f"PRAGMA table_info({table})")]
        assert not [name for name in columns if "grain" in name.lower()], table


def test_a_period_the_engine_cannot_classify_never_reaches_the_read_model() -> None:
    """Dropping such a row silently would answer "latest" out of a series with a hole."""
    with provision() as databases:
        connection = databases.read_model
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO datapoint (detail_id, period, source_datapoint_id) "
                "VALUES ('d', 'last-tuesday', 's')"
            )
        connection.rollback()
    assert issubclass(UnreadablePeriod, DatapointsUnavailable), "and if one did, it is a failure"


def test_the_national_rows_are_selected_by_absence_not_by_equality(
    read_model: sqlite3.Connection, datapoints: ReadModelDatapoints
) -> None:
    """``= NULL`` matches nothing in SQL, which is how the national series would vanish."""
    detail_id = a_detail(read_model, INFLATION)
    assert datapoints.periods(detail_id, None), "the national calendar must not be empty"
    count = read_model.execute(
        "SELECT COUNT(*) FROM datapoint WHERE detail_id = ? AND country_id = NULL", (detail_id,)
    ).fetchone()
    assert count is not None and int(count[0]) == 0, "the trap this avoids"


def test_a_resolution_with_nothing_resolved_still_says_what_was_asked() -> None:
    """The record is never blank, even when the outcome is."""
    execution = execute_value(a_question("nothing", Latest()), Fake())
    assert isinstance(execution.resolution, PeriodResolution)
    assert execution.resolution.request == Latest()
    assert execution.resolution.was_deferred is True
    assert execution.resolution.periods == ()
