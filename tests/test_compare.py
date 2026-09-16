"""Epic 4 -- comparison across countries and across indicators.

The epic exists to prevent one defect and to make four refusals distinguishable.

**The defect is F-001.** The benchmark configuration names the home country in all 21
declared sets; the published data names it in none of its 8,127 rows. So a comparison
that looks countries up by name retrieves every benchmark and silently drops the country
the reader asked about, and a two-country question comes back with six. The tests here
assert both halves of the fix: that a named set *filters* the declared set and never
widens it, and that the home country reaches the answer as a national selection rather
than as a country filter value -- which is structural, because ``filter_values`` has
nothing to emit it from.

**The four refusals.** Cross-country comparison reaches 21 of 289 details, so refusing is
the normal outcome and refusing *well* is most of the work. These are four different
statements with four different message ids, and the tests assert they are different
rather than merely present:

* this indicator declares no benchmark countries at all (268 of 289 details);
* the countries you named are not among the ones it declares;
* it declares them and publishes no country rows at all (``Total Population``, the one
  detail among the 21 in that state);
* it declares them and *this* one published nothing at the period asked about.

The first two are configuration gaps, the last two are data gaps, and a QC tester is
entitled to tell which happened from the answer alone.

The composers are driven from values constructed here rather than through the resolution
ladder, which is another session's story. Everything they need -- the declared set, the
readings, the published detail -- is handed in, so these tests exercise the composition
and nothing else.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from askai.assemble.compare import (
    Candidate,
    CompareMessage,
    Composed,
    CountryReading,
    Declaration,
    Direction,
    ExtremumMessage,
    IndicatorMessage,
    IndicatorReading,
    NotComparable,
    OrdinalMessage,
    Scope,
    Selection,
    SelectionRefusal,
    at_period,
    best_direction,
    compare_countries,
    compare_indicators,
    extremum,
    fan_out_bound,
    named_countries_may_expand,
    named_positions,
    ordered,
    ordinal,
    rank_format,
    ranking,
    refusal_statement,
    select,
    spread,
    units_differ,
    with_figures,
)
from askai.assemble.format import Formatter
from askai.assemble.roles import Placement, Role
from askai.domain.difference import spread as difference
from askai.domain.element import ElementClass
from askai.domain.numbers import Percent, PercentagePoints
from askai.domain.period import Period
from askai.domain.scope import DeclaredBenchmarks, Named, National
from askai.domain.spec import Measure
from askai.execute.value import Figure
from askai.messages import Catalogue, Lang, load_catalogue
from askai.ports.presentation import PublishedDetail
from askai.rules import RuleSet, load_rules
from askai.rules.countries import (
    Country,
    CountryAliases,
    HomeCountry,
    filter_values,
    load_country_aliases,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"


# ----------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    from askai.rules import DATA_DIR

    return load_rules(DATA_DIR)


@pytest.fixture(scope="module")
def aliases(rule_set: RuleSet) -> CountryAliases:
    return load_country_aliases(rule_set)


@pytest.fixture(scope="module")
def formatter(catalogue: Catalogue, rule_set: RuleSet) -> Formatter:
    return Formatter(catalogue=catalogue, rule_set=rule_set)


@pytest.fixture(scope="module")
def placement(rule_set: RuleSet) -> Placement:
    return Placement(rule_set=rule_set)


#: The declared benchmark set for the worked example, as P05 carries it for `Inflation`:
#: the home country and five Gulf and Asian comparators. Held as identities, because the
#: alias map has already resolved them -- which is where the home country stops being a
#: name and becomes the absence of one.
def a_declared_set() -> Declaration:
    return Declaration(
        detail_id="D-CPI-HEADLINE",
        declared=(
            HomeCountry(),
            Country(code="BH"),
            Country(code="SA"),
            Country(code="KW"),
            Country(code="OM"),
            Country(code="SG"),
        ),
    )


def a_published_detail(unit: str = "%", spec: str = "0.0") -> PublishedDetail:
    return PublishedDetail(
        detail_id="D-CPI-HEADLINE",
        name="Inflation",
        unit=unit,
        value_format=spec,
        source_id="S-PSA-CPI",
    )


def a_period() -> Period:
    return Period("2026-Q1")


def a_figure(
    value: str,
    country_id: str | None = None,
    period: Period | None = None,
    detail_id: str = "D-CPI-HEADLINE",
) -> Figure:
    return Figure(
        detail_id=detail_id,
        period=period or a_period(),
        country_id=country_id,
        measure=Measure.ACTUAL,
        value=Decimal(value),
        source_datapoint_id=f"DP-{detail_id}-{country_id or 'NAT'}-{(period or a_period()).value}",
    )


def the_inflation_readings() -> tuple[CountryReading, ...]:
    """The 2026-Q1 rows behind corpus entry e4-003, national row included.

    The home country's figure carries no country id at all, which is what the data
    actually holds -- and is why it is the national half of the union rather than a
    sixth country in the filter.
    """
    return (
        CountryReading(identity=HomeCountry(), figure=a_figure("2.98461")),
        CountryReading(
            identity=Country(code="BH"), name="Bahrain", figure=a_figure("0.95395", "C-BH")
        ),
        CountryReading(
            identity=Country(code="SA"), name="Saudi Arabia", figure=a_figure("1.78409", "C-SA")
        ),
        CountryReading(
            identity=Country(code="KW"), name="Kuwait", figure=a_figure("1.98919", "C-KW")
        ),
        CountryReading(
            identity=Country(code="OM"), name="Oman", figure=a_figure("2.35183", "C-OM")
        ),
        CountryReading(
            identity=Country(code="SG"), name="Singapore", figure=a_figure("1.48481", "C-SG")
        ),
    )


def contents(composed: Composed) -> tuple[str, ...]:
    return tuple(placed.element.content for placed in composed.elements)


def classes(composed: Composed) -> tuple[ElementClass, ...]:
    return tuple(placed.element.element_class for placed in composed.elements)


# ------------------------------------------- 4.2 named countries filter, never expand


def test_naming_two_countries_gives_two_countries(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """F-001, as a test. The old system answered this exact question with six countries.

    Corpus e4-001: *"Compare Qatar's inflation with Singapore's."* The declared set holds
    six members; the question names two of them, and two is what comes back -- one as the
    national half of the union and one as the benchmark half, never the set they were
    drawn from.
    """
    home = aliases.groups[aliases.home_code][0]
    selection = select(
        Named(countries=frozenset({home, "Singapore"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(selection, Selection)
    assert selection.codes == frozenset({"SG"})
    assert selection.national is True
    assert selection.covered == 2
    assert selection.covered < len(a_declared_set().declared)


def test_a_named_country_never_expands_the_declared_set(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """FR-9. Japan is not a declared benchmark for this detail, so it is reported, not fetched."""
    selection = select(
        Named(countries=frozenset({"Singapore", "Japan"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(selection, Selection)
    assert selection.codes == frozenset({"SG"})
    assert selection.not_declared == ("Japan",)
    assert "JP" not in selection.codes


def test_naming_only_benchmarks_does_not_silently_add_the_national_half(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """The other direction of "filter, never expand", and it is a decision worth pinning.

    The home country is declared in all 21 sets, so it is tempting to always include it
    -- it is, after all, whose benchmark set this is. But adding a series the reader did
    not ask for is expansion, which is the thing this story forbids, and an answer that
    grows is as hard to defend as one that shrinks. It reaches the answer when the reader
    names it, and then as the national half rather than as a filter value: that is the
    part FR-11b is about, and it is asserted directly above.
    """
    selection = select(
        Named(countries=frozenset({"Oman", "Bahrain"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(selection, Selection)
    assert selection.national is False
    assert selection.codes == frozenset({"OM", "BH"})
    assert selection.covered == 2


def test_the_selection_is_a_union_of_a_national_half_and_a_benchmark_half(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """AD-5. Two fields of two different types, never one widened filter."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    assert selection.national is True
    assert selection.codes == frozenset({"BH", "SA", "KW", "OM", "SG"})
    assert selection.covered == len(a_declared_set().declared)


