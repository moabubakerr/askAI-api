"""Story 1.8: the published layer, materialised -- and the base layer, kept out.

Asserted against the real export in ``data/`` and against the databases the schema step
actually builds, not against a fixture shaped like the one this code hoped for. The
counts in the story are measurements, so a disagreement here is evidence about the data
rather than an expectation to relax.

Everything runs in memory or in a temporary directory: no service, no environment
variable, no network.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.countries import country_aliases_from, reference_countries
from askai.adapters.readmodel.export import CMS_SUBDIRECTORY, CmsExport, ExportError
from askai.adapters.readmodel.ingest import (
    CONFIDENTIAL,
    IngestError,
    IngestReport,
    ingest_published_layer,
)
from askai.adapters.readmodel.schema import OWNER
from askai.adapters.readmodel.unpublished import UnpublishedCatalog
from askai.adapters.store.provision import TABLE_OWNERS, Databases, provision
from askai.ports.unpublished_catalogue import UnpublishedCatalogPort, UnpublishedName
from askai.rules.countries import (
    CountryAliasError,
    CountryAliases,
    HomeCountry,
    country_aliases,
    filter_values,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

# The story's measured facts. Written here as constants so a test that drifts has to
# change a number a reviewer can see, rather than an assertion buried in a body.
INDICATORS: Final = 189
DETAILS: Final = 289
DATAPOINTS: Final = 8_127
ANALYSES: Final = 1_031
NATIONAL_ROWS: Final = 5_263
COUNTRY_BEARING_ROWS: Final = 2_864
REFERENCE_COUNTRIES: Final = 235
REFERENCE_LOOKUPS: Final = 142 + 3  # the ten common vocabularies, plus the priority types

#: The base layer, which is reachable only as names: 531 in the CMS, 189 published.
UNPUBLISHED_INDICATORS: Final = 342
UNPUBLISHED_WITH_A_NAME: Final = 281

#: Named here and nowhere in ``src/askai``. The read model must contain rows for it in
#: the country reference and none at all in the data, which is the fact FR-10 rests on.
HOME_COUNTRY: Final = "Qatar"

#: ``PublishingStatusName`` on 100% of published indicators, and therefore information
#: about nothing. FR-49: it must not be anywhere a reader can reach.
PUBLISHING_STATUS_VALUE: Final = "Amended"

#: The layers an answer is built in. A type from the unpublished port appearing in any
#: of them is the crossing this story forbids.
ANSWER_PATH_PACKAGES: Final = (
    "compile",
    "validate",
    "execute",
    "assemble",
    "narrate",
    "respond",
    "api",
)

_UNPUBLISHED_MODULES: Final = frozenset(
    {"askai.ports.unpublished_catalogue", "askai.adapters.readmodel.unpublished"}
)


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
def report(ingested: tuple[Databases, IngestReport]) -> IngestReport:
    return ingested[1]


def _scalar(connection: sqlite3.Connection, sql: str, *parameters: object) -> object:
    row = connection.execute(sql, parameters).fetchone()
    assert row is not None
    value: object = row[0]
    return value


def _count(connection: sqlite3.Connection, table: str) -> int:
    count = _scalar(connection, f"SELECT COUNT(*) FROM {table}")
    assert isinstance(count, int)
    return count


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return sorted(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    )


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


# ------------------------------------------------------------- only the published layer


def test_the_published_layer_arrives_whole(report: IngestReport) -> None:
    """The story's headline counts, measured off the tables after the ingest."""
    assert report.indicators == INDICATORS
    assert report.details == DETAILS
    assert report.datapoints == DATAPOINTS
    assert report.countries == REFERENCE_COUNTRIES
    assert report.lookups == REFERENCE_LOOKUPS


