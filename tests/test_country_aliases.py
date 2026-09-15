"""Country identity resolves through reviewable data, and never names the home country.

Story 4.1. Four properties, and they are the four the acceptance criteria rest on:

1. **Held as data, validated at startup.** The map is built from
   ``src/askai/rules/data/country-aliases.yaml`` through the same loader the service
   starts with, and a malformed table refuses to return a partial map.
2. **Grounded in the export.** Every code in the table is a code
   ``P14_Ref_Countries`` carries, and every country value ``P03``/``P05`` publish
   resolves -- in English and in Arabic. An alias for a country the data does not have
   is worse than no alias, so the assertions run against the real CSVs rather than
   against a fixture that agrees with the file by construction.
3. **The measured duplicate collapses.** ``Korea`` and ``South Korea`` are one identity,
   a reader naming either reaches both, and a declared set carrying both yields the
   country once.
4. **The home country is a scope, not a value.** Its Arabic names resolve to
   ``HomeCountry()``; its English name resolves once the reference table extends the map;
   and no resolution of it can ever reach a country filter, because ``HomeCountry``
   carries no code to put in one.

The home country's name is read out of the export here rather than typed, for the same
reason the package may not contain it: this file then asserts the ban without being the
thing that breaks it, and the assertion stays true if the deployment's home country ever
differs from this export's.
"""

from __future__ import annotations

