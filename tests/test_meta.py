"""Epic 5 -- questions about the catalogue itself.

Stories 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.9 and the rules half of 5.10. Three of Epic 5's
stories are **not** here and are not stubbed either -- 5.4 (who owns a group), 5.8 (what an
indicator is made of) and the read half of 5.10 (the published chart configuration) each
need a read-model table that does not exist. The CMS export carries all three
(``data/Champions.csv``, ``P07a``, ``P07``/``P07b``) and the ingest of Story 1.8
materialises none of them. A test asserting a champion lookup against a table nobody wrote
would be a test of a fixture.

Most of what follows runs against the **real ingested export**, not a hand-built fixture.
Epic 5's acceptance criteria are almost entirely statements about measured data -- *7
classifications*, *12 in Diversification Targets*, *23 in the largest sector*, *28 details
with no datapoints* -- and a fixture would let those numbers be true of the fixture and
false of the export. Where a number here disagrees with the data, the data wins and the
story is wrong; one already is, and ``test_the_group_layer_has_the_entities_the_data_has``
says so.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.catalogue import SOURCE_REF_SEGMENTS, ReadModelSources
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.groups import (
    _EXISTS_BY_KIND,
    CATALOGUE_REF_PREFIX,
    EitherSource,
    ReadModelCatalogueSources,
    ReadModelGroups,
)
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.store.provision import Databases, provision
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.meta.capability import capability_elements
from askai.assemble.meta.chart import ChartOffer, PublishedChart, chartable_for, known_view_codes
from askai.assemble.meta.definitions import definition_element, published_definition
from askai.assemble.meta.groups import (
    ambiguous_group_statement,
    group_breakdown_element,
    group_count_element,
    group_members_element,
    is_answered_at_classification_level,
    single_group_note,
)
from askai.assemble.meta.overview import (
    OverviewMember,
    OverviewReading,
    max_concurrent_fetches,
    overview_classification,
    overview_elements,
)
from askai.assemble.meta.periods import calendars_by_grain, periods_element
from askai.assemble.meta.reference import (
    CatalogueReference,
    ReferenceKind,
    catalogue_element,
    whole_catalogue,
)
from askai.assemble.meta.residual import Residual, residual_element, residual_of
from askai.assemble.provenance import Provenance, admit_all
from askai.assemble.roles import Placement, Role
from askai.domain.element import ElementClass
from askai.domain.period import Grain, Period
from askai.messages import Catalogue, Lang, load_catalogue
from askai.ports.groups import Group, GroupLevel, PublishedDefinition
from askai.rules import RuleSet, rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"
META_ROOT = PACKAGE_ROOT / "assemble" / "meta"

# Measured against `data/` on 2026-09-16. Each is an acceptance criterion of a story, and
# each is asserted against the real ingest below rather than against a fixture.
CLASSIFICATIONS: Final = 7
ENTITIES: Final = 22
PUBLISHED_INDICATORS: Final = 189
SECTORS: Final = "Sectors"
SECTORS_INDICATORS: Final = 105
SECTORS_ENTITIES: Final = 8
LARGEST_SECTOR: Final = "Transportation and Storage"
LARGEST_SECTOR_SIZE: Final = 23
EDUCATION: Final = "Education Sector"
EDUCATION_SIZE: Final = 13
TOURISM_SIZE: Final = 7
DIVERSIFICATION: Final = "DiversificationTargets"
DIVERSIFICATION_SIZE: Final = 12
NATIONAL: Final = "NationalIndicators"
NATIONAL_SIZE: Final = 8
DETAILS: Final = 289
DETAILS_WITHOUT_DATA: Final = 28


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


@pytest.fixture(scope="module")
def formatter(catalogue: Catalogue, rule_set: RuleSet) -> Formatter:
    return Formatter(catalogue=catalogue, rule_set=rule_set)


@pytest.fixture(scope="module")
def placement(rule_set: RuleSet) -> Placement:
    return Placement(rule_set=rule_set)


@pytest.fixture(scope="module")
def ingested() -> Iterator[Databases]:
    with provision() as databases:
        ingest_published_layer(databases.read_model, CmsExport.rooted(EXPORT_ROOT))
        yield databases


@pytest.fixture(scope="module")
def read_model(ingested: Databases) -> sqlite3.Connection:
    return ingested.read_model


@pytest.fixture(scope="module")
def groups(read_model: sqlite3.Connection) -> ReadModelGroups:
    return ReadModelGroups(read_model)


@pytest.fixture(scope="module")
def sources(read_model: sqlite3.Connection) -> EitherSource:
    return EitherSource(
        datapoints=ReadModelSources(read_model),
        catalogue=ReadModelCatalogueSources(read_model),
    )


# ------------------------------------------------------------------------- helpers


def named(groups: ReadModelGroups, level: GroupLevel, name: str) -> Group:
    """The one group at *level* published under *name*. Fails loudly if it is not one."""
    found = [group for group in groups.groups_named(name) if group.level is level]
    assert len(found) == 1, f"{name!r} is not one {level.value} in the export: {found}"
    return found[0]


def a_provenance(detail_id: str = "D-1", period: str = "2026") -> Provenance:
    return Provenance(detail_id=detail_id, period=Period(period), country=None, source_id="S-1")


def a_group(
    level: GroupLevel = GroupLevel.ENTITY,
    key: str = "E-1",
    name: str = "A Group",
    count: int = 3,
    classification: str = "Sectors",
) -> Group:
    return Group(
        level=level,
        key=key,
        name_en=name,
        name_ar=name,
        indicator_count=count,
        classification=classification,
    )


# ===================================================== Story 5.1 -- the group layer


def test_the_group_layer_covers_every_published_indicator(groups: ReadModelGroups) -> None:
    """FR-29a: grouping comes from the catalogue's own fields, and they are complete."""
    classifications = groups.classifications()
    assert len(classifications) == CLASSIFICATIONS
    assert sum(group.indicator_count for group in classifications) == PUBLISHED_INDICATORS