def test_the_published_analyses_are_counted_and_stored(
    report: IngestReport, read_model: sqlite3.Connection
) -> None:
    """The export's 1,031 analyses are counted, and now every one of them is kept.

    Until the ``analysis`` table existed this test asserted the opposite -- the count
    without the rows -- because Story 1.6 named Epic 1's tables and Story 1.8 asked for
    the analyses to be loaded, and the ingest refused to invent a table. The table is
    the resolution; what the two stories disagreed about is settled, not worked around.
    ``tests/test_analysis.py`` holds the rest.
    """
    assert report.analyses_available == ANALYSES
    assert report.analyses == ANALYSES
    assert _count(read_model, "analysis") == ANALYSES


def test_the_counts_on_the_report_agree_with_the_tables(
    report: IngestReport, read_model: sqlite3.Connection
) -> None:
    assert report.indicators == _count(read_model, "catalogue")
    assert report.details == _count(read_model, "detail")
    assert report.datapoints == _count(read_model, "datapoint")
    assert report.rows_written == sum(
        _count(read_model, table)
        for table in (
            "ref_country",
            "ref_lookup",
            "catalogue",
            "detail",
            "datapoint",
            "analysis",
        )
    )


def test_the_read_model_holds_no_table_for_the_base_layer(read_model: sqlite3.Connection) -> None:
    """The base layer is not loaded anywhere a published row could join to it."""
    assert _table_names(read_model) == [
        "analysis",
        "catalogue",
        "datapoint",
        "detail",
        "ref_country",
        "ref_lookup",
    ]


def test_every_detail_and_datapoint_resolves_to_something_published(
    read_model: sqlite3.Connection,
) -> None:
    orphan_details = _scalar(
        read_model,
        "SELECT COUNT(*) FROM detail "
        "WHERE indicator_id NOT IN (SELECT indicator_id FROM catalogue)",
    )
    orphan_datapoints = _scalar(
        read_model,
        "SELECT COUNT(*) FROM datapoint WHERE detail_id NOT IN (SELECT detail_id FROM detail)",
    )
    assert (orphan_details, orphan_datapoints) == (0, 0)


def test_the_published_names_arrive_in_both_languages(read_model: sqlite3.Connection) -> None:
    assert _scalar(read_model, "SELECT COUNT(*) FROM catalogue WHERE name_ar = ''") == 0
    assert _scalar(read_model, "SELECT COUNT(*) FROM detail WHERE name_ar = ''") == 0


def test_the_group_layer_comes_across_resolved(read_model: sqlite3.Connection) -> None:
    """``P01`` carries the group id for all 189; the names live in two loose files."""
    assert _scalar(read_model, "SELECT COUNT(*) FROM catalogue WHERE entity_name_en IS NULL") == 0
    assert _scalar(read_model, "SELECT COUNT(DISTINCT entity_id) FROM catalogue") == 22


def test_ingest_is_repeatable_and_leaves_the_same_read_model(
    read_model: sqlite3.Connection, export: CmsExport
) -> None:
    """A refresh replaces the contents; it does not accumulate them."""
    again = ingest_published_layer(read_model, export)
    assert again.datapoints == DATAPOINTS
    assert again.indicators == INDICATORS
    assert again.details == DETAILS


# ------------------------------------------------------- the identity fact, grain-free


def test_the_key_is_detail_period_country_and_holds_across_every_row(
    read_model: sqlite3.Connection,
) -> None:
    distinct = _scalar(
        read_model,
        "SELECT COUNT(*) FROM (SELECT DISTINCT detail_id, period, country_id FROM datapoint)",
    )
    assert distinct == DATAPOINTS, "the identity fact does not hold for this export"


def test_the_grain_is_not_part_of_the_key_and_not_a_column(read_model: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in read_model.execute("PRAGMA table_info(datapoint)")}
    assert "grain" not in columns
    assert not any("interval" in column for column in columns)

    key = [
        str(row[1])
        for row in sorted(
            read_model.execute("PRAGMA table_info(datapoint)"), key=lambda row: int(row[5])
        )
        if int(row[5]) > 0
    ]
    assert key == ["detail_id", "period", "country_id"]


def test_a_duplicate_key_is_refused_rather_than_quietly_overwritten(
    read_model: sqlite3.Connection,
) -> None:
    row = read_model.execute(
        "SELECT detail_id, period, country_id FROM datapoint WHERE country_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    with pytest.raises(sqlite3.IntegrityError):
        read_model.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id) "
            "VALUES (?, ?, ?, 'a-second-row-for-one-key')",
            tuple(row),
        )
    read_model.rollback()