def test_no_selection_can_carry_the_home_country_as_a_filter_value(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """The structural half of AD-5, asserted on the value rather than on the code.

    ``HomeCountry`` has no ``code`` attribute, so ``filter_values`` has nothing to emit
    it from. The home country's code is in the declared set's own keying and is still
    absent from every filter this selection produces.
    """
    declaration = a_declared_set()
    home = aliases.home_code
    assert home in aliases.codes
    for scope in (
        DeclaredBenchmarks(),
        Named(countries=frozenset({"Singapore", "Bahrain"})),
        National(),
    ):
        selection = select(scope, declaration, aliases, rule_set)
        assert isinstance(selection, Selection)
        assert home not in selection.codes
    assert home not in declaration.codes
    assert home not in filter_values(declaration.declared)


def test_naming_the_home_country_reaches_the_national_half(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """A reader naming the country whose data this is is served by the query shape that
    has no country filter -- not by a filter value that would match none of 8,127 rows."""
    surface = aliases.groups[aliases.home_code][0]
    selection = select(
        Named(countries=frozenset({surface, "Singapore"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(selection, Selection)
    assert selection.national is True
    assert selection.codes == frozenset({"SG"})


def test_both_published_spellings_of_one_country_reach_one_identity(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """FACT 7. ``Korea`` and ``South Korea`` share a code, so either spelling is one member.

    Keyed by code, which collapses the duplicate by data rather than by opinion -- and a
    declared set carrying both spellings yields the country once.
    """
    declaration = Declaration(
        detail_id="D-TARIFF", declared=(HomeCountry(), Country(code="KR"))
    )
    for spelling in ("Korea", "South Korea"):
        selection = select(
            Named(countries=frozenset({spelling})), declaration, aliases, rule_set
        )
        assert isinstance(selection, Selection)
        assert selection.codes == frozenset({"KR"})
    both = select(
        Named(countries=frozenset({"Korea", "South Korea"})), declaration, aliases, rule_set
    )
    assert isinstance(both, Selection)
    assert both.codes == frozenset({"KR"})
    # The country is listed once, not twice -- collapsed at resolution, before any row is
    # fetched, because a set de-duplicated after the fetch has already shown it twice.
    assert both.covered == 1


def test_a_name_no_alias_group_claims_is_surfaced_rather_than_dropped(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """FR-110. An unknown name is a third thing, and is not folded into "not declared"."""
    selection = select(
        Named(countries=frozenset({"Singapore", "Freedonia"})),
        a_declared_set(),
        aliases,
        rule_set,
    )
    assert isinstance(selection, Selection)
    assert selection.unresolved == ("Freedonia",)
    assert selection.not_declared == ()


def test_the_fan_out_bound_is_read_from_the_rule_file(rule_set: RuleSet) -> None:
    """NFR-2 asks for a *stated* bound, so the selection carries it rather than a fetcher
    deciding one beside the set it bounds."""
    bound = fan_out_bound(rule_set)
    assert bound >= 1
    selection = select(
        DeclaredBenchmarks(), a_declared_set(), load_country_aliases(rule_set), rule_set
    )
    assert isinstance(selection, Selection)
    assert selection.fan_out == bound


def test_the_filter_switch_is_read_rather_than_assumed(rule_set: RuleSet) -> None:
    """A build whose rule file said a named country may expand would disagree with the
    code that filters, and the disagreement is raised rather than silently resolved."""
    assert named_countries_may_expand(rule_set) is False


def test_the_same_named_set_selects_the_same_way_on_every_run(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """AD-17. ``Named`` carries a frozenset, whose iteration order is not stable."""
    scope = Named(countries=frozenset({"Oman", "Bahrain", "Japan", "Chile"}))
    outcomes = [select(scope, a_declared_set(), aliases, rule_set) for _ in range(3)]
    first = outcomes[0]
    assert isinstance(first, Selection)
    assert all(one == first for one in outcomes)
    assert first.not_declared == ("Chile", "Japan")


# ------------------------------- 4.3 not a declared benchmark is not the same as no rows


def test_an_indicator_declaring_no_benchmarks_is_its_own_refusal(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """268 of 289 details are in this state, so it is the commonest thing the engine says."""
    outcome = select(
        DeclaredBenchmarks(), Declaration(detail_id="D-REAL-GDP"), aliases, rule_set
    )
    assert isinstance(outcome, NotComparable)
    assert outcome.refusal is SelectionRefusal.NO_DECLARED_SET


def test_naming_a_country_on_an_indicator_that_declares_none_says_so_first(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    """Corpus e4-006. Telling a reader that Japan is not a declared benchmark for an
    indicator that declares none at all answers a question they did not ask."""
    outcome = select(
        Named(countries=frozenset({"Japan"})),
        Declaration(detail_id="D-REAL-GDP"),
        aliases,
        rule_set,
    )
    assert isinstance(outcome, NotComparable)
    assert outcome.refusal is SelectionRefusal.NO_DECLARED_SET
    assert outcome.named == ("Japan",)


def test_naming_only_undeclared_countries_is_a_different_refusal(
    aliases: CountryAliases, rule_set: RuleSet
) -> None:
    outcome = select(
        Named(countries=frozenset({"Japan", "Chile"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(outcome, NotComparable)
    assert outcome.refusal is SelectionRefusal.NO_NAMED_COUNTRY_IS_DECLARED


def test_the_two_configuration_refusals_reach_a_reader_as_different_sentences(
    aliases: CountryAliases, rule_set: RuleSet, catalogue: Catalogue
) -> None:
    """Story 4.3's first half. Same shape, different message id, different words -- in
    both languages, because an engine that says one for both says the wrong one somewhere."""
    published = a_published_detail()
    no_set = select(
        Named(countries=frozenset({"Japan"})),
        Declaration(detail_id="D-REAL-GDP"),
        aliases,
        rule_set,
    )
    not_declared = select(
        Named(countries=frozenset({"Japan"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(no_set, NotComparable) and isinstance(not_declared, NotComparable)
    for lang in Lang:
        said = refusal_statement(no_set, published, catalogue, lang)
        other = refusal_statement(not_declared, published, catalogue, lang)
        assert said != other
        assert said.strip() and other.strip()


def test_declared_but_publishing_nothing_is_a_third_statement(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """Corpus e4-007 -- ``Total Population``, the one detail among the 21 declared sets
    with zero country rows. The configuration promises a comparison the data cannot
    supply, and that is a data gap, not a configuration gap."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    empty = tuple(
        CountryReading(identity=reading.identity, name=reading.name)
        for reading in the_inflation_readings()
    )
    composed = compare_countries(
        a_published_detail(), selection, empty, a_period(), catalogue, formatter, placement,
        Lang.EN,
    )
    assert composed.refused
    assert composed.reason is not None
    assert composed.elements == ()
    # The third statement, and it says something the other two cannot: the set exists and
    # the rows do not. Compared against the configuration refusal rather than merely
    # asserted non-empty, because "a refusal happened" is what the predecessor also did.
    configuration_gap = refusal_statement(
        NotComparable(detail_id="D-CPI-HEADLINE", refusal=SelectionRefusal.NO_DECLARED_SET),
        a_published_detail(),
        catalogue,
        Lang.EN,
    )
    assert composed.reason != configuration_gap
    assert catalogue.entry(Lang.AR, CompareMessage.NO_COUNTRY_ROWS_AT_ALL) is not None


# ------------------------------------------ 4.4 compare countries at a stated period


def test_the_comparison_states_the_period_it_compared_at(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """FR-22. A Council member is never shown countries silently measured at different times."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    composed = compare_countries(
        a_published_detail(), selection, the_inflation_readings(), a_period(), catalogue,
        formatter, placement, Lang.EN,
    )
    assert not composed.refused
    headline = composed.elements[0]
    assert headline.role is Role.SCOPE
    assert "Q1 2026" in headline.element.content


def test_the_home_country_appears_in_its_own_comparison(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """FR-11b. It is there, and it is there under the catalogue's phrase for national
    scope rather than under a name -- which is why no literal was needed to put it there."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    composed = compare_countries(
        a_published_detail(), selection, the_inflation_readings(), a_period(), catalogue,
        formatter, placement, Lang.EN,
    )
    national = catalogue.entry(Lang.EN, CompareMessage.NATIONAL)
    assert national is not None
    said = contents(composed)
    assert any("2.98" in line for line in said)
    assert sum(1 for line in said if "2.98" in line) == 1


def test_a_country_with_no_row_stays_in_the_list_as_a_stated_absence(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """Story 4.4's second clause, and the failure this epic is shaped around: a list that
    silently shortens reads exactly like a complete one."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    readings = the_inflation_readings()
    with_a_gap = (
        *readings[:-1],
        CountryReading(identity=Country(code="SG"), name="Singapore"),
    )
    composed = compare_countries(
        a_published_detail(), selection, with_a_gap, a_period(), catalogue, formatter,
        placement, Lang.EN,
    )
    said = contents(composed)
    assert any("Singapore" in line for line in said)
    assert ElementClass.ABSENT in classes(composed)
    assert len(with_a_gap) == len(readings)


def test_a_figure_from_another_period_becomes_the_absence_it_is() -> None:
    """The guard behind "a common period". A reading at 2025-Q4 is not evidence about
    2026-Q1, so it is not shown beside figures that are."""
    stale = CountryReading(
        identity=Country(code="SG"),
        name="Singapore",
        figure=a_figure("1.1", "C-SG", Period("2025-Q4")),
    )
    bound = at_period((stale,), a_period())
    assert bound[0].figure is None
    assert bound[0].identity == stale.identity
    assert bound[0].name == "Singapore"
    assert with_figures(bound) == ()


def test_the_narrowing_is_stated_when_the_answer_covers_less(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """FR-57. The reader is told, rather than left to count."""
    selection = select(
        Named(countries=frozenset({"Singapore", "Japan"})), a_declared_set(), aliases, rule_set
    )
    assert isinstance(selection, Selection)
    readings = (
        CountryReading(identity=HomeCountry(), figure=a_figure("2.98461")),
        CountryReading(
            identity=Country(code="SG"), name="Singapore", figure=a_figure("1.48481", "C-SG")
        ),
    )
    composed = compare_countries(
        a_published_detail(), selection, readings, a_period(), catalogue, formatter,
        placement, Lang.EN,
    )
    notes = [placed for placed in composed.elements if placed.role is Role.NOTE]
    assert notes
    assert any("Japan" in placed.element.content for placed in notes)


def test_nothing_is_narrated_as_narrowed_when_nothing_narrowed(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    composed = compare_countries(
        a_published_detail(), selection, the_inflation_readings(), a_period(), catalogue,
        formatter, placement, Lang.EN,
    )
    assert [placed for placed in composed.elements if placed.role is Role.NOTE] == []


def test_the_comparison_composes_in_arabic_from_the_catalogue(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, aliases: CountryAliases,
    rule_set: RuleSet,
) -> None:
    """It renders in Arabic because Arabic is authored beside it, not because an English
    sentence was translated at the edge."""
    selection = select(DeclaredBenchmarks(), a_declared_set(), aliases, rule_set)
    assert isinstance(selection, Selection)
    english = compare_countries(
        a_published_detail(), selection, the_inflation_readings(), a_period(), catalogue,
        formatter, placement, Lang.EN,
    )
    arabic = compare_countries(
        a_published_detail(), selection, the_inflation_readings(), a_period(), catalogue,
        formatter, placement, Lang.AR,
    )
    assert len(english.elements) == len(arabic.elements)
    assert contents(english) != contents(arabic)


# --------------------------------------- 4.5 compare indicators, each at its own period


def two_indicators() -> tuple[IndicatorReading, ...]:
    return (
        IndicatorReading(
            detail_id="D-CPI-HEADLINE",
            name="Inflation",
            asked=Period("2026-Q1"),
            figure=a_figure("2.98461", None, Period("2026-Q1")),
        ),
        IndicatorReading(
            detail_id="D-FDI-STOCK",
            name="FDI stock",
            asked=Period("2024"),
            figure=a_figure("27.596", None, Period("2024"), "D-FDI-STOCK"),
        ),
    )


def two_publications() -> dict[str, PublishedDetail]:
    return {
        "D-CPI-HEADLINE": a_published_detail(),
        "D-FDI-STOCK": PublishedDetail(
            detail_id="D-FDI-STOCK",
            name="FDI stock",
            unit="bn USD",
            value_format="0.0",
            source_id="S-MOCI-FDI",
        ),
    }


def test_each_indicator_is_shown_at_its_own_period(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    """FR-24. No false alignment is forced: the periods differ and they are both shown."""
    composed = compare_indicators(
        two_indicators(), two_publications(), catalogue, formatter, placement, Lang.EN
    )
    said = " ".join(contents(composed))
    assert "Q1 2026" in said
    assert "2024" in said


def test_a_reading_reads_its_period_off_its_own_figure() -> None:
    """Structural, not careful. There is nowhere to put another indicator's period."""
    inflation, fdi = two_indicators()
    assert inflation.period == Period("2026-Q1")
    assert fdi.period == Period("2024")
    empty = IndicatorReading(detail_id="D-X", name="X", asked=Period("2025"))
    assert empty.period is None


def test_a_reading_cannot_carry_another_indicators_figure() -> None:
    with pytest.raises(ValueError, match="one row"):
        IndicatorReading(
            detail_id="D-CPI-HEADLINE",
            name="Inflation",
            asked=a_period(),
            figure=a_figure("1.0", None, a_period(), "D-FDI-STOCK"),
        )


def test_differing_units_are_stated_rather_than_reconciled(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    """FR-47. Each is rendered in its own published unit and the answer says they are not
    directly comparable; nothing is converted or normalised."""
    readings, publications = two_indicators(), two_publications()
    assert units_differ(readings, publications)
    composed = compare_indicators(
        readings, publications, catalogue, formatter, placement, Lang.EN
    )
    said = " ".join(contents(composed))
    assert "%" in said
    assert "bn USD" in said
    assert any(placed.role is Role.NOTE for placed in composed.elements)


def test_one_unit_across_the_indicators_attaches_no_caveat(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    publications = two_publications()
    publications["D-FDI-STOCK"] = PublishedDetail(
        detail_id="D-FDI-STOCK",
        name="FDI stock",
        unit="%",
        value_format="0.0",
        source_id="S-MOCI-FDI",
    )
    composed = compare_indicators(
        two_indicators(), publications, catalogue, formatter, placement, Lang.EN
    )
    assert [placed for placed in composed.elements if placed.role is Role.NOTE] == []


def test_an_indicator_that_published_nothing_stays_in_the_comparison(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    readings = (
        two_indicators()[0],
        IndicatorReading(detail_id="D-FDI-STOCK", name="FDI stock", asked=Period("2024")),
    )
    composed = compare_indicators(
        readings, two_publications(), catalogue, formatter, placement, Lang.EN
    )
    assert ElementClass.ABSENT in classes(composed)
    assert any("FDI stock" in line for line in contents(composed))


def test_an_indicator_with_no_publication_is_refused_rather_than_half_composed(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    with pytest.raises(KeyError):
        compare_indicators(
            two_indicators(), {"D-CPI-HEADLINE": a_published_detail()}, catalogue, formatter,
            placement, Lang.EN,
        )


# ------------------------------------------------- 4.6 superlatives name what carries them


def inflation_candidates() -> tuple[Candidate, ...]:
    return (
        Candidate(label="National", figure=a_figure("2.98461")),
        Candidate(label="Bahrain", figure=a_figure("0.95395", "C-BH")),
        Candidate(label="Saudi Arabia", figure=a_figure("1.78409", "C-SA")),
        Candidate(label="Kuwait", figure=a_figure("1.98919", "C-KW")),
        Candidate(label="Oman", figure=a_figure("2.35183", "C-OM")),
        Candidate(label="Singapore", figure=a_figure("1.48481", "C-SG")),
    )


def test_a_superlative_names_the_country_and_the_period_that_carry_it(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    """FR-25 and corpus e4-003. F-027 was answering "which country" with one country's
    historical low, engaging no country dimension at all."""
    composed = extremum(
        inflation_candidates(), Direction.LOWEST, Scope.COUNTRIES, a_published_detail(),
        catalogue, formatter, placement, Lang.EN,
    )
    said = composed.elements[0].element.content
    assert "Bahrain" in said
    assert "1.0" in said
    assert "Q1 2026" in said


def test_the_name_leads_the_answer_and_the_figure_follows(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    """FR-58: the answer to a "which" question is a name, not a number."""
    composed = extremum(
        inflation_candidates(), Direction.HIGHEST, Scope.COUNTRIES, a_published_detail(),
        catalogue, formatter, placement, Lang.EN,
    )
    said = composed.elements[0].element.content
    assert said.index("National") < said.index("3.0")


def test_a_superlative_over_periods_is_not_presented_as_one_over_countries(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    """R-166, as two sentences rather than one with a hole in it."""
    over_periods = (
        Candidate(label="Q1 2026", figure=a_figure("2.98461")),
        Candidate(label="Q4 2025", figure=a_figure("2.10", None, Period("2025-Q4"))),
    )
    countries = extremum(
        inflation_candidates(), Direction.HIGHEST, Scope.COUNTRIES, a_published_detail(),
        catalogue, formatter, placement, Lang.EN,
    )
    periods = extremum(
        over_periods, Direction.HIGHEST, Scope.PERIODS, a_published_detail(), catalogue,
        formatter, placement, Lang.EN,
    )
    assert contents(countries)[0] != contents(periods)[0]


def test_the_published_polarity_decides_what_best_means(rule_set: RuleSet) -> None:
    """FR-25. On an indicator whose polarity is ``Decrease`` the best figure is the lowest."""
    assert best_direction("Increase", rule_set) is Direction.HIGHEST
    assert best_direction("Decrease", rule_set) is Direction.LOWEST
    assert best_direction(" decrease ", rule_set) is Direction.LOWEST


def test_an_unpublished_polarity_yields_no_direction_rather_than_a_guess(
    rule_set: RuleSet,
) -> None:
    """Higher-is-better is simply false on a rank, so there is no safe default."""
    assert best_direction(None, rule_set) is None
    assert best_direction("", rule_set) is None
    assert best_direction("Sideways", rule_set) is None


def test_an_answer_with_no_published_direction_states_the_one_it_used(
    catalogue: Catalogue, formatter: Formatter, placement: Placement
) -> None:
    composed = extremum(
        inflation_candidates(), Direction.HIGHEST, Scope.COUNTRIES, a_published_detail(),
        catalogue, formatter, placement, Lang.EN, direction_was_published=False,
    )
    notes = [placed for placed in composed.elements if placed.role is Role.NOTE]
    assert len(notes) == 1
    assert "higher" in notes[0].element.content


def test_one_ordering_stands_behind_the_superlative_and_the_rank(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """F-015 and finding 43: a figure composed once and then quietly recomputed.

    The superlative's carrier and the first place in the ranking are the same country
    because both read one ``ordered()``, not because two computations agreed.
    """
    candidates = inflation_candidates()
    placed = ordered(candidates, Direction.LOWEST)
    top = extremum(
        candidates, Direction.LOWEST, Scope.COUNTRIES, a_published_detail(), catalogue,
        formatter, placement, Lang.EN,
    )
    assert placed[0].label == "Bahrain"
    assert placed[0].label in top.elements[0].element.content


def test_an_ordering_is_stable_across_equal_figures() -> None:
    """AD-17. Two equal figures swapping places between processes is an answer a QC
    tester cannot diff against yesterday's."""
    tied = (
        Candidate(label="Oman", figure=a_figure("2.0", "C-OM")),
        Candidate(label="Kuwait", figure=a_figure("2.0", "C-KW")),
    )
    assert [one.label for one in ordered(tied, Direction.HIGHEST)] == ["Oman", "Kuwait"]
    assert [one.label for one in ordered(tied[::-1], Direction.HIGHEST)] == ["Oman", "Kuwait"]


def test_an_unnamed_candidate_is_refused(catalogue: Catalogue) -> None:
    with pytest.raises(ValueError, match="names what carries it"):
        Candidate(label="  ", figure=a_figure("1.0"))


# ------------------------------------------------------------- 4.7 ranks are ordinals


def a_rank_detail() -> PublishedDetail:
    return PublishedDetail(
        detail_id="D-GII-RANK",
        name="Global Innovation Index Rank",
        unit="Rank",
        value_format="",
        source_id="S-WIPO-GII",
    )


def rank_candidates() -> tuple[Candidate, ...]:
    """Corpus e4-004's 2025 rows. The polarity is ``Decrease``: a lower rank is better."""
    return (
        Candidate(label="National", figure=a_figure("48", None, Period("2025"), "D-GII-RANK")),
        Candidate(label="UAE", figure=a_figure("30", "C-AE", Period("2025"), "D-GII-RANK")),
        Candidate(
            label="Saudi Arabia", figure=a_figure("46", "C-SA", Period("2025"), "D-GII-RANK")
        ),
        Candidate(label="Bahrain", figure=a_figure("62", "C-BH", Period("2025"), "D-GII-RANK")),
        Candidate(label="Oman", figure=a_figure("69", "C-OM", Period("2025"), "D-GII-RANK")),
        Candidate(label="Kuwait", figure=a_figure("73", "C-KW", Period("2025"), "D-GII-RANK")),
    )


def test_a_rank_is_rendered_as_an_ordinal(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-26. A 3rd place does not arrive as the number 3 in a unit that is not a unit."""
    composed = ranking(
        rank_candidates(), "National", Direction.LOWEST, a_rank_detail(), catalogue,
        formatter, placement, rule_set, Lang.EN,
    )
    assert not composed.refused
    said = composed.elements[0].element.content
    assert "3rd" in said
    assert "National" in said


def test_the_rank_respects_the_published_polarity(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """A lower published rank is better, so the home country's 48 places it third of six
    rather than fourth from the other end."""
    placed = ordered(rank_candidates(), Direction.LOWEST)
    assert [one.label for one in placed][:3] == ["UAE", "Saudi Arabia", "National"]


def test_ranks_render_as_ordinals_in_arabic_too(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-62. Arabic ordinal forms come from the bilingual catalogue, not from a suffix
    rule that would generate fluent English and broken Arabic."""
    english = ranking(
        rank_candidates(), "National", Direction.LOWEST, a_rank_detail(), catalogue,
        formatter, placement, rule_set, Lang.EN,
    )
    arabic = ranking(
        rank_candidates(), "National", Direction.LOWEST, a_rank_detail(), catalogue,
        formatter, placement, rule_set, Lang.AR,
    )
    assert contents(english) != contents(arabic)
    assert ordinal(3, Role.HEADLINE, catalogue, formatter, placement, rule_set, Lang.AR) != (
        ordinal(3, Role.HEADLINE, catalogue, formatter, placement, rule_set, Lang.EN)
    )


@pytest.mark.parametrize("position", [1, 2, 3, 10])
def test_every_authored_position_has_a_word_in_both_languages(
    position: int, catalogue: Catalogue, formatter: Formatter, placement: Placement,
    rule_set: RuleSet,
) -> None:
    for lang in Lang:
        written = ordinal(position, Role.HEADLINE, catalogue, formatter, placement, rule_set, lang)
        assert written.strip()


def test_a_position_past_the_authored_list_falls_to_the_numbered_form(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """The fallback is correct at every value rather than a gap: a suffix rule stopping
    at ten produces "21th"."""
    beyond = named_positions(rule_set) + 1
    written = ordinal(beyond, Role.HEADLINE, catalogue, formatter, placement, rule_set, Lang.EN)
    assert str(beyond) in written
    assert catalogue.entry(Lang.AR, OrdinalMessage.BEYOND) is not None


def test_a_position_is_counted_from_one(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    with pytest.raises(ValueError, match="counted from one"):
        ordinal(0, Role.HEADLINE, catalogue, formatter, placement, rule_set, Lang.EN)


def test_an_indicator_that_publishes_no_ranking_is_refused_not_computed(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """Ranking reaches 12 of 189 indicators. On the other 177 the answer says so; it does
    not order the rows it happens to hold and present the result as a rank."""
    composed = ranking(
        inflation_candidates(), "Bahrain", Direction.LOWEST, a_published_detail(), catalogue,
        formatter, placement, rule_set, Lang.EN,
    )
    assert composed.refused
    assert composed.reason is not None
    assert composed.elements == ()


def test_a_rank_is_never_rendered_with_a_decimal_or_a_percent_sign(
    formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """``Rank`` is one of the 28 published units and it governs: ``11.00 Rank`` is the
    defect this clause records."""
    written = formatter.format(
        Decimal(11),
        rank_format(rule_set),
        placement.mode_for(Role.HEADLINE),
        Lang.EN,
    )
    assert written.value == "11"
    assert "." not in written.value
    assert "%" not in written.value


def test_a_subject_outside_the_scope_has_no_place_in_it(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    with pytest.raises(ValueError, match="not one of the candidates"):
        ranking(
            rank_candidates(), "Freedonia", Direction.LOWEST, a_rank_detail(), catalogue,
            formatter, placement, rule_set, Lang.EN,
        )


def test_the_subject_is_matched_through_the_single_fold(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """AD-26. A trailing space between the label and the name being asked about would
    otherwise read as a country that is not in its own comparison."""
    composed = ranking(
        rank_candidates(), "  national  ", Direction.LOWEST, a_rank_detail(), catalogue,
        formatter, placement, rule_set, Lang.EN,
    )
    assert not composed.refused
    assert "3rd" in composed.elements[0].element.content


# --------------------------------------------------------- 4.8 spread between extrema


def test_a_spread_names_both_endpoints(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-27 and corpus e4-005. A spread is checkable rather than a bare number."""
    composed = spread(
        inflation_candidates(), a_published_detail(), catalogue, formatter, placement,
        rule_set, Lang.EN,
    )
    said = composed.elements[0].element.content
    assert "National" in said
    assert "Bahrain" in said
    assert "3.0" in said
    assert "1.0" in said


def test_a_spread_over_a_percentage_indicator_is_in_points(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-21. 2.98 against 0.95 is a gap of 2.0 pp, and 2.0 % is a different quantity."""
    composed = spread(
        inflation_candidates(), a_published_detail(), catalogue, formatter, placement,
        rule_set, Lang.EN,
    )
    assert "pp" in composed.elements[0].element.content


def test_the_points_come_from_an_actual_subtraction_of_two_percentages() -> None:
    """The type says so, and it says so because ``Percent - Percent`` was performed --
    not because a unit string was swapped on the way out (AD-4)."""
    gap = difference(Decimal("2.98461"), Decimal("0.95395"), measured_in_percent=True)
    assert isinstance(gap, PercentagePoints)
    assert gap == Percent(Decimal("2.98461")) - Percent(Decimal("0.95395"))


def test_a_spread_over_a_non_percentage_indicator_keeps_the_published_unit(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    published = PublishedDetail(
        detail_id="D-FDI-STOCK", name="FDI stock", unit="bn USD", value_format="0.0",
        source_id="S-MOCI-FDI",
    )
    candidates = (
        Candidate(label="National", figure=a_figure("27.596", None, Period("2024"))),
        Candidate(label="UAE", figure=a_figure("270.619", "C-AE", Period("2024"))),
    )
    composed = spread(
        candidates, published, catalogue, formatter, placement, rule_set, Lang.EN
    )
    said = composed.elements[0].element.content
    assert "bn USD" in said
    assert "pp" not in said


def test_a_spread_is_derived_and_states_its_two_input_rows(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-19, AD-4. The element's single ``source_ref`` has nowhere to carry two rows, so
    they travel on ``row_ids`` and both endpoints are named in the content."""
    composed = spread(
        inflation_candidates(), a_published_detail(), catalogue, formatter, placement,
        rule_set, Lang.EN,
    )
    assert classes(composed) == (ElementClass.DERIVED,)
    assert len(composed.row_ids) == 2
    assert len(set(composed.row_ids)) == 2


def test_a_scope_with_one_value_has_no_spread(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    composed = spread(
        inflation_candidates()[:1], a_published_detail(), catalogue, formatter, placement,
        rule_set, Lang.EN,
    )
    assert composed.refused
    assert composed.elements == ()


def test_a_spread_run_the_wrong_way_round_is_refused() -> None:
    """Returning it would put a minus sign in front of a distance in an answer."""
    with pytest.raises(ValueError, match="wrong way round"):
        difference(Decimal(1), Decimal(2), measured_in_percent=False)


# ------------------------------------------------------------------ the composed shape


def test_a_composition_carries_elements_or_a_reason_and_never_both() -> None:
    with pytest.raises(ValueError, match="never both and never"):
        Composed()


def test_a_reading_for_the_home_country_carries_no_name() -> None:
    """The literal is banned everywhere under ``src/askai/``, and this is why it never
    needed to be written: there is nowhere on the type to put it."""
    with pytest.raises(ValueError, match="no country name"):
        CountryReading(identity=HomeCountry(), name="Somewhere")


def test_a_benchmark_reading_without_a_name_is_refused() -> None:
    with pytest.raises(ValueError, match="no published name"):
        CountryReading(identity=Country(code="SG"))


def test_a_national_reading_cannot_carry_a_country_row() -> None:
    with pytest.raises(ValueError, match="rows with no country value"):
        CountryReading(identity=HomeCountry(), figure=a_figure("1.0", "C-SG"))


def test_a_country_reading_cannot_carry_the_national_row() -> None:
    with pytest.raises(ValueError, match="different rows"):
        CountryReading(identity=Country(code="SG"), name="Singapore", figure=a_figure("1.0"))


def test_a_declaration_belongs_to_a_detail() -> None:
    with pytest.raises(ValueError, match="needs the detail"):
        Declaration(detail_id="  ")


# ------------------------------------------- every id this package names exists in both


def test_every_message_id_this_package_names_exists_in_both_languages(
    catalogue: Catalogue,
) -> None:
    """The half of the catalogue check the loader cannot do for us.

    ``load_catalogue`` refuses a catalogue whose halves disagree, so an id present in one
    language and not the other already stops startup. What it cannot know is whether an
    id a *composer* names exists at all -- a typo there renders as a raised lookup on the
    one question nobody tried, which is a refusal wearing a crash's clothes.
    """
    named = [
        value
        for holder in (CompareMessage, IndicatorMessage, ExtremumMessage, OrdinalMessage)
        for name, value in vars(holder).items()
        if not name.startswith("_") and isinstance(value, str)
    ]
    assert named
    for message_id in named:
        for lang in Lang:
            assert catalogue.entry(lang, message_id) is not None, (
                f"{message_id} is named by a composer and is not in the {lang.value} "
                "catalogue"
            )


def test_the_authored_ordinals_run_from_one_with_no_gaps(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """A gap would render as a raised lookup at exactly one position in one language."""
    for position in range(1, named_positions(rule_set) + 1):
        for lang in Lang:
            assert catalogue.entry(lang, OrdinalMessage.at(position)) is not None


def test_today_is_not_read_by_any_composition_here() -> None:
    """AD-17, trivially: nothing in this package takes a clock or a date, so the same
    readings compose the same answer on every run. Asserted so it stops being trivial
    loudly rather than quietly."""
    source = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PACKAGE_ROOT / "assemble" / "compare").rglob("*.py"))
    )
    assert "datetime" not in source
    assert "date.today" not in source