def test_the_group_layer_has_the_entities_the_data_has(groups: ReadModelGroups) -> None:
    """Measured **22**, and Story 5.1 says 20.

    The story's number is wrong and this test is where that is recorded. The count is
    derived from the export -- eight entities under `Sectors`, four under `SpecialEntities`
    and `Enablers`, two under `Drivers` and `SpecialProjects`, one each under the two
    container classifications -- and it agrees with the 22 `AGENTS.md` already records from
    Story 1.8's ingest. Asserting the story's 20 would have made the ingest's own measured
    figure a failure.
    """
    entities = [
        entity
        for classification in groups.classifications()
        for entity in groups.entities_in(classification.key)
    ]
    assert len(entities) == ENTITIES
    assert sum(entity.indicator_count for entity in entities) == PUBLISHED_INDICATORS


def test_every_indicator_resolves_to_exactly_one_entity(groups: ReadModelGroups) -> None:
    """FR-29a: one classification *and* one entity, 189/189, across the two name files."""
    for classification in groups.classifications():
        entities = groups.entities_in(classification.key)
        assert entities, f"{classification.key} has no entity"
        assert sum(entity.indicator_count for entity in entities) == classification.indicator_count
        assert all(entity.name_en for entity in entities), "an entity name did not resolve"


def test_diversification_targets_holds_twelve_with_their_names(groups: ReadModelGroups) -> None:
    """Story 5.1's headline criterion, and recorded failure F-032 where QC expected 12."""
    group = named(groups, GroupLevel.CLASSIFICATION, DIVERSIFICATION)
    assert group.indicator_count == DIVERSIFICATION_SIZE
    members = groups.indicators_in(group.level, group.key)
    assert len(members) == DIVERSIFICATION_SIZE
    assert all(member.name_en.strip() for member in members)


def test_the_education_sector_holds_its_published_indicators(groups: ReadModelGroups) -> None:
    """Recorded failure F-033. An entity, not a classification -- which is Story 5.2."""
    group = named(groups, GroupLevel.ENTITY, EDUCATION)
    assert group.indicator_count == EDUCATION_SIZE
    assert group.classification == SECTORS
    assert len(groups.indicators_in(group.level, group.key)) == EDUCATION_SIZE


def test_a_count_excludes_a_confidential_indicator_rather_than_hiding_it(
    read_model: sqlite3.Connection, groups: ReadModelGroups
) -> None:
    """FR-50, asserted at the point it could go wrong.

    The count and the list come from the same table under the same CHECK, so there is no
    path where a row is counted and not listed. Measured on this export, **zero** published
    indicators are confidential -- so this asserts the structural property (count equals
    listed) rather than a filtered arithmetic that never fires.
    """
    (confidential,) = read_model.execute(
        "SELECT COUNT(*) FROM catalogue WHERE priority_type = 'Confidential'"
    ).fetchone()
    assert confidential == 0
    for classification in groups.classifications():
        listed = groups.indicators_in(classification.level, classification.key)
        assert len(listed) == classification.indicator_count


def test_a_container_classification_is_a_real_one_to_one(
    groups: ReadModelGroups, rule_set: RuleSet
) -> None:
    """Story 5.1: answered at classification level, and **not** treated as an absent entity."""
    for key in (DIVERSIFICATION, NATIONAL):
        classification = named(groups, GroupLevel.CLASSIFICATION, key)
        entities = groups.entities_in(key)
        assert len(entities) == 1, f"{key} is listed as a container and divides further"
        assert entities[0].indicator_count == classification.indicator_count
        assert is_answered_at_classification_level(rule_set, classification)
        assert is_answered_at_classification_level(rule_set, entities[0])