def test_a_duplicate_national_key_is_refused_too(read_model: sqlite3.Connection) -> None:
    """The primary key does not constrain these at all -- two NULLs compare distinct."""
    row = read_model.execute(
        "SELECT detail_id, period FROM datapoint WHERE country_id IS NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    with pytest.raises(sqlite3.IntegrityError):
        read_model.execute(
            "INSERT INTO datapoint (detail_id, period, country_id, source_datapoint_id) "
            "VALUES (?, ?, NULL, 'a-second-national-row')",
            tuple(row),
        )
    read_model.rollback()


def test_a_colliding_export_is_refused_whole(tmp_path: Path) -> None:
    export = _synthetic_export(tmp_path)
    _append(
        export,
        "P03_Published_DataPoints",
        {
            "PublishedDataPointId": "dp-2",
            "PublishedIndicatorDetailId": "det-1",
            "Period": "2025",
            "CountryId": "",
            "Actual": "2",
        },
    )
    with provision() as databases:
        with pytest.raises(IngestError) as excinfo:
            ingest_published_layer(databases.read_model, CmsExport.rooted(tmp_path))
        assert "(detail, period, country)" in str(excinfo.value)
        assert _count(databases.read_model, "catalogue") == 0, "nothing may be left behind"


def test_the_published_change_columns_are_carried_by_the_row_s_own_grain(
    read_model: sqlite3.Connection,
) -> None:
    """Change is published, not computed, and a yearly row has no month-over-month."""
    assert (
        _scalar(
            read_model,
            "SELECT COUNT(*) FROM datapoint WHERE period NOT GLOB '????-[01][0-9]' "
            "AND change_mom_percent IS NOT NULL",
        )
        == 0
    )
    assert (
        _scalar(
            read_model,
            "SELECT COUNT(*) FROM datapoint WHERE period NOT GLOB '????-Q[1-4]' "
            "AND change_qoq_percent IS NOT NULL",
        )
        == 0
    )
    yearly_yoy = _scalar(
        read_model,
        "SELECT COUNT(*) FROM datapoint WHERE period GLOB '[0-9][0-9][0-9][0-9]' "
        "AND change_yoy_percent IS NOT NULL",
    )
    assert isinstance(yearly_yoy, int) and yearly_yoy > 0, "the published change must arrive"


# ----------------------------------------------------------- FR-10: the blank stays blank


def test_the_national_marker_is_preserved_exactly(report: IngestReport) -> None:
    assert report.national_rows == NATIONAL_ROWS
    assert report.country_rows == COUNTRY_BEARING_ROWS
    assert report.national_rows + report.country_rows == DATAPOINTS


def test_the_home_country_has_a_reference_row_and_no_data_row(
    read_model: sqlite3.Connection,
) -> None:
    """The trap FR-10 exists for: the config names it, the data never does.

    If ingest had back-filled the blank country, this count would be 5,263 and the
    national series would have been silently merged into the benchmark set.
    """
    home = _scalar(read_model, "SELECT country_id FROM ref_country WHERE name_en = ?", HOME_COUNTRY)
    assert isinstance(home, str), "the country reference must still carry the home country"
    assert _scalar(read_model, "SELECT COUNT(*) FROM datapoint WHERE country_id = ?", home) == 0


def test_no_country_name_is_stored_on_a_datapoint(read_model: sqlite3.Connection) -> None:
    """A name on the row is what makes back-filling one a one-line change."""
    columns = {str(row[1]) for row in read_model.execute("PRAGMA table_info(datapoint)")}
    assert not any("name" in column for column in columns)
    assert "country_id" in columns


def test_the_ingest_names_no_country_at_all() -> None:
    """The whole package is scanned for the literal elsewhere; this is the local claim."""
    source = (PACKAGE_ROOT / "adapters" / "readmodel" / "ingest.py").read_text(encoding="utf-8")
    assert HOME_COUNTRY.casefold() not in source.casefold()


def test_only_the_countries_that_carry_data_are_on_datapoints(
    read_model: sqlite3.Connection,
) -> None:
    assert _scalar(read_model, "SELECT COUNT(DISTINCT country_id) FROM datapoint") == 30


# ------------------------------------------------------- FR-50: confidential never lands


def test_a_confidential_indicator_is_excluded_with_everything_under_it(tmp_path: Path) -> None:
    _synthetic_export(tmp_path, priority_id="3")
    with provision() as databases:
        report = ingest_published_layer(databases.read_model, CmsExport.rooted(tmp_path))
        assert report.confidential_indicators_excluded == 1
        assert report.indicators == 0
        assert report.details == 0, "its details must not survive it"
        assert report.datapoints == 0, "nor its numbers"
        assert _count(databases.read_model, "catalogue") == 0


def test_a_non_confidential_indicator_in_the_same_shape_does_land(tmp_path: Path) -> None:
    """Without this, the exclusion above could be passing for any reason at all."""
    _synthetic_export(tmp_path, priority_id="2")
    with provision() as databases:
        report = ingest_published_layer(databases.read_model, CmsExport.rooted(tmp_path))
        assert report.confidential_indicators_excluded == 0
        assert (report.indicators, report.details, report.datapoints) == (1, 1, 1)


def test_the_table_refuses_a_confidential_row_even_when_the_filter_is_bypassed() -> None:
    """The filter is the polite refusal; the constraint is the one nobody can forget."""
    with provision() as databases, pytest.raises(sqlite3.IntegrityError):
        databases.read_model.execute(
            "INSERT INTO catalogue (indicator_id, name_en, name_ar, classification, "
            "priority_type) VALUES ('i', 'n', 'n', 'c', ?)",
            (CONFIDENTIAL,),
        )


def test_nothing_confidential_is_in_the_real_read_model(
    read_model: sqlite3.Connection, report: IngestReport
) -> None:
    assert report.confidential_indicators_excluded == 0, "none is published in this export"
    assert _scalar(
        read_model, "SELECT COUNT(*) FROM catalogue WHERE priority_type = ?", CONFIDENTIAL
    ) == 0


# --------------------------------------------------------- FR-49: no CMS state is stored


def test_the_publishing_status_is_in_no_column_and_no_value(read_model: sqlite3.Connection) -> None:
    """It is ``Amended`` on 100% of published indicators, so it distinguishes nothing."""
    for table in _table_names(read_model):
        columns = [str(row[1]) for row in read_model.execute(f"PRAGMA table_info({table})")]
        assert not any("status" in column for column in columns), table
        for row in read_model.execute(f"SELECT * FROM {table}"):
            values = [value for value in row if isinstance(value, str)]
            assert PUBLISHING_STATUS_VALUE not in values, table


# ------------------------------------------- FR-64: decoded once, at ingest, never after


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<p>Gross domestic product</p>", "Gross domestic product"),
        ("<p>a</p><p>b</p>", "a b"),
        ("Trade &amp; industry", "Trade & industry"),
        ("&lt;p&gt; is a tag the author typed", "<p> is a tag the author typed"),
        ("the second- lowest level", "the second-lowest level"),
        ("soft­hyphen", "softhyphen"),
        ("  spaced \u200b out  ", "spaced out"),
        ("PGRhdGE+PHA+ZW5jb2RlZDwvcD4=", "encoded"),
    ],
)
def test_published_content_is_decoded_and_rendered_to_text(raw: str, expected: str) -> None:
    assert published_text(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "<p></p>", "<p>&nbsp;</p>", "-", "–"])