import ast
import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from askai.domain.normalise import normalise
from askai.rules import RuleLoadError, load_rules, rules
from askai.rules.countries import (
    ALIAS_GROUPS_RULE,
    HOME_COUNTRY_RULE,
    Country,
    CountryAliasError,
    CountryAliases,
    HomeCountry,
    ReferenceCountry,
    country_aliases,
    filter_values,
    load_country_aliases,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
COUNTRIES_MODULE: Final = PACKAGE_ROOT / "rules" / "countries.py"
ALIAS_FILE: Final = PACKAGE_ROOT / "rules" / "data" / "country-aliases.yaml"
EXPORT: Final = PROJECT_ROOT / "data" / "cms"


def _export(prefix: str) -> list[dict[str, str]]:
    """The one export file whose name starts with *prefix*, read as rows.

    Fails rather than skips when it is missing: the point of these assertions is that
    the aliases are grounded in the export, and a green run over no data proves nothing.
    """
    matches = sorted(EXPORT.glob(f"{prefix}-*.csv"))
    assert len(matches) == 1, f"expected exactly one {prefix} export, found {matches}"
    with matches[0].open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


@pytest.fixture(scope="module")
def reference() -> list[dict[str, str]]:
    return _export("P14_Ref_Countries")


@pytest.fixture(scope="module")
def datapoints() -> list[dict[str, str]]:
    return _export("P03_Published_DataPoints")


@pytest.fixture(scope="module")
def declared() -> list[dict[str, str]]:
    return _export("P05_Published_BenchmarkCountries")


@pytest.fixture(scope="module")
def home_names(reference: list[dict[str, str]]) -> tuple[str, str]:
    """The home country's English and Arabic names, taken from the reference table."""
    code = country_aliases().home_code
    rows = [row for row in reference if row["Code"] == code]
    assert rows, f"the export has no reference row for the home code {code}"
    return rows[0]["NameEN"], rows[0]["NameAR"]


@pytest.fixture(scope="module")
def extended(reference: list[dict[str, str]]) -> CountryAliases:
    """The packaged map extended with the export's reference table, as refresh builds it."""
    return country_aliases().extended_with(
        ReferenceCountry(code=row["Code"], name_en=row["NameEN"], name_ar=row["NameAR"])
        for row in reference
    )


# ------------------------------------------------------------------ held as data


def test_the_map_is_built_from_the_packaged_rule_files() -> None:
    """FR-11a: the alias map is data in ``rules/``, loaded by the startup loader."""
    assert ALIAS_FILE.is_file()
    entry = rules().get(ALIAS_GROUPS_RULE)
    assert entry.source_file == ALIAS_FILE
    assert entry.rule.is_fireable
    assert country_aliases().groups


def test_every_country_rule_states_a_status_and_is_reviewable() -> None:
    """The file answers to the shared schema, status included -- nothing is defaulted."""
    country_rules = [entry for entry in rules() if entry.source_file == ALIAS_FILE]
    assert len(country_rules) >= 2
    for entry in country_rules:
        assert entry.rule.area == "COUNTRY"
        assert entry.status.value in {"agreed", "proposed", "rejected"}
        assert entry.rule.sources


def test_no_country_list_exists_in_code(reference: list[dict[str, str]]) -> None:
    """AC: *no hard-coded country list exists in code*, asserted over the resolver itself.

    Docstrings are excluded deliberately -- prose explaining why the duplicate exists is
    not a list the engine reads. Every other string constant in the module is fair game,
    and none of them may be a country name the export knows.
    """
    tree = ast.parse(COUNTRIES_MODULE.read_text(encoding="utf-8"))
    documentation = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    written = {
        normalise(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        if id(node) not in documentation
    }
    names = {
        normalise(row[column])
        for row in reference
        for column in ("NameEN", "NameAR")
        if row[column].strip()
    }
    assert not (written & names), f"countries named in code: {sorted(written & names)}"


# ------------------------------------------------------------------ grounded in the export


def test_every_code_in_the_table_is_a_code_the_export_carries(
    reference: list[dict[str, str]],
) -> None:
    known = {row["Code"] for row in reference if row["Code"].strip()}
    assert country_aliases().codes <= known


def test_every_published_country_value_resolves(datapoints: list[dict[str, str]]) -> None:
    """Both languages, over the 8,127 published rows. The blank value is the national
    marker and is deliberately not a name to resolve."""
    aliases = country_aliases()
    published = {
        (row["CountryEN"], row["CountryAR"], row["CountryCode"])
        for row in datapoints
        if row["CountryEN"].strip()
    }
    assert len(published) == 30
    for english, arabic, code in published:
        assert aliases.resolve(english) == Country(code=code), english
        assert aliases.resolve(arabic) == Country(code=code), arabic


def test_every_declared_benchmark_country_resolves(
    declared: list[dict[str, str]], extended: CountryAliases
) -> None:
    """The 21 declared sets, including the home country the data never names."""
    for row in declared:
        resolved = extended.resolve(row["CountryEN"])
        assert resolved is not None, row["CountryEN"]
        assert extended.resolve(row["CountryAR"]) == resolved, row["CountryAR"]


def test_the_table_is_not_wider_than_the_data_it_answers_for(
    datapoints: list[dict[str, str]], declared: list[dict[str, str]]
) -> None:
    """An alias for a country the export does not have is worse than no alias."""
    carried = {row["CountryCode"] for row in datapoints if row["CountryCode"].strip()}
    carried |= {row["CountryCode"] for row in declared if row["CountryCode"].strip()}
    assert country_aliases().codes == carried


def test_a_reference_row_widens_the_map_without_contradicting_it(
    extended: CountryAliases, reference: list[dict[str, str]]
) -> None:
    """The reference table is the authority on which countries exist; the reviewed table
    keeps every group it had, and a name it already claims is not reassigned."""
    packaged = country_aliases()
    assert extended.codes >= packaged.codes
    assert len(extended.codes) > len(packaged.codes)
    for code, forms in packaged.groups.items():
        assert set(forms) <= set(extended.groups[code])


# ------------------------------------------------------------------ the measured duplicate


def test_both_published_spellings_of_one_country_are_one_identity(
    datapoints: list[dict[str, str]],
) -> None:
    """FACT 7: ``Korea`` and ``South Korea`` are two ids in the export under one code."""
    spellings = {
        row["CountryEN"] for row in datapoints if row["CountryCode"] == "KR"
    }
    assert spellings == {"Korea", "South Korea"}
    aliases = country_aliases()
    assert {aliases.resolve(name) for name in spellings} == {Country(code="KR")}


def test_a_reader_naming_either_spelling_reaches_the_same_rows(
    datapoints: list[dict[str, str]],
) -> None:
    """The reason the collapse matters: the two spellings carry different rows."""
    aliases = country_aliases()
    reached = {
        row["PublishedDataPointId"]
        for row in datapoints
        if row["CountryEN"].strip() and aliases.resolve(row["CountryEN"]) == Country(code="KR")
    }
    assert len(reached) == 95  # 93 rows under one spelling, 2 under the other


def test_a_declared_set_carrying_both_spellings_shows_the_country_once(
    declared: list[dict[str, str]],
) -> None:
    """A benchmark set does not show the country twice -- collapsed before any fetch."""
    both = [row for row in declared if row["CountryCode"] == "KR"]
    assert {row["CountryEN"] for row in both} == {"Korea", "South Korea"}
    resolved = country_aliases().resolve_all(row["CountryEN"] for row in both)
    assert resolved.identities == (Country(code="KR"),)
    assert resolved.unmapped == ()


def test_a_set_keeps_the_order_it_was_named_in() -> None:
    resolved = country_aliases().resolve_all(["Singapore", "Korea", "Singapore"])
    assert resolved.identities == (Country(code="SG"), Country(code="KR"))


# ------------------------------------------------------------------ the home country


def test_the_home_country_resolves_to_the_national_scope_in_arabic(
    home_names: tuple[str, str],
) -> None:
    """Arabic is a first-class path: it needs no reference table to work."""
    assert country_aliases().resolve(home_names[1]) == HomeCountry()


def test_the_home_country_resolves_to_the_national_scope_in_english(
    home_names: tuple[str, str], extended: CountryAliases
) -> None:
    """Its Latin-script names come from the export, which is why the package need not
    carry them -- and the reader still reaches the national scope by naming it."""
    assert extended.resolve(home_names[0]) == HomeCountry()
    assert extended.resolve(home_names[0].upper()) == HomeCountry()


def test_no_resolution_of_the_home_country_can_become_a_filter_value(
    home_names: tuple[str, str], extended: CountryAliases
) -> None:
    """AD-5, structurally: ``HomeCountry`` has no code, so there is nothing to filter by."""
    named = [extended.resolve(name) for name in home_names]
    assert named == [HomeCountry(), HomeCountry()]
    assert filter_values(identity for identity in named if identity is not None) == frozenset()
    assert not hasattr(HomeCountry(), "code")


def test_a_mixed_set_filters_by_the_benchmarks_and_never_by_the_home_country(
    home_names: tuple[str, str], extended: CountryAliases
) -> None:
    """The F-001 shape: the home country and one benchmark, named together."""
    resolved = extended.resolve_all([home_names[0], "Singapore"])
    assert resolved.identities == (HomeCountry(), Country(code="SG"))
    assert filter_values(resolved.identities) == {"SG"}


def test_the_home_country_has_no_country_row_to_be_filtered_for(
    datapoints: list[dict[str, str]], home_names: tuple[str, str]
) -> None:
    """The measured fact the whole design answers to: the configuration names it in every
    declared set, the published data names it in none of its rows."""
    home_code = country_aliases().home_code
    assert not [row for row in datapoints if row["CountryCode"] == home_code]
    assert not [row for row in datapoints if row["CountryEN"] == home_names[0]]
    assert len([row for row in datapoints if not row["CountryEN"].strip()]) == 5263


def test_the_home_country_is_declared_in_every_declared_set(
    declared: list[dict[str, str]],
) -> None:
    home_code = country_aliases().home_code
    sets_declaring = {row["PublishedIndicatorDetailId"] for row in declared}
    naming_home = {
        row["PublishedIndicatorDetailId"] for row in declared if row["CountryCode"] == home_code
    }
    assert len(sets_declaring) == 21
    assert naming_home == sets_declaring


def test_the_alias_file_does_not_name_the_home_country(home_names: tuple[str, str]) -> None:
    """The house rule, asserted over the data file as well as over the modules.

    A rule file inside ``src/askai/`` is no safer a place for the literal than a module,
    and this file is the one a story about country aliases would put it in.
    """
    written = ALIAS_FILE.read_text(encoding="utf-8").lower()
    assert home_names[0].lower() not in written


# ------------------------------------------------------------------ the single fold


def test_lookup_uses_the_one_normalisation() -> None:
    """AD-26 names alias lookup as a call site of the single ``normalise()``."""
    from askai.rules import countries

    # Read out of the module namespace rather than as an attribute: the name is imported
    # for use, not re-exported, and the assertion is about the object, not the surface.
    assert vars(countries)["normalise"] is normalise


@pytest.mark.parametrize(
    "surface",
    [
        "singapore",
        "  SINGAPORE  ",
        "Singapóre",
        "Singapore.",
    ],
)
def test_an_english_form_is_found_however_it_was_typed(surface: str) -> None:
    assert country_aliases().resolve(surface) == Country(code="SG")


@pytest.mark.parametrize(
    "surface",
    [
        "الأردن",  # as published, with hamza
        "الاردن",  # as a reader types it, without
        "الأُردن",  # with a harakat the fold removes
    ],
)
def test_an_arabic_form_is_found_however_it_was_typed(surface: str) -> None:
    assert country_aliases().resolve(surface) == Country(code="JO")


def test_an_unknown_name_resolves_to_nothing_rather_than_to_a_near_match() -> None:
    assert country_aliases().resolve("Atlantis") is None
    assert country_aliases().resolve("") is None


# ------------------------------------------------------------------ unmapped values (FR-110)


def test_an_unmapped_country_value_is_returned_for_the_refresh_report() -> None:
    """FR-110: the value is surfaced by name, not dropped and not invented."""
    resolved = country_aliases().resolve_all(["Singapore", "Atlantis", "Atlantis", "Ruritania"])
    assert resolved.identities == (Country(code="SG"),)
    assert resolved.unmapped == ("Atlantis", "Ruritania")
    assert country_aliases().unmapped(["Singapore", "Atlantis"]) == ("Atlantis",)


def test_the_base_layer_countries_that_never_publish_are_reported_not_answered() -> None:
    """The seven base-layer-only countries are exactly the FR-110 case: real values in an
    upstream table that the published export does not carry, so the map must not claim
    them and the refresh report must name them."""
    never_published = [
        "Algeria",
        "Canada",
        "Poland",
        "Russia",
        "South Africa",
        "Sri Lanka",
        "USA",
    ]
    assert country_aliases().unmapped(never_published) == tuple(never_published)


# ------------------------------------------------------------------ a bad table refuses to load


def _rule_file(groups: Sequence[str], home_code: str = "QA") -> str:
    statement = "A statement long enough for the shared schema to accept it as a rule."
    lines = "\n".join(f'          - "{group}"' for group in groups)
    return (
        "area: COUNTRY\n"
        "about: a table built for a test, in the shape of the packaged one\n"
        "rules:\n"
        f"  - id: {ALIAS_GROUPS_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: table\n"
        "    sources: [test]\n"
        "    values:\n"
        "      groups:\n"
        f"{lines}\n"
        f"  - id: {HOME_COUNTRY_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: switch\n"
        "    sources: [test]\n"
        "    values:\n"
        f"      home_country_code: {home_code}\n"
    )


def _load(directory: Path, groups: Sequence[str], home_code: str = "QA") -> CountryAliases:
    (directory / "country-aliases.yaml").write_text(_rule_file(groups, home_code), "utf-8")
    return load_country_aliases(load_rules(directory))


def test_a_hand_built_table_loads_the_same_way_the_packaged_one_does(tmp_path: Path) -> None:
    """The fixture's own smoke test: the failures below must be the table's, not the harness'."""
    aliases = _load(tmp_path, ["QA | X", "SG | Singapore | Singapura"])
    assert aliases.resolve("Singapura") == Country(code="SG")
    assert aliases.resolve("X") == HomeCountry()


def test_one_surface_form_claimed_by_two_countries_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(CountryAliasError) as excinfo:
        _load(tmp_path, ["QA | X", "SG | Singapore", "SA | Singapore"])
    assert "Singapore" in str(excinfo.value)


def test_a_form_repeated_inside_one_group_fails_to_load(tmp_path: Path) -> None:
    """Two spellings that fold to one normal form are one alias, and the file should say so."""
    with pytest.raises(CountryAliasError) as excinfo:
        _load(tmp_path, ["QA | X", "JO | الأردن | الاردن"])
    assert "twice" in str(excinfo.value)


def test_a_group_that_does_not_open_with_a_code_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(CountryAliasError):
        _load(tmp_path, ["QA | X", "Singapore | SG"])


def test_a_group_with_no_surface_form_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(CountryAliasError):
        _load(tmp_path, ["QA | X", "SG |"])


def test_a_code_opening_two_groups_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(CountryAliasError) as excinfo:
        _load(tmp_path, ["QA | X", "SG | Singapore", "SG | Singapura"])
    assert "two groups" in str(excinfo.value)


def test_a_home_code_with_no_group_fails_to_load(tmp_path: Path) -> None:
    """The home country must be *in* the table it is excluded from filters by; a code
    naming no group would silently make it an ordinary filter value."""
    with pytest.raises(CountryAliasError) as excinfo:
        _load(tmp_path, ["SG | Singapore"], home_code="ZZ")
    assert "ZZ" in str(excinfo.value)


def test_a_country_alias_failure_is_a_rule_load_failure() -> None:
    """The service refuses to start on it, like any other bad rule file."""
    assert issubclass(CountryAliasError, RuleLoadError)


def test_a_reference_row_contradicting_a_reviewed_group_is_refused(tmp_path: Path) -> None:
    aliases = _load(tmp_path, ["QA | X", "SG | Singapore"])
    with pytest.raises(CountryAliasError) as excinfo:
        aliases.extended_with([ReferenceCountry(code="SA", name_en="Singapore", name_ar="")])
    assert "SG" in str(excinfo.value)