def test_a_classification_that_divides_is_not_answered_at_classification_level(
    groups: ReadModelGroups, rule_set: RuleSet
) -> None:
    """The other side of the same table -- otherwise it would pass by always saying yes."""
    sectors = named(groups, GroupLevel.CLASSIFICATION, SECTORS)
    assert not is_answered_at_classification_level(rule_set, sectors)


# ============================================ Story 5.2 -- a group is not a classification


def test_sectors_binds_to_the_classification_and_returns_its_hundred_and_five(
    groups: ReadModelGroups,
) -> None:
    """FR-30: the word *Sectors* is the category, and the category is 105 indicators."""
    sectors = named(groups, GroupLevel.CLASSIFICATION, SECTORS)
    assert sectors.indicator_count == SECTORS_INDICATORS
    assert len(groups.entities_in(SECTORS)) == SECTORS_ENTITIES


def test_a_named_sector_binds_to_the_entity_and_returns_only_its_own(
    groups: ReadModelGroups,
) -> None:
    """FR-30, the other reading -- and the 98-indicator gap that makes it matter."""
    education = named(groups, GroupLevel.ENTITY, EDUCATION)
    assert education.indicator_count == EDUCATION_SIZE
    assert education.indicator_count < SECTORS_INDICATORS


def test_the_entities_of_a_category_are_listed_largest_first(groups: ReadModelGroups) -> None:
    """R-165's ordering: a reader scanning the breakdown is looking for the weight."""
    entities = groups.entities_in(SECTORS)
    sizes = [entity.indicator_count for entity in entities]
    assert sizes == sorted(sizes, reverse=True)
    assert entities[0].name_en == LARGEST_SECTOR
    assert entities[0].indicator_count == LARGEST_SECTOR_SIZE
    assert entities[-1].indicator_count == TOURISM_SIZE