def test_content_that_says_nothing_becomes_nothing(raw: str | None) -> None:
    assert published_text(raw) is None


def test_plain_text_that_looks_like_base64_is_left_alone() -> None:
    """A wrong guess here corrupts a published definition silently."""
    assert published_text("Indicators") == "Indicators"
    assert published_text("Classified Hotels") == "Classified Hotels"


def test_no_stored_definition_carries_markup_or_an_entity(read_model: sqlite3.Connection) -> None:
    for column in ("definition_en", "definition_ar"):
        rows = read_model.execute(
            f"SELECT {column} FROM detail WHERE {column} IS NOT NULL"
        ).fetchall()
        assert rows, column
        assert not [value for (value,) in rows if "<" in value or "&nbsp;" in value]


def test_the_definitions_really_did_need_decoding(
    read_model: sqlite3.Connection, export: CmsExport
) -> None:
    """139 of 289 published definitions are HTML in the export; none is HTML here.

    The rest of the gap is absence wearing a definition's clothes: 88 of the 289 are a
    bare dash, and the domain's emptiness predicate reads that as "nothing to say"
    rather than as the text "-". 171 details carry a definition; 118 do not.
    """
    assert sum(1 for row in export.published_details() if "<" in row["DefinationEN"]) == 139
    assert _count(read_model, "detail WHERE definition_en IS NOT NULL") == 171
    assert _count(read_model, "detail WHERE definition_ar IS NOT NULL") == 170
    assert _count(read_model, "detail WHERE definition_en = '-'") == 0


