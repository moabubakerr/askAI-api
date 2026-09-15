"""Behaviour of the domain vocabulary -- every I/O matrix row that is not type-level.

The rows asserted under ``mypy --strict`` instead live in
``tests/test_type_invariants.py``; the rows that are structural properties of the
whole tree live in ``tests/test_domain_invariants.py``.

Nothing here touches a database, a service or a model.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from askai.domain.degradation import Degradation
from askai.domain.element import Element, ElementClass
from askai.domain.numbers import Percent, PercentagePoints, pp
from askai.domain.period import ACCEPTED_PERIOD_FORMS, Grain, Period, PeriodFormatError
from askai.domain.scope import DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    SPEC_VERSION,
    Bound,
    Deferred,
    Exact,
    LastN,
    Latest,
    Measure,
    Operation,
    QuerySpec,
    Range,
    Unbound,
    period_field,
)
from askai.domain.text import is_published_text

# ------------------------------------------------------------------ Period parses


@pytest.mark.parametrize(
    ("value", "grain", "start", "end"),
    [
        ("2025", Grain.YEARLY, date(2025, 1, 1), date(2025, 12, 31)),
        ("2025-Q1", Grain.QUARTERLY, date(2025, 1, 1), date(2025, 3, 31)),
        ("2025-Q4", Grain.QUARTERLY, date(2025, 10, 1), date(2025, 12, 31)),
        ("2025-01", Grain.MONTHLY, date(2025, 1, 1), date(2025, 1, 31)),
        ("2025-02", Grain.MONTHLY, date(2025, 2, 1), date(2025, 2, 28)),
        ("2024-02", Grain.MONTHLY, date(2024, 2, 1), date(2024, 2, 29)),  # leap year
        ("2025-12", Grain.MONTHLY, date(2025, 12, 1), date(2025, 12, 31)),
        ("1900-02", Grain.MONTHLY, date(1900, 2, 1), date(1900, 2, 28)),  # not a leap year
        ("2000-02", Grain.MONTHLY, date(2000, 2, 1), date(2000, 2, 29)),  # is a leap year
    ],
)
def test_period_parses_each_published_form(
    value: str, grain: Grain, start: date, end: date
) -> None:
    period = Period(value)
    assert (period.grain, period.start, period.end) == (grain, start, end)


def test_quarterly_periods_tile_the_year_without_gap_or_overlap() -> None:
    quarters = [Period(f"2025-Q{n}") for n in (1, 2, 3, 4)]
    assert quarters[0].start == date(2025, 1, 1)
    assert quarters[-1].end == date(2025, 12, 31)
    for earlier, later in itertools.pairwise(quarters):
        assert (later.start - earlier.end).days == 1


# ------------------------------------------------------------------ Period rejects


@pytest.mark.parametrize(
    "value",
    [
        "2025-W03",  # ISO week -- a real form, but not a published one
        "Jan 2025",
        "2025-13",  # month 13
        "2025-00",  # month 0
        "2025-Q0",
        "2025-Q5",
        "",
        "  ",
        "2025 ",
        "025",
        "20255",
        "2025-1",  # unpadded month
        "2025-q1",  # lowercase marker
        "2025/01",
        "2025\n",  # `$` would match before a trailing newline; `fullmatch` does not
        "2025-Q1\n",
        "٢٠٢٥",  # Arabic-Indic 2025: `\d` accepts it, `[0-9]` does not
        "٢٠٢٥-Q1",
        "0000",  # matches the shape, has no calendar bounds
        "0000-01",
        "0000-Q1",
    ],
)
def test_period_rejects_an_unpublished_form(value: str) -> None:
    with pytest.raises(PeriodFormatError) as excinfo:
        Period(value)
    message = str(excinfo.value)
    assert repr(value) in message, "the rejection must name the offending value"
    for form in ACCEPTED_PERIOD_FORMS:
        assert form in message, "the rejection must name the accepted forms"


def test_period_rejects_a_date_rather_than_coercing_it() -> None:
    """A `date` is the tempting silent default, so it is refused explicitly."""
    with pytest.raises(PeriodFormatError):
        Period(date(2025, 1, 1))  # type: ignore[arg-type]


def test_an_arabic_indic_period_is_not_a_second_spelling_of_a_published_one() -> None:
    """Two spellings of one period would be two rows under a key built on the string,
    which is what `(detail, period, country)` uniqueness rests on."""
    with pytest.raises(PeriodFormatError):
        Period("٢٠٢٥")


def test_the_year_boundaries_that_do_exist_are_accepted() -> None:
    """Rejecting 0000 must not have rejected the rest of the calendar with it."""
    assert Period("0001").start == date(1, 1, 1)
    assert Period("9999").end == date(9999, 12, 31)


def test_an_unconstructible_period_fails_at_construction_not_at_use() -> None:
    """Year 0000 matches the shape; `date(0, ...)` does not exist.

    The bounds are computed in __post_init__ so this is a PeriodFormatError at
    construction, rather than a bare ValueError escaping later out of `.start` --
    a property documented never to fail.
    """
    with pytest.raises(PeriodFormatError):
        Period("0000")


def test_a_rejected_period_is_never_a_silent_default() -> None:
    """The error is typed and carries the value -- not a fallback period."""
    with pytest.raises(PeriodFormatError) as excinfo:
        Period("2025-13")
    assert isinstance(excinfo.value, ValueError)
    assert excinfo.value.value == "2025-13"


# ------------------------------------------------------------------ grain is derived


def test_grain_is_derived_and_not_a_constructor_argument() -> None:
    field_names = {field.name for field in dataclasses.fields(Period)}
    assert field_names == {"value"}, "grain must not be stored beside the period"
    with pytest.raises(TypeError):
        Period("2025", Grain.MONTHLY)  # type: ignore[call-arg]


def test_grain_cannot_disagree_with_the_period() -> None:
    """There is one of them, so there is nothing to disagree with."""
    assert Period("2025").grain is Grain.YEARLY
    assert Period("2025-Q1").grain is Grain.QUARTERLY
    assert Period("2025-01").grain is Grain.MONTHLY


def test_period_is_frozen_and_hashable() -> None:
    period = Period("2025-Q1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        period.value = "2026-Q1"  # type: ignore[misc]
    assert {Period("2025-Q1"), Period("2025-Q1")} == {Period("2025-Q1")}


# ------------------------------------------------------------------ latest stays determinate


def test_latest_is_deferred_not_unbound_and_not_bound() -> None:
    state = period_field(Latest())
    assert isinstance(state, Deferred)
    assert not isinstance(state, Bound | Unbound)
    assert state.request == Latest()


def test_last_n_is_deferred_for_the_same_reason_as_latest() -> None:
    """"The last five years" is anchored on the latest published period."""
    state = period_field(LastN(5, Grain.YEARLY))
    assert isinstance(state, Deferred)


@pytest.mark.parametrize(
    "request_",
    [Exact(Period("2025-Q1")), Range(Period("2022"), Period("2025"))],
)
def test_a_named_period_is_bound_not_deferred(request_: Exact | Range) -> None:
    state = period_field(request_)
    assert isinstance(state, Bound)
    assert not isinstance(state, Deferred)


def test_deferred_carries_the_request_so_it_is_not_a_flavour_of_missing() -> None:
    state = period_field(LastN(3, Grain.QUARTERLY))
    assert isinstance(state, Deferred)
    assert state.request == LastN(3, Grain.QUARTERLY)


def test_unbound_carries_a_reason() -> None:
    state: Unbound = Unbound("the question named no indicator")
    assert state.reason


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_unbound_refuses_an_empty_reason(blank: str) -> None:
    """The reason is what the clarification or refusal says; without it the answer is
    a silent failure, which is what AD-15 exists to prevent."""
    with pytest.raises(ValueError, match="reason"):
        Unbound(blank)


@pytest.mark.parametrize("n", [0, -1, -5])
def test_last_n_refuses_a_non_positive_count(n: int) -> None:
    with pytest.raises(ValueError, match="at least one period"):
        LastN(n, Grain.YEARLY)


def test_a_range_may_not_run_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        Range(Period("2030"), Period("2020"))


def test_a_range_may_not_change_grain_part_way() -> None:
    with pytest.raises(ValueError, match="one grain"):
        Range(Period("2020"), Period("2025-Q1"))


def test_a_single_period_range_is_allowed() -> None:
    """Inverted is refused; degenerate is a legitimate one-period span."""
    assert Range(Period("2025-Q1"), Period("2025-Q1")).start == Period("2025-Q1")


# ------------------------------------------------------------------ national scope


def test_national_scope_carries_no_country_value() -> None:
    assert dataclasses.fields(National()) == ()


def test_named_scope_filters_rather_than_widens() -> None:
    scope = Named(frozenset({"OMN", "SAU"}))
    assert scope.countries == frozenset({"OMN", "SAU"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.countries = frozenset({"ARE"})  # type: ignore[misc]


def test_an_empty_named_scope_is_refused() -> None:
    """It filters every benchmark away while being indistinguishable from an unset scope;
    National() and DeclaredBenchmarks() are the two ways to mean "no named list"."""
    with pytest.raises(ValueError, match="at least one country"):
        Named(frozenset())


def test_a_mutable_country_set_is_coerced_so_the_spec_stays_hashable() -> None:
    """A plain `set` passed at runtime would make the enclosing QuerySpec unhashable,
    and a spec that cannot be hashed cannot be a cache key or a log field."""
    scope = Named({"OMN", "SAU"})  # type: ignore[arg-type]
    assert isinstance(scope.countries, frozenset)
    assert hash(scope) == hash(Named(frozenset({"OMN", "SAU"})))


def test_the_country_scope_variants_are_distinct_and_comparable() -> None:
    """Each variant equals only itself -- typed as `object` because mypy is right that
    comparing two of them directly is a non-overlapping check. That it *is*
    non-overlapping is the property under test."""
    variants: list[object] = [National(), Named(frozenset({"OMN"})), DeclaredBenchmarks()]
    for left_index, left in enumerate(variants):
        for right_index, right in enumerate(variants):
            assert (left == right) is (left_index == right_index)
    assert National() == National()


# ------------------------------------------------------------------ Element


def test_an_element_requires_a_source_ref_at_runtime_too() -> None:
    with pytest.raises(TypeError):
        Element("inflation was 2.6%", ElementClass.MEASURED)  # type: ignore[call-arg]


def test_no_element_field_has_a_default() -> None:
    """A default on `source_ref` would be a constructor that omits it."""
    for field in dataclasses.fields(Element):
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING


def test_element_offers_no_alternate_constructor() -> None:
    """No classmethod, no factory -- any of them would be a second route to an element."""
    extra = {
        name
        for name, value in vars(Element).items()
        if isinstance(value, classmethod | staticmethod)
    }
    assert extra == set()


def test_element_class_is_immutable_once_set() -> None:
    element = Element("2.6%", ElementClass.MEASURED, "row-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        element.element_class = ElementClass.DERIVED  # type: ignore[misc]


def test_element_class_is_closed_over_the_six_ad6_classes() -> None:
    assert {member.value for member in ElementClass} == {
        "measured",
        "derived",
        "attributed",
        "article",
        "external",
        "absent",
    }


@pytest.mark.parametrize("blank", ["", " ", "\t", "\n  "])
def test_an_element_with_a_blank_source_ref_is_refused(blank: str) -> None:
    """A blank source_ref satisfies the signature and defeats the guarantee.

    It is exactly the render-time-droppable provenance label AD-6 claims to have
    eliminated, and the mypy fixture cannot see it because `Element(c, k, "")` is
    perfectly well typed.
    """
    with pytest.raises(ValueError, match="source_ref"):
        Element("inflation was 2.6%", ElementClass.MEASURED, blank)


def test_element_does_not_model_role() -> None:
    """Class and role are independent axes; role lives in the lens mapping in rules/."""
    assert "role" not in {field.name for field in dataclasses.fields(Element)}


# ------------------------------------------------------------------ Percent and pp


def test_percent_and_pp_are_distinct_types() -> None:
    """Typed as `object` on purpose: mypy rejects the comparison as non-overlapping,
    which is the same claim this makes at runtime. One value, two units, never equal."""
    one_percent: object = Percent(Decimal(1))
    one_pp: object = pp(Decimal(1))
    assert type(one_percent) is not type(one_pp)
    assert one_percent != one_pp


def test_pp_is_an_alias_not_a_second_type() -> None:
    assert pp is PercentagePoints


def test_neither_type_offers_a_float_conversion() -> None:
    for kind in (Percent, PercentagePoints):
        assert not hasattr(kind, "__float__")


def test_no_conversion_exists_in_either_direction() -> None:
    forbidden = {"to_pp", "to_percent", "as_pp", "as_percent", "from_pp", "from_percent"}
    for kind in (Percent, PercentagePoints):
        assert forbidden.isdisjoint(dir(kind))


def test_mixing_percent_and_pp_fails_at_runtime_as_well() -> None:
    with pytest.raises((TypeError, AttributeError)):
        Percent(Decimal("2.6")) + pp(Decimal("0.4"))  # type: ignore[operator]


def test_same_type_arithmetic_works_and_stays_decimal() -> None:
    total = Percent(Decimal("2.6")) + Percent(Decimal("0.4"))
    assert total == Percent(Decimal("3.0"))
    assert isinstance(total.value, Decimal)

    movement = pp(Decimal("0.4")) - pp(Decimal("0.1"))
    assert movement == pp(Decimal("0.3"))
    assert type(movement) is PercentagePoints


def test_the_difference_between_two_percentages_is_percentage_points() -> None:
    """The unit, not just the number.

    FR-21: on an indicator measured in %, a change is in pp. A `Percent` here would put
    the conflation inside the type built to prevent it -- and asserting only that the
    result is a Decimal would not have noticed.
    """
    movement = Percent(Decimal("3.2")) - Percent(Decimal("2.6"))
    assert type(movement) is PercentagePoints
    assert movement == pp(Decimal("0.6"))
    # `object` because mypy rejects the comparison as non-overlapping, which is the
    # same claim: the same number in the other unit is a different value.
    same_number_wrong_unit: object = Percent(Decimal("0.6"))
    assert movement != same_number_wrong_unit


@pytest.mark.parametrize("bad", ["NaN", "-NaN", "sNaN", "Infinity", "-Infinity"])
def test_a_non_finite_decimal_is_refused(bad: str) -> None:
    """NaN would make a frozen value unequal to itself, and either breaks `sorted()`
    on a type declared `order=True`."""
    for kind in (Percent, PercentagePoints):
        with pytest.raises(ValueError, match="finite"):
            kind(Decimal(bad))


def test_these_values_survive_sorting_and_equal_themselves() -> None:
    """The two properties the non-finite guard exists to protect."""
    values = [Percent(Decimal(3)), Percent(Decimal(1)), Percent(Decimal(2))]
    assert sorted(values) == [Percent(Decimal(n)) for n in (1, 2, 3)]
    assert Percent(Decimal(1)) == Percent(Decimal(1))


def test_a_float_is_refused_rather_than_quietly_accepted() -> None:
    for kind in (Percent, PercentagePoints):
        with pytest.raises(TypeError):
            kind(2.6)  # type: ignore[arg-type]


def test_neither_type_formats_or_rounds() -> None:
    """Formatting is the single Formatter in assemble/ (AD-18), not a convenience here."""
    forbidden = {"format", "rounded", "to_string", "display", "__format__"}
    for kind in (Percent, PercentagePoints):
        assert forbidden.isdisjoint(vars(kind))


# ------------------------------------------------------------------ QuerySpec


def _spec(**overrides: object) -> QuerySpec:
    defaults: dict[str, object] = {
        "detail": Bound("d-5fad"),
        "period": period_field(Exact(Period("2025-Q1"))),
        "country_scope": Bound(National()),
        "measure": Bound(Measure.ACTUAL),
        "operation": Bound(Operation.VALUE),
        "today": date(2026, 4, 1),
    }
    defaults.update(overrides)
    return QuerySpec(**defaults)  # type: ignore[arg-type]


def test_a_query_spec_is_frozen() -> None:
    spec = _spec()
    for field in dataclasses.fields(spec):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(spec, field.name, None)


def test_a_query_spec_carries_no_grain_field() -> None:
    assert "grain" not in {field.name for field in dataclasses.fields(QuerySpec)}


def test_a_query_spec_carries_today_rather_than_reading_a_clock() -> None:
    assert _spec().today == date(2026, 4, 1)


def test_spec_version_starts_at_one_and_is_on_every_spec() -> None:
    assert SPEC_VERSION == 1
    assert _spec().spec_version == 1


def test_measure_and_operation_are_closed() -> None:
    assert {member.value for member in Measure} == {"actual", "target", "baseline", "change"}
    assert {member.value for member in Operation} == {
        "value",
        "series",
        "change",
        "comparison",
        "extremum",
        "rank",
        "spread",
        "list",
        "count",
        "definition",
        "explanation",
    }


def test_the_period_field_bypass_is_closed() -> None:
    """`period_field` decides the state -- and nothing may go around it.

    Without this, `Bound(Latest())` was constructible and the module's claim that the
    collapse is "unrepresentable rather than merely discouraged" was simply false.
    """
    with pytest.raises(ValueError, match="never Bound"):
        _spec(period=Bound(Latest()))
    with pytest.raises(ValueError, match="never Bound"):
        _spec(period=Bound(LastN(5, Grain.YEARLY)))
    with pytest.raises(ValueError, match="never Deferred"):
        _spec(period=Deferred(Exact(Period("2025-Q1"))))


def test_a_period_field_built_the_right_way_is_accepted() -> None:
    assert _spec(period=period_field(Latest())).period == Deferred(Latest())


def test_an_unrecognised_period_request_fails_loudly() -> None:
    """A PeriodSpec member added later must not default to Bound, which is AD-1's
    forbidden collapse arriving through an omission rather than a decision."""
    with pytest.raises(TypeError, match="PeriodSpec"):
        period_field("2025-Q1")  # type: ignore[arg-type]


def test_a_spec_version_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _spec(spec_version=99)


def test_today_must_be_a_date_and_not_a_datetime() -> None:
    """`datetime` is a `date` subclass, so two specs for one question would differ by
    time of day -- AD-17 reproducibility lost to a field nobody looked at."""
    with pytest.raises(TypeError, match="datetime"):
        _spec(today=datetime(2026, 4, 1, 9, 30, tzinfo=UTC))


def test_a_spec_field_can_be_unbound_with_a_reason() -> None:
    spec = _spec(detail=Unbound("15 candidates contain 'GDP'"))
    assert isinstance(spec.detail, Unbound)
    assert spec.detail.reason


# ------------------------------------------------------------------ Degradation


def test_a_degradation_is_a_frozen_value() -> None:
    degradation = Degradation(kind="model_unavailable", where="narrate", detail="budget exceeded")
    with pytest.raises(dataclasses.FrozenInstanceError):
        degradation.kind = "other"  # type: ignore[misc]
    assert (degradation.kind, degradation.where, degradation.detail) == (
        "model_unavailable",
        "narrate",
        "budget exceeded",
    )


# ------------------------------------------------------------------ is_published_text


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "\t\n",
        "<p></p>",
        "<p>&nbsp;</p>",
        "&nbsp;",
        "<ul><li><p></p></li></ul>",
        "<p>" + chr(0x00A0) + "</p>",  # no-break space
        "<p>" + chr(0x200B) + "</p>",  # zero width space
        chr(0xFEFF),  # zero width no-break space
        "<p>" + chr(0x00AD) + "</p>",  # soft hyphen -- renders as nothing
        "<p>" + chr(0x2060) + "</p>",  # word joiner
        "&#173;",  # soft hyphen as an entity
        "-",
        chr(0x2013),  # a bare en dash
        "<p>-</p>",
        "<p>&#8211;</p>",  # en dash as a numeric entity
        " <p> &nbsp; </p> ",
        "<br/>",
        '<p class="x"></p>',
    ],
)
def test_is_published_text_is_false_for_every_shape_of_absence(raw: str | None) -> None:
    assert is_published_text(raw) is False


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "n/a",
        "<p>GDP grew 2.6%</p>",
        "<ul><li><p>The cost of clearing exports was QAR 1,935</p></li></ul>",
        "التضخم",  # Arabic: "inflation"
        "<p>-5%</p>",  # a dash that is part of a value, not a bare one
        "--",  # two dashes is not the "nothing to say" marker
        "&amp;",  # decodes to "&", which is content
        "&lt;p&gt;&lt;/p&gt;",  # an *escaped* tag the author typed and wants shown
        "<p>&lt;li&gt;</p>",  # markup around escaped markup
    ],
)
def test_is_published_text_is_true_for_substantive_content(raw: str) -> None:
    assert is_published_text(raw) is True


def test_markup_is_stripped_before_entities_are_decoded() -> None:
    """Order matters, and only one order renders markup to text.

    Decoding first turns `&lt;p&gt;` -- a literal angle bracket the author typed --
    into a real tag and then deletes it, so published text reads as absent.
    """
    assert is_published_text("&lt;p&gt;&lt;/p&gt;") is True
    assert is_published_text("<p>&nbsp;</p>") is False


def test_is_published_text_returns_a_bool_not_a_truthy_value() -> None:
    """Call sites compare it; a truthy string would pass `if` and fail `is True`."""
    assert isinstance(is_published_text("<p>x</p>"), bool)
    assert isinstance(is_published_text(""), bool)
