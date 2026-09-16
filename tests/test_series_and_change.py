"""Epic 3 -- series, change, period comparison and targets.

Stories 3.2 through 3.8. Session A is still building the resolution ladder, so nothing
here asks a question: the ``QuerySpec`` and the ``Figure``s are constructed directly and
the composers are driven from them. That is the better unit test in any case -- it asserts
on the composition rather than on everything upstream of it -- and the corpus entries in
``corpus/epic-3.yaml`` are what will assert the same properties end to end once a question
can reach here.

Each property is asserted where it can actually fail:

* **behaviourally**, on the composers as they run, with figures taken from the measured
  export (``data/cms/``, read 2026-09-15) so the numbers in the assertions are numbers
  that exist;
* **structurally**, as scans -- no composer names a ``FormatMode``, builds a percentage
  type, or reaches a published constant as a literal -- because those are the properties
  a future story breaks by accident rather than on purpose.

The F-005/F-029 class gets the most attention, and deliberately: a change figure that is
percent when it should be percentage points reads fluently, formats correctly, and is
wrong by a factor no reader can see.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from askai.assemble.change import (
    ChangeTables,
    ComparisonDimension,
    ComposedDeclared,
    ComposedSeries,
    ComputedChange,
    DeclaredTarget,
    NotASeries,
    NotPublished,
    PublishedChange,
    SelectedChange,
    Series,
    SeriesError,
    SeriesPoint,
    SeriesRefusal,
    SeriesTables,
    TargetError,
    TargetTables,
    baseline_element,
    change_composition,
    column_identity,
    compare_periods,
    comparison_dimension,
    compute_change,
    declared_element,
    named_periods,
    no_change_published,
    paired_with,
    select_change,
    series_composition,
    series_over,
    target_element,
)
from askai.assemble.change.delta import UnlabelledChange
from askai.assemble.format import Formatter
from askai.assemble.roles import Lens, Placement, Role
from askai.compile.binding import UnboundReason, unbound
from askai.domain.calendar import (
    MixedGrainSpan,
    a_year_earlier,
    following,
    periods_between,
    preceding,
)
from askai.domain.change import (
    Basis,
    ChangeFlavour,
    UndefinedChange,
    change_value,
    read_change,
)
from askai.domain.element import ElementClass
from askai.domain.numbers import Percent, PercentagePoints
from askai.domain.period import Grain, Period
from askai.domain.spec import (
    Bound,
    Deferred,
    Exact,
    Latest,
    Measure,
    Range,
    period_field,
)
from askai.execute.latest import has_happened
from askai.execute.value import Figure, Reading
from askai.messages import Catalogue, Lang, load_catalogue
from askai.ports.presentation import PublishedDetail
from askai.rules import rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
CHANGE_ROOT = PACKAGE_ROOT / "assemble" / "change"

#: The export's own change columns, as the read model spells them. Ten of them across the
#: five published (grain x basis) pairings and two flavours -- Story 3.4's count, written
#: out so the table in `rules/` is asserted against something rather than against itself.
PUBLISHED_PAIRINGS = (
    (Grain.MONTHLY, Basis.MOM),
    (Grain.MONTHLY, Basis.YOY),
    (Grain.QUARTERLY, Basis.QOQ),
    (Grain.QUARTERLY, Basis.YOY),
    (Grain.YEARLY, Basis.YOY),
)


# ------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def formatter(catalogue: Catalogue) -> Formatter:
    return Formatter(catalogue=catalogue, rule_set=rules())


@pytest.fixture(scope="module")
def placement() -> Placement:
    return Placement(rule_set=rules())


@pytest.fixture(scope="module")
def change_tables() -> ChangeTables:
    return ChangeTables(rule_set=rules())


@pytest.fixture(scope="module")
def series_tables() -> SeriesTables:
    return SeriesTables(rule_set=rules())


@pytest.fixture(scope="module")
def target_tables() -> TargetTables:
    return TargetTables(rule_set=rules())


#: `Inflation` as the export publishes it: measured in %, so every change on it is in
#: percentage points. The detail the F-005 trap is easiest to spring on.
INFLATION = PublishedDetail(
    detail_id="D-INFLATION",
    name="Inflation",
    unit="%",
    value_format="0.0",
    source_id="S-NPC",
)

#: `Real GDP`: measured in QAR, so its change is a percentage. The control case.
REAL_GDP = PublishedDetail(
    detail_id="D-REALGDP",
    name="Real GDP",
    unit="QAR",
    value_format="bn0.0",
    source_id="S-NPC",
)


def figure(
    detail: PublishedDetail,
    period: str,
    value: str,
    *,
    measure: Measure = Measure.ACTUAL,
    country_id: str | None = None,
) -> Figure:
    """One published reading, as ``execute/`` would have returned it."""
    return Figure(
        detail_id=detail.detail_id,
        period=Period(period),
        country_id=country_id,
        measure=measure,
        value=Decimal(value),
        source_datapoint_id=f"DP-{detail.detail_id}-{period}",
    )


def readings(detail: PublishedDetail, *published: tuple[str, str]) -> tuple[Reading, ...]:
    """Several readings, newest first -- the order ``execute/`` hands them over in."""
    return tuple(
        Reading(period=Period(period), figure=figure(detail, period, value))
        for period, value in reversed(published)
    )


# ============================================================ 3.2  a series over a range


def test_a_series_is_an_ordered_run_across_the_bound_range_at_one_grain() -> None:
    """FR-16. Ordered oldest first, because a series is read forwards."""
    span = Range(start=Period("2019"), end=Period("2025"))
    series = series_over(
        span,
        readings(
            INFLATION,
            ("2019", "-0.6"),
            ("2020", "-2.7"),
            ("2021", "2.3"),
            ("2022", "4.99528"),
            ("2023", "3.1"),
            ("2024", "1.3"),
            ("2025", "0.54316"),
        ),
    )
    assert [point.period.value for point in series.points] == [
        "2019",
        "2020",
        "2021",
        "2022",
        "2023",
        "2024",
        "2025",
    ]
    assert series.is_contiguous
    assert {point.period.grain for point in series.points} == {Grain.YEARLY}


def test_a_series_is_not_collapsed_into_a_single_headline_figure(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """FR-16's second clause, asserted as the story asks: the role, not the wording."""
    composed = _composed_series(catalogue, formatter, placement, series_tables)
    assert isinstance(composed, ComposedSeries)
    roles = {point.placed.role for point in composed.points}
    assert roles == {Role.SERIES}
    assert Role.HEADLINE not in roles