def test_no_answer_path_module_strips_markup() -> None:
    """The stripping happens once, here. A second one at answer time is the defect."""
    offenders = [
        _module_name(path)
        for package in ANSWER_PATH_PACKAGES
        for path in _python_files(PACKAGE_ROOT / package)
        if "<[^>]" in path.read_text(encoding="utf-8")
        or "html.unescape" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# ------------------------------------------ the unpublished port: names and existence only


@pytest.fixture(scope="module")
def unpublished(export: CmsExport) -> UnpublishedCatalog:
    return UnpublishedCatalog.from_export(export)


def test_the_adapter_satisfies_the_port(unpublished: UnpublishedCatalog) -> None:
    port: UnpublishedCatalogPort = unpublished
    assert isinstance(port, UnpublishedCatalogPort)


def test_the_base_layer_is_reachable_as_names_and_existence(
    unpublished: UnpublishedCatalog, export: CmsExport
) -> None:
    published = {row["SourceIndicatorId"].casefold() for row in export.published_indicators()}
    base = export.base_indicators()
    assert len(base) - len(published) == UNPUBLISHED_INDICATORS
    assert len(unpublished.names()) == UNPUBLISHED_WITH_A_NAME


def test_the_port_answers_existence_under_the_engine_s_own_fold(
    unpublished: UnpublishedCatalog,
) -> None:
    first = unpublished.names()[0]
    assert unpublished.holds(first.name_en)
    assert unpublished.holds(f"  {first.name_en.upper()}  "), "one fold, or none at all"
    assert not unpublished.holds("an indicator nobody ever wrote down")


def test_a_published_indicator_is_not_in_the_unpublished_catalogue(
    unpublished: UnpublishedCatalog, export: CmsExport
) -> None:
    published = {row["NameEN"] for row in export.published_indicators() if row["NameEN"].strip()}
    # A name published under one indicator may also sit on an unapproved one -- 257 of
    # 320 names in this export are ambiguous -- so the claim is about the common case,
    # asserted over the whole set rather than one lucky row.
    overlap = [name for name in published if unpublished.holds(name)]
    assert len(overlap) < len(published) / 10, sorted(overlap)[:5]


def test_the_port_exposes_names_and_nothing_else() -> None:
    """Two fields, both names. There is nothing on this type to join a figure to."""
    assert [field for field in UnpublishedName.__dataclass_fields__] == ["name_en", "name_ar"]
    assert sorted(
        name for name in vars(UnpublishedCatalogPort) if not name.startswith("_")
    ) == ["holds", "names"]


def test_the_unpublished_catalogue_writes_nothing(read_model: sqlite3.Connection) -> None:
    source = (PACKAGE_ROOT / "adapters" / "readmodel" / "unpublished.py").read_text(
        encoding="utf-8"
    )
    for table in TABLE_OWNERS:
        assert f"INTO {table}" not in source
        assert f"UPDATE {table}" not in source
    assert "sqlite3" not in source, "it takes no connection, so it cannot reach a file"


def test_no_type_from_the_unpublished_port_crosses_into_an_answer() -> None:
    """The structural form of the story's crossing test.

    The answer package itself lands in Story 1.15, so the claim is asserted where it can
    already be broken: no layer that compiles, validates, executes, assembles, narrates
    or responds may so much as import the unapproved catalogue's types.
    """
    offenders: list[str] = []
    for package in ANSWER_PATH_PACKAGES:
        for path in _python_files(PACKAGE_ROOT / package):
            crossings = _imported_modules(path) & _UNPUBLISHED_MODULES
            offenders.extend(f"{_module_name(path)} imports {name}" for name in sorted(crossings))
    assert offenders == []


def test_only_the_adapter_reaches_the_unpublished_port_at_all() -> None:
    """Named importers, so a new one is a decision rather than an accident."""
    importers = {
        _module_name(path)
        for path in _python_files(PACKAGE_ROOT)
        if _imported_modules(path) & _UNPUBLISHED_MODULES
    }
    assert importers == {"askai.adapters.readmodel.unpublished"}


def test_the_crossing_scan_would_catch_an_offender(tmp_path: Path) -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from askai.ports.unpublished_catalogue import UnpublishedName\n", encoding="utf-8"
    )
    assert _imported_modules(offender) & _UNPUBLISHED_MODULES