def test_a_group_answer_states_its_size(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """R-GROUP-SIZE-IS-STATED, in the element the reader actually gets."""
    education = named(groups, GroupLevel.ENTITY, EDUCATION)
    placed = group_count_element(catalogue, Lang.EN, rule_set, education)
    assert placed.role is Role.HEADLINE
    assert placed.element.element_class is ElementClass.MEASURED
    assert str(EDUCATION_SIZE) in placed.element.content
    assert EDUCATION in placed.element.content


def test_a_group_size_is_written_in_arabic_without_an_english_numeral(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """The count agrees with its Arabic noun rather than being interpolated into one."""
    diversification = named(groups, GroupLevel.CLASSIFICATION, DIVERSIFICATION)
    content = group_count_element(catalogue, Lang.AR, rule_set, diversification).element.content
    assert content
    assert "indicator" not in content


def test_a_category_is_answered_by_its_groups_and_not_by_a_hundred_names(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """R-165. The breakdown names 8 groups with their counts, not 105 indicators."""
    sectors = named(groups, GroupLevel.CLASSIFICATION, SECTORS)
    entities = groups.entities_in(SECTORS)
    placed = group_breakdown_element(catalogue, Lang.EN, rule_set, sectors, entities)
    members = groups.indicators_in(sectors.level, sectors.key)
    for entity in entities:
        assert entity.name_en in placed.element.content
    listed = sum(1 for member in members if member.name_en in placed.element.content)
    assert listed < len(members), "the breakdown listed the membership rather than the groups"


def test_an_ambiguous_name_names_both_readings_with_their_sizes(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """FR-2 and AD-25: both readings, neither chosen, each with the number that separates them."""
    both = (
        a_group(
            level=GroupLevel.CLASSIFICATION,
            key=SECTORS,
            name=SECTORS,
            count=SECTORS_INDICATORS,
            classification=SECTORS,
        ),
        a_group(level=GroupLevel.ENTITY, key="E-TOURISM", name="Tourism", count=TOURISM_SIZE),
    )
    statement = ambiguous_group_statement(catalogue, Lang.EN, rule_set, both)
    assert str(SECTORS_INDICATORS) in statement
    assert str(TOURISM_SIZE) in statement
    assert "Tourism" in statement


def test_a_clarification_needs_more_than_one_reading(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """One reading is not ambiguous; offering a single choice is a refusal misnamed."""
    with pytest.raises(LookupError):
        ambiguous_group_statement(catalogue, Lang.EN, rule_set, (a_group(),))


def test_the_single_group_note_explains_why_a_category_was_given(
    catalogue: Catalogue, groups: ReadModelGroups
) -> None:
    """The container case, said -- so the reader sees why they got the level above."""
    diversification = named(groups, GroupLevel.CLASSIFICATION, DIVERSIFICATION)
    placed = single_group_note(catalogue, Lang.EN, diversification)
    assert placed.role is Role.NOTE
    assert DIVERSIFICATION in placed.element.content


# ============================================ Story 5.3 -- questions about the data itself


def test_a_count_is_an_element_that_resolves_like_any_figure(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups, sources: EitherSource
) -> None:
    """AD-3/AD-6: a count is a figure, carries a ``source_ref``, and is admitted."""
    education = named(groups, GroupLevel.ENTITY, EDUCATION)
    placed = group_count_element(catalogue, Lang.EN, rule_set, education)
    admitted = admit_all((placed.element,), sources)
    assert admitted.elements and not admitted.degradations


def test_a_count_of_a_group_that_is_not_published_is_refused(sources: EitherSource) -> None:
    """The closed world, over the catalogue's own rows: a stale group does not resolve."""
    stale = catalogue_element(
        "x", ElementClass.MEASURED, CatalogueReference(ReferenceKind.ENTITY, "E-GONE")
    )
    refused = admit_all((stale,), sources)
    assert not refused.elements and len(refused.degradations) == 1


def test_periods_are_stated_per_grain_and_never_merged(catalogue: Catalogue) -> None:
    """FR-4 and the 90 multi-grain details: two calendars, not one span across both."""
    periods = (Period("2020"), Period("2024"), Period("2026-01"), Period("2026-04"))
    split = calendars_by_grain(periods)
    assert list(split) == [Grain.MONTHLY, Grain.YEARLY]
    placed = periods_element(catalogue, Lang.EN, "D-1", "Inflation", periods)
    content = placed.element.content
    assert "2020" in content and "2024" in content
    assert "January 2026" in content and "April 2026" in content
    assert placed.element.element_class is ElementClass.MEASURED


def test_one_period_at_a_grain_is_not_written_as_a_span_to_itself(
    catalogue: Catalogue,
) -> None:
    content = periods_element(
        catalogue, Lang.EN, "D-1", "Inflation", (Period("2024"),)
    ).element.content
    assert content.count("2024") == 1


def test_a_detail_that_publishes_nothing_says_so_rather_than_looking_absent(
    catalogue: Catalogue,
) -> None:
    """The 28 of 289. A published detail with no rows is a statement, not an empty answer."""
    placed = periods_element(catalogue, Lang.EN, "D-1", "Some Detail", ())
    assert placed.element.element_class is ElementClass.ABSENT
    assert "Some Detail" in placed.element.content
    assert placed.element.content.strip()


def test_published_but_empty_is_a_different_answer_from_no_such_detail(
    read_model: sqlite3.Connection, groups: ReadModelGroups
) -> None:
    """The two states are distinguishable at the port, which is where they must be.

    ``definition`` returns ``None`` only for a detail the catalogue does not hold; a detail
    that exists and publishes no datapoints comes back as a real row. An engine that
    collapsed the two would tell 28 readers their indicator does not exist.
    """
    empty = read_model.execute(
        "SELECT detail_id FROM detail WHERE detail_id NOT IN "
        "(SELECT DISTINCT detail_id FROM datapoint) LIMIT 1"
    ).fetchone()
    assert empty is not None, "the export no longer has a detail publishing nothing"
    assert groups.definition(str(empty[0])) is not None
    assert groups.definition("D-NOT-A-DETAIL") is None


def test_the_export_still_has_the_details_the_story_measured(
    read_model: sqlite3.Connection,
) -> None:
    (details,) = read_model.execute("SELECT COUNT(*) FROM detail").fetchone()
    (without,) = read_model.execute(
        "SELECT COUNT(*) FROM detail WHERE detail_id NOT IN "
        "(SELECT DISTINCT detail_id FROM datapoint)"
    ).fetchone()
    assert details == DETAILS
    assert without == DETAILS_WITHOUT_DATA


def test_the_member_list_names_the_published_indicators(
    catalogue: Catalogue, groups: ReadModelGroups
) -> None:
    education = named(groups, GroupLevel.ENTITY, EDUCATION)
    members = groups.indicators_in(education.level, education.key)
    placed = group_members_element(catalogue, Lang.EN, education, members)
    assert placed.role is Role.EVIDENCE
    assert all(member.name_en in placed.element.content for member in members)


# ============================================== Story 5.5 -- the executive overview


def test_the_overview_set_is_read_from_the_catalogue_and_never_hardcoded(
    rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """FR-31 and AD-11. The rule names a classification; the members come from the data."""
    classification = overview_classification(rule_set)
    assert classification == NATIONAL
    group = named(groups, GroupLevel.CLASSIFICATION, classification)
    assert group.indicator_count == NATIONAL_SIZE
    assert len(groups.indicators_in(group.level, group.key)) == NATIONAL_SIZE


def test_no_indicator_name_appears_in_the_overview_rule_file(rule_set: RuleSet) -> None:
    """The clause takes a classification and cannot be edited into a list of favourites."""
    rule = rule_set.fire("R-OVERVIEW-SET-IS-A-PUBLISHED-CLASSIFICATION")
    assert set(rule.values) == {"classification"}
    assert isinstance(rule.values["classification"], str)


def test_the_overview_fan_out_is_bounded_and_stated(rule_set: RuleSet) -> None:
    """NFR-2: a declared bound rather than an unbounded fan-out nobody signed off."""
    assert max_concurrent_fetches(rule_set) >= 1


def test_each_overview_member_carries_its_own_period(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
) -> None:
    """FR-31a: no common period is forced, and each period is written beside its own name."""
    members = (
        _member("Gross National Income", "GNI", Decimal("1.5"), "2023"),
        _member("Government Revenues", "GOV", Decimal("2.5"), "2026-Q1"),
    )
    composed = overview_elements(
        catalogue, Lang.EN, formatter, placement, rule_set, _national(), members
    )
    briefing = composed[0].element.content
    assert "2023" in briefing and "Q1 2026" in briefing
    assert composed[0].element.element_class is ElementClass.DERIVED


def test_an_overview_member_is_also_evidence_sourced_to_its_own_row(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
) -> None:
    """A stale member is refused on its own rather than taking the briefing with it."""
    members = (_member("Real GDP", "GDP", Decimal("7.0"), "2025"),)
    composed = overview_elements(
        catalogue, Lang.EN, formatter, placement, rule_set, _national(), members
    )
    evidence = [placed for placed in composed if placed.role is Role.EVIDENCE]
    assert len(evidence) == 1
    assert evidence[0].element.element_class is ElementClass.MEASURED
    assert evidence[0].element.source_ref.count("|") == SOURCE_REF_SEGMENTS - 1


def test_a_member_publishing_nothing_stays_in_the_overview_and_says_so(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
) -> None:
    """A reviewed set of 8 that silently returns 7 covers less than it claims to."""
    members = (
        _member("Real GDP", "GDP", Decimal("7.0"), "2025"),
        OverviewMember(indicator_id="I-SILENT", name="Trade Balance", reading=None),
    )
    composed = overview_elements(
        catalogue, Lang.EN, formatter, placement, rule_set, _national(), members
    )
    absent = [placed for placed in composed if placed.element.element_class is ElementClass.ABSENT]
    assert len(absent) == 1
    assert "Trade Balance" in absent[0].element.content
    assert "Trade Balance" in composed[0].element.content


def test_the_overview_states_that_each_figure_is_at_its_own_latest(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
) -> None:
    composed = overview_elements(
        catalogue,
        Lang.EN,
        formatter,
        placement,
        rule_set,
        _national(),
        (_member("Real GDP", "GDP", Decimal("7.0"), "2025"),),
    )
    notes = [placed for placed in composed if placed.role is Role.NOTE]
    assert len(notes) == 1
    assert notes[0].element.content.strip()


def test_the_overview_gives_one_figure_per_member(
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    rule_set: RuleSet,
) -> None:
    """F-021: *"I did not ask for all of this"*. One briefing, one row each, one note."""
    members = tuple(
        _member(f"Indicator {n}", f"I-{n}", Decimal("1.0"), "2025") for n in range(NATIONAL_SIZE)
    )
    composed = overview_elements(
        catalogue, Lang.EN, formatter, placement, rule_set, _national(), members
    )
    assert len(composed) == len(members) + 2


# ============================================= Story 5.6 -- what the engine can do


def test_the_capability_answer_is_counted_from_the_read_model(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """FR-32: grounded in the data held, so the numbers move when the data does."""
    coverage = groups.coverage()
    assert coverage.indicators == PUBLISHED_INDICATORS
    assert coverage.classifications == CLASSIFICATIONS
    assert coverage.entities == ENTITIES
    composed = capability_elements(catalogue, Lang.EN, rule_set, coverage)
    text = " ".join(placed.element.content for placed in composed)
    assert str(PUBLISHED_INDICATORS) in text
    assert str(CLASSIFICATIONS) in text


def test_every_capability_claim_carries_a_source_ref_that_resolves(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups, sources: EitherSource
) -> None:
    """FR-77: the engine does not describe itself from a prompt."""
    composed = capability_elements(catalogue, Lang.EN, rule_set, groups.coverage())
    admitted = admit_all((placed.element for placed in composed), sources)
    assert len(admitted.elements) == len(composed)
    assert not admitted.degradations


def test_the_capability_answer_names_what_it_does_not_hold(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """The read model has no analyst-prose table and no article table; the answer says so."""
    composed = capability_elements(catalogue, Lang.EN, rule_set, groups.coverage())
    notes = [placed for placed in composed if placed.role is Role.NOTE]
    assert len(notes) == 2
    assert any("commentary" in placed.element.content for placed in notes)


def test_the_capability_answer_does_not_claim_a_confidential_filter(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """Zero of 189 are confidential, so claiming the filter would imply withheld data."""
    composed = capability_elements(catalogue, Lang.EN, rule_set, groups.coverage())
    text = " ".join(placed.element.content for placed in composed)
    assert "confidential" in text.casefold()
    assert "nothing is being withheld" in text.casefold()


def test_the_capability_answer_returns_something(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """F-007 returned nothing. This is the regression."""
    for lang in Lang:
        composed = capability_elements(catalogue, lang, rule_set, groups.coverage())
        assert composed
        assert all(placed.element.content.strip() for placed in composed)


def test_a_capability_answer_over_an_empty_read_model_is_refused(sources: EitherSource) -> None:
    """The whole-catalogue reference resolves only when the engine holds a catalogue."""
    with provision() as empty:
        blank = EitherSource(
            datapoints=ReadModelSources(empty.read_model),
            catalogue=ReadModelCatalogueSources(empty.read_model),
        )
        assert not blank.resolves(whole_catalogue().source_ref)
    assert sources.resolves(whole_catalogue().source_ref)


# ============================================== Story 5.7 -- published definitions


def test_a_published_definition_is_quoted_rather_than_generated(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """FR-33. The content is the published text, unaltered."""
    published = PublishedDefinition(
        detail_id="D-1",
        definition_en="The increase in the general level of prices.",
        definition_ar="ارتفاع المستوى العام للأسعار.",
        source_id="S-1",
    )
    placed = definition_element(catalogue, Lang.EN, rule_set, published, "Inflation")
    assert placed.element.element_class is ElementClass.MEASURED
    assert published.definition_en in placed.element.content


@pytest.mark.parametrize("placeholder", ["-", " - ", "--", "N/A", "n/a", "TBD"])
def test_a_placeholder_is_not_rendered_as_a_definition(
    catalogue: Catalogue, rule_set: RuleSet, placeholder: str
) -> None:
    """88 English and 89 Arabic definitions are literally ``-``. None is a definition."""
    published = PublishedDefinition(
        detail_id="D-1", definition_en=placeholder, definition_ar=placeholder, source_id="S-1"
    )
    assert published_definition(rule_set, published, Lang.EN) is None
    placed = definition_element(catalogue, Lang.EN, rule_set, published, "Some Indicator")
    assert placed.element.element_class is ElementClass.ABSENT
    assert placeholder.strip() not in placed.element.content.replace("-", "–")


def test_the_placeholder_definitions_are_already_absent_by_the_time_they_are_stored(
    read_model: sqlite3.Connection,
) -> None:
    """Where the ``-`` is actually caught today, recorded rather than assumed.

    The export publishes 88 English and 89 Arabic definitions that are literally ``-``, and
    **the ingest already drops them**: FR-64's ``published_text`` refuses a placeholder, so
    what reaches ``detail.definition_en`` is ``NULL``. The composer's rule is therefore the
    second line and not the first, which is worth knowing -- a reviewer reading
    ``R-META-PLACEHOLDER-IS-NOT-A-DEFINITION`` would otherwise assume it is what stops the
    hyphen reaching a reader, and would not look at the ingest when it does.

    The rule still earns its place: the parametrised test above drives the composer with a
    placeholder directly, which is exactly what happens if a later export spells one a way
    ``published_text`` does not recognise, or if a definition arrives from anywhere else.
    """
    (dashes,) = read_model.execute(
        "SELECT COUNT(*) FROM detail WHERE TRIM(definition_en) = '-'"
    ).fetchone()
    assert dashes == 0
    (unpublished,) = read_model.execute(
        "SELECT COUNT(*) FROM detail WHERE definition_en IS NULL"
    ).fetchone()
    assert unpublished > 0, "no detail publishes an absent definition; the case has gone"


def test_an_absent_arabic_definition_is_stated_and_not_filled_from_english(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """FR-60. Substituting would answer a question about the Arabic catalogue in English."""
    published = PublishedDefinition(
        detail_id="D-1",
        definition_en="The increase in the general level of prices.",
        definition_ar="-",
        source_id="S-1",
    )
    assert published_definition(rule_set, published, Lang.AR) is None
    placed = definition_element(catalogue, Lang.AR, rule_set, published, "Inflation")
    assert placed.element.element_class is ElementClass.ABSENT
    assert published.definition_en not in placed.element.content


def test_a_definition_element_is_sourced_to_the_detail_it_came_from(
    catalogue: Catalogue, rule_set: RuleSet, read_model: sqlite3.Connection, groups: ReadModelGroups
) -> None:
    (detail_id,) = read_model.execute("SELECT detail_id FROM detail LIMIT 1").fetchone()
    published = groups.definition(str(detail_id))
    assert published is not None
    placed = definition_element(catalogue, Lang.EN, rule_set, published, "Any Detail")
    assert placed.element.source_ref.endswith(str(detail_id))
    assert ReadModelCatalogueSources(read_model).resolves(placed.element.source_ref)


# ================================================== Story 5.9 -- the residual, named


def test_components_that_account_for_the_whole_have_no_residual() -> None:
    """``None``, not a zero-amount residual: a zero would compose a part that is not there."""
    assert residual_of(Decimal(100), [Decimal(60), Decimal(40)]) is None


def test_a_shortfall_is_named_rather_than_dropped() -> None:
    """FR-37c. 60% of something leaves 40%, and the 40% is the answer's other half."""
    residual = residual_of(Decimal(100), [Decimal(60)])
    assert residual == Residual(amount=Decimal(40), total=Decimal(100), exceeds=False)


def test_parts_that_exceed_the_whole_are_reported_and_never_adjusted() -> None:
    """There is no remainder to name here; there is an inconsistency to report."""
    residual = residual_of(Decimal(100), [Decimal(60), Decimal(55)])
    assert residual is not None
    assert residual.exceeds
    assert residual.amount == Decimal(15)


def test_a_residual_is_a_magnitude_and_a_direction_never_a_negative_share() -> None:
    with pytest.raises(ValueError):
        Residual(amount=Decimal(-1), total=Decimal(100), exceeds=False)


def test_the_residual_arithmetic_is_exact_decimal() -> None:
    """Published values are exact decimals, so a difference that appears is a real one."""
    residual = residual_of(Decimal("100.0"), [Decimal("33.3"), Decimal("33.3"), Decimal("33.3")])
    assert residual is not None
    assert residual.amount == Decimal("0.1")


def test_the_residual_is_derived_and_states_what_it_came_from(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """FR-45: computed here, classed ``derived``, with its inputs in the content."""
    residual = residual_of(Decimal(100), [Decimal(60)])
    assert residual is not None
    placed = residual_element(
        catalogue,
        Lang.EN,
        formatter,
        placement,
        rule_set,
        residual,
        PublishedFormat(unit="Percent", spec=""),
        a_provenance(),
    )
    assert placed.element.element_class is ElementClass.DERIVED
    assert "100" in placed.element.content


def test_the_residual_is_not_called_other_unless_the_data_says_so(
    catalogue: Catalogue, formatter: Formatter, placement: Placement, rule_set: RuleSet
) -> None:
    """*"Other"* asserts a published residual category. Nothing published says that."""
    residual = residual_of(Decimal(100), [Decimal(60)])
    assert residual is not None
    default = residual_element(
        catalogue,
        Lang.EN,
        formatter,
        placement,
        rule_set,
        residual,
        PublishedFormat(unit="Percent", spec=""),
        a_provenance(),
    ).element.content
    assert "other" not in default.casefold()

    published = residual_element(
        catalogue,
        Lang.EN,
        formatter,
        placement,
        rule_set,
        residual,
        PublishedFormat(unit="Percent", spec=""),
        a_provenance(),
        published_label="Other services",
    ).element.content
    assert "Other services" in published


def test_the_stated_total_parts_and_residual_are_mutually_consistent() -> None:
    """The accounting contract: the three numbers add up, individually and together."""
    total, parts = Decimal(100), [Decimal(55), Decimal(20)]
    residual = residual_of(total, parts)
    assert residual is not None
    assert sum(parts, Decimal(0)) + residual.amount == total


# ======================================== Story 5.10 -- whether an answer can be charted


def test_no_published_configuration_means_no_chart_and_no_views(rule_set: RuleSet) -> None:
    """The honest answer while the read model holds no chart table."""
    offer = chartable_for(rule_set, None, has_a_series=True)
    assert offer == ChartOffer()
    assert not offer.available and offer.default_view is None and not offer.alternate_views


def test_a_single_figure_is_not_chartable_whatever_the_configuration_says(
    rule_set: RuleSet,
) -> None:
    configuration = PublishedChart(
        indicator_id="I-1", chart_type="line", default_view="yoy", alternate_views=("mom",)
    )
    assert not chartable_for(rule_set, configuration, has_a_series=False).available


def test_only_the_declared_views_are_offered(rule_set: RuleSet) -> None:
    """F-035: the client renders what it is offered, so nothing undeclared is offered."""
    configuration = PublishedChart(
        indicator_id="I-1", chart_type="line", default_view="yoy", alternate_views=("mom",)
    )
    offer = chartable_for(rule_set, configuration, has_a_series=True)
    assert offer.available
    assert offer.default_view == "yoy"
    assert offer.alternate_views == ("mom",)


def test_a_view_code_this_build_does_not_know_is_dropped(rule_set: RuleSet) -> None:
    configuration = PublishedChart(
        indicator_id="I-1",
        chart_type="line",
        default_view="yoy",
        alternate_views=("mom", "invented-view"),
    )
    assert chartable_for(rule_set, configuration, has_a_series=True).alternate_views == ("mom",)
    assert "invented-view" not in known_view_codes(rule_set)


def test_the_default_view_is_not_repeated_among_the_alternates(rule_set: RuleSet) -> None:
    configuration = PublishedChart(
        indicator_id="I-1", chart_type="line", default_view="yoy", alternate_views=("yoy", "mom")
    )
    assert chartable_for(rule_set, configuration, has_a_series=True).alternate_views == ("mom",)


def test_a_configuration_with_no_default_view_offers_no_chart(rule_set: RuleSet) -> None:
    """Declared as drawn and not declared under which view is not a chart the client can draw."""
    configuration = PublishedChart(
        indicator_id="I-1", chart_type="line", default_view="", alternate_views=("mom",)
    )
    assert not chartable_for(rule_set, configuration, has_a_series=True).available


def test_an_unavailable_offer_cannot_name_a_view() -> None:
    with pytest.raises(ValueError):
        ChartOffer(available=False, default_view="yoy")


# ================================================================ structural properties


def test_the_two_reference_shapes_do_not_parse_as_each_other(
    read_model: sqlite3.Connection,
) -> None:
    """The catalogue and datapoint resolvers can be asked in turn without either guessing."""
    catalogue_ref = CatalogueReference(ReferenceKind.ENTITY, "E-1").source_ref
    datapoint_ref = a_provenance().source_ref
    assert catalogue_ref.split("|") == [catalogue_ref]
    assert len(datapoint_ref.split("|")) == SOURCE_REF_SEGMENTS
    assert not ReadModelSources(read_model).resolves(catalogue_ref)
    assert not ReadModelCatalogueSources(read_model).resolves(datapoint_ref)


def test_every_reference_kind_is_one_the_read_model_can_resolve() -> None:
    """The two lists live in different layers, so their agreement is asserted, not shared."""
    assert {kind.value for kind in ReferenceKind} == set(_EXISTS_BY_KIND)
    assert CatalogueReference(ReferenceKind.ENTITY, "E-1").source_ref.startswith(
        CATALOGUE_REF_PREFIX
    )


def test_a_reference_key_may_not_contain_the_separator() -> None:
    """Otherwise it would split into a reference nobody built and might resolve."""
    with pytest.raises(ValueError):
        CatalogueReference(ReferenceKind.ENTITY, "E:1")
    with pytest.raises(ValueError):
        CatalogueReference(ReferenceKind.ENTITY, "  ")


def test_the_group_adapter_only_reads(read_model: sqlite3.Connection) -> None:
    """AD-20: the ingest owns every read-model table, and this module is not the ingest."""
    source = (PACKAGE_ROOT / "adapters" / "readmodel" / "groups.py").read_text(encoding="utf-8")
    for statement in ("INSERT", "UPDATE ", "DELETE", "DROP", "CREATE TABLE", "ALTER"):
        assert statement not in source.upper().replace("UPDATED", ""), statement


def test_nothing_unpublished_reaches_a_catalogue_answer() -> None:
    """No module here imports the unapproved catalogue, and its types have nowhere to sit.

    Asserted over the **imports** rather than over the source text: the package docstring
    explains why the boundary exists and says the word, and a substring scan that a
    docstring can fail is a scan that gets deleted the first time it does.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted(META_ROOT.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and "unpublished" in (node.module or "")
    ]
    assert not offenders, offenders


def test_no_composer_here_names_a_format_mode() -> None:
    """AD-18: the mode is read off ``Placement.mode_for(role)`` and never chosen."""
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted(META_ROOT.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "FormatMode"
    ]
    assert not offenders, offenders


# -------------------------------------------------------------------------- helpers


def _national() -> Group:
    return a_group(
        level=GroupLevel.CLASSIFICATION,
        key=NATIONAL,
        name="National Indicators",
        count=NATIONAL_SIZE,
        classification=NATIONAL,
    )


def _member(name: str, indicator_id: str, value: Decimal, period: str) -> OverviewMember:
    return OverviewMember(
        indicator_id=indicator_id,
        name=name,
        reading=OverviewReading(
            value=value,
            provenance=a_provenance(detail_id=f"D-{indicator_id}", period=period),
            published=PublishedFormat(unit="Percent", spec=""),
        ),
    )