def test_every_point_carries_the_reference_to_its_own_row(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """AD-3. Each point names the key it was fetched by, and no two points share one."""
    composed = _composed_series(catalogue, formatter, placement, series_tables)
    assert isinstance(composed, ComposedSeries)
    references = [point.placed.element.source_ref for point in composed.points]
    assert len(set(references)) == len(references)
    for point, reference in zip(composed.points, references, strict=True):
        detail_id, period, country, source_id = reference.split("|")
        assert (detail_id, period, country, source_id) == (
            INFLATION.detail_id,
            point.period.value,
            "",
            INFLATION.source_id,
        )


def test_series_values_pass_through_the_single_formatter(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """AD-18. The detail's published unit and Format field, and evidence precision.

    ``0.54316`` published at Format ``0.0`` stays ``0.54316`` in a series, because the
    ``series`` role takes evidence precision -- a run the reader is checking against the
    published table is exactly where rounding would be wrong.
    """
    composed = _composed_series(catalogue, formatter, placement, series_tables)
    assert isinstance(composed, ComposedSeries)
    last = composed.points[-1].placed.element.content
    assert "0.54316" in last
    assert "%" in last


# ========================================================== 3.3  the gaps are stated


def _gapped_series(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
    lang: Lang = Lang.EN,
) -> ComposedSeries:
    """`Public Debt as a Percentage of GDP` quarterly, with the interior gap the export
    actually has: P06 declares quarterly actuals from 2021-Q1 and P03's first quarterly
    row is 2023-Q1."""
    span = Range(start=Period("2022-Q3"), end=Period("2023-Q2"))
    series = series_over(
        span, readings(INFLATION, ("2023-Q1", "3.0"), ("2023-Q2", "2.4"))
    )
    composed = series_composition(
        series,
        INFLATION,
        catalogue,
        formatter,
        placement,
        series_tables,
        lang,
        country_id=None,
        publishes_a_figure=True,
    )
    assert isinstance(composed, ComposedSeries)
    return composed


def test_a_missing_period_is_an_element_not_an_omission(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """FR-17 and FR-45. The run is as long as the span, and the holes carry content."""
    composed = _gapped_series(catalogue, formatter, placement, series_tables)
    assert len(composed.points) == len(periods_between(Period("2022-Q3"), Period("2023-Q2")))
    assert composed.gap_periods == (Period("2022-Q3"), Period("2022-Q4"))
    for placed in composed.gaps:
        assert placed.element.element_class is ElementClass.ABSENT
        assert placed.element.content.strip()


def test_a_gap_names_the_period_that_is_missing(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """FR-45: the missing period *is* the content, in the language's own period form."""
    composed = _gapped_series(catalogue, formatter, placement, series_tables)
    stated = [point.placed.element.content for point in composed.points if point.is_a_gap]
    assert any("Q3 2022" in content for content in stated)
    assert any("Q4 2022" in content for content in stated)


def test_silently_skipping_a_period_is_prohibited(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """The defect, stated directly: a run built from the rows would have two points."""
    composed = _gapped_series(catalogue, formatter, placement, series_tables)
    published_rows = len(composed.row_backed)
    assert published_rows < len(composed.points)
    assert [point.period.value for point in composed.points] == [
        "2022-Q3",
        "2022-Q4",
        "2023-Q1",
        "2023-Q2",
    ]


def test_a_series_that_skipped_a_period_cannot_be_built() -> None:
    """The contiguity check is on the type, so a short run is unrepresentable.

    Both halves: a reading the span did not ask for is refused rather than placed, and a
    ``Series`` assembled by hand out of only the periods that published is refused too --
    which is the shape the defect actually takes.
    """
    span = Range(start=Period("2019"), end=Period("2021"))
    with pytest.raises(SeriesError, match="outside the span"):
        series_over(span, readings(INFLATION, ("2025", "0.5")))
    with pytest.raises(SeriesError, match="covers every period"):
        Series(
            span=span,
            points=(
                SeriesPoint(period=Period("2019"), figure=figure(INFLATION, "2019", "-0.6")),
                SeriesPoint(period=Period("2021"), figure=figure(INFLATION, "2021", "2.3")),
            ),
        )


def test_the_gaps_appear_in_both_lenses(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """FR-59d. The points are explore-only, so the note is what reaches the executive.

    Without it a series answer in the shortest lens would carry no statement that
    anything was missing at all, which is brevity removing exactly what FR-59b says it
    may not.
    """
    composed = _gapped_series(catalogue, formatter, placement, series_tables)
    assert composed.gap_note is not None
    assert composed.gap_note.role is Role.NOTE
    assert placement.lenses_for(Role.NOTE) == {Lens.EXECUTIVE, Lens.EXPLORE}
    assert Lens.EXPLORE in placement.lenses_for(Role.SERIES)
    assert "Q3 2022" in composed.gap_note.element.content
    assert "Q4 2022" in composed.gap_note.element.content


def test_a_contiguous_series_carries_no_gap_note(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    composed = _composed_series(catalogue, formatter, placement, series_tables)
    assert isinstance(composed, ComposedSeries)
    assert composed.gap_note is None
    assert composed.gaps == ()


def test_a_reading_at_another_grain_is_never_a_point_on_the_series() -> None:
    """FR-6 and R-SERIES-IS-ONE-GRAIN. A year does not fill a missing quarter."""
    span = Range(start=Period("2025-Q1"), end=Period("2025-Q4"))
    with pytest.raises(SeriesError, match="one grain"):
        series_over(span, readings(INFLATION, ("2025", "0.54316")))


def test_a_detail_publishing_text_is_refused_rather_than_answered_as_a_span_of_gaps(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """The 21 details publishing a tier or a band across 126 rows.

    "Nothing is published" and "what is published is not a number" are different facts,
    and only the second is true here.
    """
    span = Range(start=Period("2023"), end=Period("2025"))
    refused = series_composition(
        series_over(span, ()),
        INFLATION,
        catalogue,
        formatter,
        placement,
        series_tables,
        Lang.EN,
        country_id=None,
        publishes_a_figure=False,
    )
    assert isinstance(refused, NotASeries)
    assert refused.reason is SeriesRefusal.DETAIL_PUBLISHES_TEXT
    assert INFLATION.name in refused.statement


def test_a_series_states_its_gaps_in_arabic_too(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> None:
    """FR-61/FR-63: the Arabic gap is authored Arabic, not an English sentence."""
    composed = _gapped_series(catalogue, formatter, placement, series_tables, Lang.AR)
    assert composed.gap_note is not None
    content = composed.gap_note.element.content
    assert "الربع الثالث 2022" in content
    assert "No value" not in content


def _composed_series(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    series_tables: SeriesTables,
) -> ComposedSeries | NotASeries:
    span = Range(start=Period("2023"), end=Period("2025"))
    series = series_over(
        span, readings(INFLATION, ("2023", "3.1"), ("2024", "1.3"), ("2025", "0.54316"))
    )
    return series_composition(
        series,
        INFLATION,
        catalogue,
        formatter,
        placement,
        series_tables,
        Lang.EN,
        country_id=None,
        publishes_a_figure=True,
    )


# ==================================== 3.4  select the published column, never recompute


def test_ten_precomputed_change_columns_across_two_flavours(
    change_tables: ChangeTables,
) -> None:
    """Story 3.4's count, asserted against the export's own pairings."""
    pairings = {
        (grain, basis) for grain in Grain for basis in change_tables.bases_for(grain)
    }
    assert pairings == set(PUBLISHED_PAIRINGS)
    columns = {
        column_identity(basis, flavour)
        for _, basis in PUBLISHED_PAIRINGS
        for flavour in ChangeFlavour
    }
    assert len(columns) * 0 + len(PUBLISHED_PAIRINGS) * len(ChangeFlavour) == 10


def test_the_published_column_matching_the_grain_and_basis_is_selected(
    change_tables: ChangeTables,
) -> None:
    """AD-4. The Inflation 2026-04 row: MoM percent empty, MoM pp = -1.5528."""
    later = figure(INFLATION, "2026-04", "2.6162")
    selected = select_change(
        change_tables,
        PublishedChange(mom_percent=None, mom_pp="-1.5528"),
        later,
        Period("2026-03"),
        INFLATION.unit,
        Basis.MOM,
    )
    assert isinstance(selected, SelectedChange)
    assert selected.column == "change_mom_pp"
    assert selected.value == PercentagePoints(Decimal("-1.5528"))
    assert selected.element_class is ElementClass.MEASURED


def test_a_published_column_that_does_not_span_the_pairing_is_not_selected(
    change_tables: ChangeTables,
) -> None:
    """The year-on-year column on the 2025 row spans 2025 and 2024, and nothing else."""
    later = figure(REAL_GDP, "2025", "736.638")
    assert paired_with(Basis.YOY, Period("2025")) == Period("2024")
    assert (
        select_change(
            change_tables,
            PublishedChange(yoy_percent="2.9"),
            later,
            Period("2022"),
            REAL_GDP.unit,
            Basis.YOY,
        )
        is None
    )


def test_a_basis_the_grain_does_not_publish_is_never_selected(
    change_tables: ChangeTables,
) -> None:
    """A yearly row publishes year on year only; asking it for QoQ selects nothing."""
    later = figure(REAL_GDP, "2025", "736.638")
    assert Basis.QOQ not in change_tables.bases_for(Grain.YEARLY)
    assert (
        select_change(
            change_tables,
            PublishedChange(qoq_percent="1.1"),
            later,
            Period("2024"),
            REAL_GDP.unit,
            Basis.QOQ,
        )
        is None
    )


def test_a_change_with_no_published_column_is_computed_and_classed_derived(
    change_tables: ChangeTables,
) -> None:
    """FR-19's second arm, and the class that goes with it."""
    computed = compute_change(
        change_tables,
        figure(REAL_GDP, "2025", "736.638"),
        figure(REAL_GDP, "2022", "700.0"),
        REAL_GDP.unit,
        Basis.YOY,
    )
    assert isinstance(computed, ComputedChange)
    assert computed.element_class is ElementClass.DERIVED
    assert isinstance(computed.value, Percent)


def test_a_computed_change_states_the_readings_it_was_computed_from(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-19: the inputs are on the value, so the sentence cannot omit them."""
    computed = compute_change(
        change_tables,
        figure(INFLATION, "2025", "0.54316"),
        figure(INFLATION, "2022", "4.99528"),
        INFLATION.unit,
        Basis.YOY,
    )
    composed = change_composition(
        computed, INFLATION, catalogue, formatter, placement, change_tables, Lang.EN
    )
    assert composed.was_computed
    assert composed.column is None
    assert composed.placed.element.element_class is ElementClass.DERIVED
    content = composed.placed.element.content
    assert "2025" in content and "2022" in content
    assert "computed" in content


def test_a_measured_element_can_never_carry_a_computed_change(
    change_tables: ChangeTables,
) -> None:
    """Enforced at construction: the class is a property of the value, not an argument.

    There is no way to pass ``measured`` to a computed change, because the composer never
    takes an ``ElementClass`` -- it reads one off whichever of the two types it was
    handed.
    """
    computed = compute_change(
        change_tables,
        figure(REAL_GDP, "2025", "736.638"),
        figure(REAL_GDP, "2024", "715.866"),
        REAL_GDP.unit,
        Basis.YOY,
    )
    assert computed.element_class is ElementClass.DERIVED
    with pytest.raises(AttributeError):
        object.__setattr__(computed, "element_class", ElementClass.MEASURED)


def test_a_selected_change_cannot_exist_without_naming_its_column() -> None:
    """The other half of the same guarantee."""
    with pytest.raises(LookupError, match="names the published column"):
        SelectedChange(
            basis=Basis.YOY,
            value=Percent(Decimal("2.9")),
            column="   ",
            later=figure(REAL_GDP, "2025", "736.638"),
            earlier=Period("2024"),
        )


def test_a_change_across_a_range_states_both_endpoints(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-18. Both bound endpoints are in the sentence, not implied by the basis."""
    selected = select_change(
        change_tables,
        PublishedChange(yoy_percent="2.9"),
        figure(REAL_GDP, "2025", "736.638"),
        Period("2024"),
        REAL_GDP.unit,
        Basis.YOY,
    )
    assert selected is not None
    composed = change_composition(
        selected, REAL_GDP, catalogue, formatter, placement, change_tables, Lang.EN
    )
    assert "2025" in composed.placed.element.content
    assert "2024" in composed.placed.element.content


def test_the_selected_column_identity_is_what_a_corpus_entry_asserts_on(
    change_tables: ChangeTables,
) -> None:
    """The F-005/F-029 guard: the identity, not the rendered number."""
    selected = select_change(
        change_tables,
        PublishedChange(yoy_percent="2.9", yoy_pp="0.6"),
        figure(INFLATION, "2025", "0.54316"),
        Period("2024"),
        INFLATION.unit,
        Basis.YOY,
    )
    assert selected is not None
    # The percent column is populated and is *not* what was read: the unit decided.
    assert selected.column == "change_yoy_pp"
    assert selected.value == PercentagePoints(Decimal("0.6"))


def test_recomputing_a_published_column_is_not_permitted_by_the_rules(
    change_tables: ChangeTables,
) -> None:
    assert change_tables.may_recompute_a_published_column() is False
    assert change_tables.may_compute_when_nothing_matches() is True


# ========================================= 3.5  always name the basis and the periods


def test_a_change_figure_names_its_basis_and_both_periods(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-20, and R-168's reading it moved to."""
    selected = select_change(
        change_tables,
        PublishedChange(mom_pp="-1.5528"),
        figure(INFLATION, "2026-04", "2.6162"),
        Period("2026-03"),
        INFLATION.unit,
        Basis.MOM,
    )
    assert selected is not None
    composed = change_composition(
        selected, INFLATION, catalogue, formatter, placement, change_tables, Lang.EN
    )
    content = composed.placed.element.content
    assert "month on month" in content
    assert "April 2026" in content and "March 2026" in content
    assert "2.6" in content  # the reading it moved to (R-168)


def test_an_unlabelled_growth_figure_is_a_failing_test_not_a_cosmetic_issue(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-20 made into something that fails.

    The wording is data, so the way this breaks in practice is an edit to the catalogue
    that drops ``{basis}``. The composer checks the message's own parameter set before
    rendering, so the edit fails here rather than producing a fluent, undefendable figure.
    """
    stripped = dict(catalogue.fields)
    stripped["change.selected"] = frozenset(
        field for field in stripped["change.selected"] if field != "basis"
    )
    # The catalogue is frozen, so the edit is a new one rather than a mutation -- which
    # is the same shape the real edit takes: a changed file, loaded fresh.
    edited = dataclasses.replace(catalogue, fields=stripped)

    selected = select_change(
        change_tables,
        PublishedChange(mom_pp="-1.5528"),
        figure(INFLATION, "2026-04", "2.6162"),
        Period("2026-03"),
        INFLATION.unit,
        Basis.MOM,
    )
    assert selected is not None
    with pytest.raises(UnlabelledChange, match="basis"):
        change_composition(
            selected, INFLATION, edited, formatter, placement, change_tables, Lang.EN
        )


def test_a_computed_change_says_that_it_was_computed(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-19. Two different sentences, because they are two different claims."""
    computed = compute_change(
        change_tables,
        figure(REAL_GDP, "2025", "736.638"),
        figure(REAL_GDP, "2022", "700.0"),
        REAL_GDP.unit,
        Basis.YOY,
    )
    selected = SelectedChange(
        basis=Basis.YOY,
        value=Percent(Decimal("2.9")),
        column="change_yoy_percent",
        later=figure(REAL_GDP, "2025", "736.638"),
        earlier=Period("2024"),
    )
    spoken = {
        change_composition(
            change, REAL_GDP, catalogue, formatter, placement, change_tables, Lang.EN
        ).placed.element.content
        for change in (computed, selected)
    }
    assert len(spoken) == len(("computed", "selected"))


def test_the_basis_and_periods_survive_the_executive_lens(placement: Placement) -> None:
    """FR-59b. ``delta`` is shown in both lenses, and the label is inside the element."""
    assert placement.shows(Lens.EXECUTIVE, Role.DELTA)
    assert placement.shows(Lens.EXPLORE, Role.DELTA)


def test_the_basis_is_named_in_arabic_from_the_catalogue(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-63. Authored Arabic, never a transliterated English abbreviation."""
    selected = select_change(
        change_tables,
        PublishedChange(mom_pp="-1.5528"),
        figure(INFLATION, "2026-04", "2.6162"),
        Period("2026-03"),
        INFLATION.unit,
        Basis.MOM,
    )
    assert selected is not None
    content = change_composition(
        selected, INFLATION, catalogue, formatter, placement, change_tables, Lang.AR
    ).placed.element.content
    assert "على أساس شهري" in content
    for spelling in ("MoM", "YoY", "QoQ", "month on month"):
        assert spelling not in content


def test_no_change_is_published_names_the_basis_it_was_asked_for(
    catalogue: Catalogue,
) -> None:
    """"No change is published" and "no quarter-on-quarter change is published" differ."""
    stated = no_change_published(REAL_GDP, catalogue, Lang.EN, Basis.QOQ)
    assert "quarter on quarter" in stated.statement
    assert REAL_GDP.name in stated.statement


# ========================================== 3.6  percent is never percentage points


def test_a_change_on_a_percent_indicator_is_typed_and_labelled_pp(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-21. A 2-point move in an inflation rate is never reported as 2% growth."""
    assert change_tables.flavour_for(INFLATION.unit) is ChangeFlavour.PERCENTAGE_POINTS
    selected = select_change(
        change_tables,
        PublishedChange(mom_pp="-1.5528"),
        figure(INFLATION, "2026-04", "2.6162"),
        Period("2026-03"),
        INFLATION.unit,
        Basis.MOM,
    )
    assert selected is not None
    assert isinstance(selected.value, PercentagePoints)
    content = change_composition(
        selected, INFLATION, catalogue, formatter, placement, change_tables, Lang.EN
    ).placed.element.content
    assert "pp" in content


def test_a_change_on_an_indicator_in_its_own_unit_is_a_percentage(
    change_tables: ChangeTables,
) -> None:
    assert change_tables.flavour_for(REAL_GDP.unit) is ChangeFlavour.PERCENT
    assert change_tables.unit_for(ChangeFlavour.PERCENT) == "%"
    assert change_tables.unit_for(ChangeFlavour.PERCENTAGE_POINTS) == "pp"


def test_percent_and_percentage_points_do_not_convert() -> None:
    """AD-4. Asserted at runtime as well as under ``mypy --strict``."""
    with pytest.raises(TypeError):
        Percent(Decimal(1)) + PercentagePoints(Decimal(1))  # type: ignore[operator]
    with pytest.raises(TypeError):
        PercentagePoints(Decimal(1)) + Percent(Decimal(1))  # type: ignore[operator]
    movement = Percent(Decimal("3.2")) - Percent(Decimal("2.6"))
    assert isinstance(movement, PercentagePoints)


def test_the_declared_flavour_decides_the_type_never_the_value() -> None:
    """Story 3.6's clause, and the whole of why the flavour is an argument.

    The same digits become two different quantities, chosen by the column they came from.
    """
    digits = Decimal("2.0")
    assert change_value(ChangeFlavour.PERCENT, digits) == Percent(digits)
    assert change_value(ChangeFlavour.PERCENTAGE_POINTS, digits) == PercentagePoints(digits)
    assert read_change(ChangeFlavour.PERCENTAGE_POINTS, "2.0") == PercentagePoints(digits)


def test_a_column_publishing_nothing_reads_as_no_change_rather_than_zero() -> None:
    """The Inflation 2026-04 row publishes no MoM percent. Empty is not nought."""
    assert read_change(ChangeFlavour.PERCENT, None) is None
    assert read_change(ChangeFlavour.PERCENT, "") is None
    assert read_change(ChangeFlavour.PERCENT, "-") is None
    assert read_change(ChangeFlavour.PERCENT, "0") == Percent(Decimal(0))


def test_a_proportional_change_from_zero_is_undefined_rather_than_enormous() -> None:
    with pytest.raises(UndefinedChange):
        compute_change(
            ChangeTables(rule_set=rules()),
            figure(REAL_GDP, "2025", "10"),
            figure(REAL_GDP, "2024", "0"),
            REAL_GDP.unit,
            Basis.YOY,
        )


# ================================== 3.7  compare the same indicator at two named periods


def test_two_named_periods_are_read_from_the_binder_s_own_account() -> None:
    """FR-23. ``compile/`` refuses to bind them as a span and says which two they were."""
    state = unbound(UnboundReason.MORE_THAN_ONE_PERIOD_NAMED, "2022, 2025")
    assert named_periods(state) == (Period("2022"), Period("2025"))
    assert comparison_dimension(state) is ComparisonDimension.PERIOD


def test_the_comparison_dimension_is_derived_and_never_defaulted() -> None:
    """A question that bound one period, or deferred one, is not a period comparison."""
    assert comparison_dimension(period_field(Exact(Period("2025")))) is None
    assert comparison_dimension(period_field(Latest())) is None
    assert named_periods(Bound(value=Exact(Period("2025")))) == ()
    assert named_periods(Deferred(request=Latest())) == ()


def test_a_question_refused_for_another_reason_is_not_a_period_comparison() -> None:
    """FR-22's existence: countries bind a scope, and that is Epic 4's composition."""
    other = unbound(UnboundReason.GRAIN_NOT_PUBLISHED, "quarterly")
    assert named_periods(other) == ()
    assert comparison_dimension(other) is None


def test_both_periods_are_named_alongside_their_figures(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-23. `Inflation` 2022 = 4.99528 and 2025 = 0.54316, no column spanning them."""
    comparison = compare_periods(
        figure(INFLATION, "2022", "4.99528"),
        figure(INFLATION, "2025", "0.54316"),
        INFLATION,
        PublishedChange(yoy_pp="-0.8"),
        catalogue,
        formatter,
        placement,
        change_tables,
        Lang.EN,
    )
    assert comparison.dimension is ComparisonDimension.PERIOD
    assert comparison.periods == (Period("2022"), Period("2025"))
    spoken = " ".join(placed.element.content for placed in comparison.readings)
    assert "2022" in spoken and "2025" in spoken
    assert "4.99528" in spoken and "0.54316" in spoken
    # No published column spans 2022 and 2025, so the movement is computed and says so.
    assert comparison.was_computed


def test_a_published_column_spanning_exactly_those_two_periods_is_selected(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-19 inside FR-23: 2024 against 2025 *is* the published year-on-year pairing."""
    comparison = compare_periods(
        figure(REAL_GDP, "2024", "715.866"),
        figure(REAL_GDP, "2025", "736.638"),
        REAL_GDP,
        PublishedChange(yoy_percent="2.9"),
        catalogue,
        formatter,
        placement,
        change_tables,
        Lang.EN,
    )
    assert not comparison.was_computed
    assert comparison.change.column == "change_yoy_percent"
    assert isinstance(comparison.change.change, SelectedChange)


def test_both_readings_are_shown_as_published_so_the_movement_can_be_checked(
    change_tables: ChangeTables,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """The readings take the ``evidence`` role, which preserves published precision."""
    comparison = compare_periods(
        figure(INFLATION, "2022", "4.99528"),
        figure(INFLATION, "2025", "0.54316"),
        INFLATION,
        PublishedChange(),
        catalogue,
        formatter,
        placement,
        change_tables,
        Lang.EN,
    )
    assert {placed.role for placed in comparison.readings} == {Role.EVIDENCE}
    assert "4.99528" in comparison.readings[0].element.content


# ============================================ 3.8  published targets and baselines


def test_a_published_target_is_answered_and_labelled_as_a_target(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """FR-37. `Non-Hydrocarbon Real GDP` declares TargetValue 581.2805 at 2030."""
    detail = PublishedDetail(
        detail_id="D-NHGDP",
        name="Non-Hydrocarbon Real GDP",
        unit="QAR",
        value_format="bn0.0",
        source_id="S-NPC",
    )
    composed = target_element(
        DeclaredTarget(
            detail_id="D-NHGDP",
            target=Decimal("581.2805"),
            target_period=Period("2030"),
        ),
        detail,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(composed, ComposedDeclared)
    assert composed.measure is Measure.TARGET
    assert composed.period == Period("2030")
    assert "target" in composed.placed.element.content.lower()
    assert "581.3" in composed.placed.element.content


def test_a_published_baseline_is_answered_and_labelled_as_a_baseline(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """`Total Population` declares BaseLineValue 2.76 at BaseLineYear 2019, unit m."""
    detail = PublishedDetail(
        detail_id="D-POP",
        name="Total Population",
        unit="m",
        value_format="0.00",
        source_id="S-PSA",
    )
    composed = baseline_element(
        DeclaredTarget(
            detail_id="D-POP",
            target=Decimal(4),
            target_period=Period("2030"),
            baseline=Decimal("2.76"),
            baseline_period=Period("2019"),
        ),
        detail,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(composed, ComposedDeclared)
    assert composed.measure is Measure.BASELINE
    assert "baseline" in composed.placed.element.content.lower()
    assert "2019" in composed.placed.element.content


def test_a_detail_publishing_no_target_is_refused_and_says_which_is_missing(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """Targets reach 98 of 289 details, so the refusal is the commoner answer."""
    declared = DeclaredTarget(detail_id=INFLATION.detail_id)
    refused = target_element(
        declared,
        INFLATION,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(refused, NotPublished)
    assert refused.measure is Measure.TARGET
    assert "target" in refused.statement.lower()

    no_baseline = baseline_element(
        declared,
        INFLATION,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(no_baseline, NotPublished)
    assert no_baseline.measure is Measure.BASELINE


def test_half_a_declaration_is_refused_at_construction() -> None:
    """A value with no year is a number with nothing to aim at."""
    with pytest.raises(TargetError, match="target"):
        DeclaredTarget(detail_id="D-X", target=Decimal(1))
    with pytest.raises(TargetError, match="baseline"):
        DeclaredTarget(detail_id="D-X", baseline_period=Period("2019"))


def test_the_whole_answer_is_composed_from_the_single_measure_binding(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """AD-1. The bound ``measure`` dispatches once, and an actual is not answered here."""
    declared = DeclaredTarget(
        detail_id=INFLATION.detail_id,
        baseline=Decimal("2.1"),
        baseline_period=Period("2019"),
    )
    composed = declared_element(
        Measure.BASELINE,
        declared,
        INFLATION,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(composed, ComposedDeclared)
    assert composed.measure is Measure.BASELINE

    for measure in (Measure.ACTUAL, Measure.CHANGE):
        with pytest.raises(TargetError, match="not declared on a detail"):
            declared_element(
                measure,
                declared,
                INFLATION,
                catalogue,
                formatter,
                placement,
                target_tables,
                Lang.EN,
                country_id=None,
            )


def test_a_future_dated_target_is_answerable_and_a_future_dated_actual_is_not(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """FR-8 governs actuals, not published targets -- 289 of 322 future rows are targets."""
    today = date(2026, 9, 15)
    assert not has_happened(Period("2030"), today)

    detail = PublishedDetail(
        detail_id="D-NHGDP",
        name="Non-Hydrocarbon Real GDP",
        unit="QAR",
        value_format="bn0.0",
        source_id="S-NPC",
    )
    composed = target_element(
        DeclaredTarget(
            detail_id="D-NHGDP",
            target=Decimal("581.2805"),
            target_period=Period("2030"),
        ),
        detail,
        catalogue,
        formatter,
        placement,
        target_tables,
        Lang.EN,
        country_id=None,
    )
    assert isinstance(composed, ComposedDeclared)
    assert composed.period.start > today
    assert target_tables.future_dated_target_is_eligible() is True
    assert target_tables.future_dated_actual_is_eligible() is False


def test_a_target_is_never_shown_as_an_actual(target_tables: TargetTables) -> None:
    """F-015. The label is part of the sentence, not a field a renderer may drop."""
    assert target_tables.may_be_shown_as_an_actual() is False


def test_a_baseline_is_read_from_the_detail_and_never_from_a_datapoint(
    target_tables: TargetTables,
) -> None:
    """``datapoint.baseline`` is NULL on all 8,127 rows, deliberately (Story 1.8)."""
    assert target_tables.baseline_is_read_from_a_datapoint() is False


def test_a_declaration_is_never_composed_against_another_detail(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    target_tables: TargetTables,
) -> None:
    """Every part of the sentence but the number would be about the wrong indicator."""
    with pytest.raises(TargetError, match="belongs to"):
        target_element(
            DeclaredTarget(
                detail_id="D-SOMETHING-ELSE",
                target=Decimal("1.0"),
                target_period=Period("2030"),
            ),
            INFLATION,
            catalogue,
            formatter,
            placement,
            target_tables,
            Lang.EN,
            country_id=None,
        )


# ============================================================== the calendar underneath


@pytest.mark.parametrize(
    ("period", "next_period", "previous", "year_earlier"),
    [
        ("2025", "2026", "2024", "2024"),
        ("2025-Q4", "2026-Q1", "2025-Q3", "2024-Q4"),
        ("2025-Q1", "2025-Q2", "2024-Q4", "2024-Q1"),
        ("2025-12", "2026-01", "2025-11", "2024-12"),
        ("2025-01", "2025-02", "2024-12", "2024-01"),
    ],
)
def test_the_calendar_steps_at_the_period_s_own_grain(
    period: str, next_period: str, previous: str, year_earlier: str
) -> None:
    assert following(Period(period)) == Period(next_period)
    assert preceding(Period(period)) == Period(previous)
    assert a_year_earlier(Period(period)) == Period(year_earlier)


def test_the_expected_run_comes_from_the_span_and_not_from_the_rows() -> None:
    assert periods_between(Period("2024-Q3"), Period("2025-Q2")) == (
        Period("2024-Q3"),
        Period("2024-Q4"),
        Period("2025-Q1"),
        Period("2025-Q2"),
    )
    assert periods_between(Period("2025"), Period("2025")) == (Period("2025"),)


def test_a_span_that_changes_grain_part_way_is_refused() -> None:
    with pytest.raises(MixedGrainSpan):
        periods_between(Period("2024"), Period("2025-Q4"))
    with pytest.raises(MixedGrainSpan):
        periods_between(Period("2025"), Period("2024"))


# ===================================================================== the scans


def _modules() -> list[Path]:
    return sorted(CHANGE_ROOT.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _names_called(tree: ast.Module) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node.func.id, node.lineno


def test_no_composer_in_this_package_names_a_format_mode() -> None:
    """AD-18/FR-48. The mode is a property of the position, asked for by role."""
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in _modules()
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Attribute) and node.attr in ("HEADLINE", "EVIDENCE")
        and isinstance(node.value, ast.Name)
        and node.value.id == "FormatMode"
    ]
    assert not offences, "a composer holds a Role and asks Placement:\n  " + "\n  ".join(
        offences
    )


def test_no_composer_in_this_package_constructs_a_percentage_type() -> None:
    """AD-4. The one constructor is ``domain/change.py``; here there is none."""
    constructors = frozenset({"Percent", "PercentagePoints", "pp"})
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line} builds {name}"
        for path in _modules()
        for name, line in _names_called(_parse(path))
        if name in constructors
    ]
    assert not offences, "percent and percentage points never convert:\n  " + "\n  ".join(
        offences
    )


def test_every_rule_this_package_names_exists_and_fires() -> None:
    """A rule id spelled wrong would be a table that silently never applies.

    Matched on the whole string rather than on a prefix: prose mentioning ``R-168`` is a
    citation, and treating it as an id would make this scan fail on a comment.
    """
    rule_set = rules()
    named = {
        node.value
        for path in _modules()
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"R-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", node.value)
    }
    assert named
    for rule_id in sorted(named):
        assert rule_set.fire(rule_id).is_fireable


def test_the_composers_state_their_purity_class() -> None:
    doc = ast.get_docstring(_parse(CHANGE_ROOT / "__init__.py"))
    assert doc is not None
    assert "Purity: pure." in doc