# ------------------------------------------------------------------- AD-20: one owner


def test_the_ingest_is_the_read_model_s_own_module(read_model: sqlite3.Connection) -> None:
    for table in ("catalogue", "detail", "datapoint", "ref_country", "ref_lookup"):
        assert TABLE_OWNERS[table] == OWNER
    assert OWNER == "askai.adapters.readmodel"


def test_the_ingest_sets_no_connection_policy_of_its_own() -> None:
    """WAL is set once by the schema step. An ingest that set it would be the second."""
    source = (PACKAGE_ROOT / "adapters" / "readmodel" / "ingest.py").read_text(encoding="utf-8")
    assert "journal_mode" not in source
    assert "user_version" not in source


def test_a_failed_refresh_leaves_the_previous_read_model_untouched(
    export: CmsExport, tmp_path: Path
) -> None:
    """A reader sees the old contents or the new ones, never a mixture of the two."""
    with provision() as databases:
        ingest_published_layer(databases.read_model, export)
        assert _count(databases.read_model, "datapoint") == DATAPOINTS

        broken = _synthetic_export(tmp_path)
        _append(
            broken,
            "P03_Published_DataPoints",
            {
                "PublishedDataPointId": "dp-2",
                "PublishedIndicatorDetailId": "det-1",
                "Period": "2025",
                "CountryId": "",
                "Actual": "2",
            },
        )
        with pytest.raises(IngestError):
            ingest_published_layer(databases.read_model, CmsExport.rooted(broken))

        assert _count(databases.read_model, "datapoint") == DATAPOINTS
        assert _count(databases.read_model, "catalogue") == INDICATORS
        assert not databases.read_model.in_transaction


# ------------------------------------ the country map the export is the authority for


def test_the_ingest_widens_the_reviewed_alias_table_with_the_published_names(
    report: IngestReport, export: CmsExport
) -> None:
    """Story 4.1's open seam, closed here: if nothing called it, nothing would widen it."""
    packaged = country_aliases()
    widened = report.country_aliases
    assert widened is not packaged
    assert widened.codes >= packaged.codes
    published = {row["NameEN"] for row in export.reference_countries() if row["Code"].strip()}
    assert [name for name in published if widened.resolve(name) is None] == []


def test_the_home_country_is_nameable_again_and_still_cannot_be_filtered(
    report: IngestReport,
) -> None:
    """The names arrive from the export, which is why no file under ``src`` holds them."""
    resolved = report.country_aliases.resolve(HOME_COUNTRY)
    assert isinstance(resolved, HomeCountry), "the export's own name for it must resolve"
    assert filter_values([resolved]) == frozenset(), "and must never become a filter value"


def test_the_two_spellings_of_one_country_collapse_to_one_identity(
    report: IngestReport,
) -> None:
    """``Korea`` and ``South Korea`` are both published; a benchmark set must show one."""
    resolution = report.country_aliases.resolve_all(["Korea", "South Korea"])
    assert len(resolution.identities) == 1, resolution
    assert resolution.unmapped == ()


def test_a_reference_table_that_contradicts_the_reviewed_groups_stops_the_ingest(
    tmp_path: Path,
) -> None:
    """A silent overwrite here would rename a country by editing an export."""
    _synthetic_export(tmp_path)
    reviewed = CountryAliases.build("QA", {"QA": ["QA-home"], "SW": ["Somewhere"]})
    contradicting = CmsExport.rooted(tmp_path)
    with pytest.raises(CountryAliasError):
        country_aliases_from(
            contradicting,
            CountryAliases.build("QA", {"QA": ["QA-home", "Somewhere"], "XX": ["Elsewhere"]}),
        )
    assert country_aliases_from(contradicting, reviewed).codes >= {"QA", "SW"}


def test_a_reference_row_with_no_usable_code_contributes_nothing(export: CmsExport) -> None:
    rows = reference_countries(export)
    assert len(rows) == REFERENCE_COUNTRIES
    assert all(row.name_en for row in rows)


# ------------------------------------------------------------------ the export on disk


def test_a_missing_export_file_is_named_rather_than_skipped(tmp_path: Path) -> None:
    (tmp_path / CMS_SUBDIRECTORY).mkdir()
    with pytest.raises(ExportError) as excinfo:
        CmsExport.rooted(tmp_path).published_indicators()
    assert "P01_Published_Indicators" in str(excinfo.value)


def test_two_exports_in_one_directory_are_refused(tmp_path: Path) -> None:
    cms = tmp_path / CMS_SUBDIRECTORY
    cms.mkdir()
    for stamp in ("20260811", "20260812"):
        (cms / f"P01_Published_Indicators-{stamp}.csv").write_text("Id\n", encoding="utf-8")
    with pytest.raises(ExportError) as excinfo:
        CmsExport.rooted(tmp_path).published_indicators()
    assert "2 files" in str(excinfo.value)


def test_a_missing_group_name_file_is_named(tmp_path: Path) -> None:
    (tmp_path / CMS_SUBDIRECTORY).mkdir()
    with pytest.raises(ExportError) as excinfo:
        CmsExport.rooted(tmp_path).entity_names()
    assert "Sectors.csv" in str(excinfo.value)


# --------------------------------------------------------------- the synthetic export


_SYNTHETIC: Final = {
    "P01_Published_Indicators": [
        {
            "PublishedIndicatorId": "ind-1",
            "SourceIndicatorId": "base-1",
            "NameEN": "A published indicator",
            "NameAR": "مؤشر منشور",
            "IndicatorPriorityTypeId": "2",
            "IndicatorEntityTypeId": "ENT-1",
            "EntityClassificationName": "Sectors",
            "PublishingStatusName": "Amended",
        }
    ],
    "P02_Published_IndicatorDetails": [
        {
            "PublishedIndicatorDetailId": "det-1",
            "PublishedIndicatorId": "ind-1",
            "SourceIndicatorDetailId": "base-det-1",
            "IsMain": "True",
            "NameEN": "A detail",
            "NameAR": "تفصيل",
            "DefinationEN": "<p>What it measures</p>",
            "DefinationAR": "<p>ما يقيسه</p>",
            "Format": "0.0",
            "UnitId": "look-1",
            "PolarityId": "look-1",
            "ValueTypeId": "look-1",
            "DataSourceId": "look-1",
            "AggregationTypeId": "look-1",
        }
    ],
    "P03_Published_DataPoints": [
        {
            "PublishedDataPointId": "dp-1",
            "PublishedIndicatorDetailId": "det-1",
            "Period": "2025",
            "CountryId": "",
            "CountryEN": "",
            "Actual": "1",
            "YearlyYoYPercent": "3.5",
        }
    ],
    "P04_Published_DataPointAnalysis": [
        {"PublishedDataPointAnalysisId": "an-1", "PublishedDataPointId": "dp-1"}
    ],
    "P12_Ref_Lookups_Common": [
        {"LookupType": "Units", "Id": "look-1", "NameEN": "Per cent", "NameAR": "نسبة"}
    ],
    "P13_Ref_IndicatorPriorityTypes": [
        {"Id": "1", "NameEN": "Non-Priority", "NameAR": "غير ذات أولوية"},
        {"Id": "2", "NameEN": "Priority", "NameAR": "ذات أولوية"},
        {"Id": "3", "NameEN": CONFIDENTIAL, "NameAR": "سري"},
    ],
    "P14_Ref_Countries": [
        {"Id": "c-1", "NameEN": "Somewhere", "NameAR": "مكان", "Code": "SW"},
    ],
    "Item_2_Indicators_Catalog": [
        {"Id": "base-1", "NameEN": "A published indicator", "NameAR": "مؤشر منشور"},
        {"Id": "base-2", "NameEN": "An indicator nobody approved", "NameAR": "مؤشر غير معتمد"},
    ],
}

_SYNTHETIC_LOOSE: Final = {
    "Sectors.csv": [{"Id": "ent-1", "NameEN": "A sector", "NameAR": "قطاع"}],
    "General Entities.csv": [{"Id": "ent-2", "NameEN": "An entity", "NameAR": "جهة"}],
}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    columns = list(rows[0])
    lines = [",".join(f'"{column}"' for column in columns)]
    lines.extend(",".join(f'"{row.get(column, "")}"' for column in columns) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def _synthetic_export(root: Path, priority_id: str = "2") -> Path:
    """A one-indicator export in the real export's shape, written to *root*."""
    cms = root / CMS_SUBDIRECTORY
    cms.mkdir(exist_ok=True)
    for prefix, rows in _SYNTHETIC.items():
        copied = [dict(row) for row in rows]
        if prefix == "P01_Published_Indicators":
            copied[0]["IndicatorPriorityTypeId"] = priority_id
        _write_csv(cms / f"{prefix}-20260811.csv", copied)
    for filename, rows in _SYNTHETIC_LOOSE.items():
        _write_csv(root / filename, [dict(row) for row in rows])
    return root


def _append(root: Path, prefix: str, row: dict[str, str]) -> None:
    path = next((root / CMS_SUBDIRECTORY).glob(f"{prefix}*.csv"))
    rows = [dict(existing) for existing in _SYNTHETIC[prefix]]
    rows.append({**{column: "" for column in rows[0]}, **row})
    _write_csv(path, rows)


def test_the_synthetic_export_is_the_same_shape_as_the_real_one(tmp_path: Path) -> None:
    """Otherwise the FR-50 tests above prove something about a fixture, not about ingest."""
    _synthetic_export(tmp_path)
    synthetic = CmsExport.rooted(tmp_path)
    real = CmsExport.rooted(EXPORT_ROOT)
    for reader in ("published_indicators", "published_details", "published_datapoints"):
        synthetic_columns = set(getattr(synthetic, reader)()[0])
        real_columns = set(getattr(real, reader)()[0])
        assert synthetic_columns <= real_columns, reader


def test_the_synthetic_export_ingests_end_to_end(tmp_path: Path) -> None:
    _synthetic_export(tmp_path)
    with provision() as databases:
        report = ingest_published_layer(databases.read_model, CmsExport.rooted(tmp_path))
    assert (report.indicators, report.details, report.datapoints) == (1, 1, 1)
    assert report.national_rows == 1
    assert report.analyses_available == 1


def test_the_unpublished_port_over_the_synthetic_export(tmp_path: Path) -> None:
    _synthetic_export(tmp_path)
    catalogue = UnpublishedCatalog.from_export(CmsExport.rooted(tmp_path))
    assert [entry.name_en for entry in catalogue.names()] == ["An indicator nobody approved"]
    assert catalogue.holds("an indicator nobody approved")
    assert not catalogue.holds("A published indicator")
