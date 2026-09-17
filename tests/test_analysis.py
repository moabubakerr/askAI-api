"""The ``analysis`` table: the analyst commentary the ingest used to count and discard.

Asserted against the real export in ``data/`` and against the database the schema step
actually builds. Every number here is a measurement of that export, so a disagreement is
evidence about the data rather than an expectation to relax.

Two stories contradicted each other and the contradiction is what this table settles:
Story 1.6 said "create Epic 1's tables" and named five, Story 1.8 said "load the 1,031
analyses". The ingest agent refused to invent a table and wrote a test asserting both the
count and the absence. This file replaces that absence with the rows.

Nothing here needs a service, an environment variable or a network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.commentary import ReadModelCommentary
from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import IngestReport, ingest_published_layer
from askai.adapters.readmodel.schema import ANALYSIS, OWNER
from askai.adapters.store.database import SCHEMA_VERSION
from askai.adapters.store.provision import TABLE_OWNERS, Databases, provision
from askai.domain.period import Period
from askai.messages.lang import Lang
from askai.ports.commentary import Commentary, CommentaryUnavailable

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: Measured on this export. Written as constants so a drift has to change a number a
#: reviewer can see rather than an assertion buried in a body.
ANALYSES: Final = 1_031

#: Rows carrying a substantive English summary -- what Story 2 can actually quote. 652 of
#: 8,127 datapoints is 8% coverage, which is why an answer with no commentary is the
#: normal case rather than a fault.
WITH_ENGLISH_SUMMARY: Final = 652

#: Rows carrying markup that decodes to nothing at all in **any** of the eight analyst
#: prose columns -- ``<p>&nbsp;</p>`` and its relatives. The briefed number, and the one
#: that matters: these are already a reported rejection class and must stay one.
DECODING_TO_NOTHING: Final = 14

#: The same count over all ten columns, the two SRO notes included. Two further rows
#: carry an SRO note and nothing else, so the number a reader sees depends on which
#: columns are called analyst prose; both are asserted so neither can move unseen.
DECODING_TO_NOTHING_WITH_SRO: Final = 16

#: Rows whose prose columns are blank in the export before anything is decoded. Kept,
#: not dropped: the row records that an analysis exists for this datapoint and says
#: nothing, which is a different fact from no analysis existing.
BLANK_IN_THE_EXPORT: Final = 349

#: The export's column names, which are not the table's. ``NPCAnalysis*`` is published on
#: 7 rows in English and ``Sro*`` on 135; neither is a reason to leave a column out.
PROSE_COLUMNS: Final = (
    ("SroEN", "sro_en"),
    ("SroAR", "sro_ar"),
    ("SummaryEN", "summary_en"),
    ("SummaryAR", "summary_ar"),
    ("DetailedAnalysisEN", "detailed_en"),
    ("DetailedAnalysisAR", "detailed_ar"),
    ("NPCAnalysisEN", "npc_en"),
    ("NPCAnalysisAR", "npc_ar"),
    ("BenchmarkEN", "benchmark_en"),
    ("BenchmarkAR", "benchmark_ar"),
)

#: The eight the brief calls analyst prose: the SRO note is a responsible owner's remark
#: rather than an analysis of the figure, so the rejection class is counted without it.
ANALYST_PROSE_COLUMNS: Final = PROSE_COLUMNS[2:]


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


def _count(connection: sqlite3.Connection, sql: str, *parameters: object) -> int:
    count = _scalar(connection, sql, *parameters)
    assert isinstance(count, int)
    return count


# ----------------------------------------------------------------- the table exists


def test_the_table_is_owned_by_the_read_model() -> None:
    """One writer, per AD-20. The ingest fills it and nothing else may."""
    assert TABLE_OWNERS["analysis"] == OWNER
    assert ANALYSIS.owner == OWNER


def test_the_schema_version_moved() -> None:
    """A new table is a new shape, and an estate at the old one must not be adopted.

    Stated as a test rather than left to the reviewer because the operational
    consequence is real: every provisioned estate fails at startup with a version
    mismatch until it is re-provisioned and refreshed. That is Story 1.6 working, not a
    regression -- but it is only safe while the number actually moves.
    """
    assert SCHEMA_VERSION == 2


def test_the_table_is_in_the_read_model_and_not_the_index(
    ingested: tuple[Databases, IngestReport],
) -> None:
    """It is a keyed lookup, so it lives with the other keyed lookups (AD-20).

    The semantic index answers *which* passage is relevant. This table holds the
    passage, fetched by ``(detail, period, country)`` like any other published row.
    """
    databases = ingested[0]
    assert _count(databases.read_model, "SELECT COUNT(*) FROM analysis") >= 0
    with pytest.raises(sqlite3.OperationalError):
        databases.semantic_index.execute("SELECT 1 FROM analysis")


# ------------------------------------------------------------------ the measured counts


def test_every_published_analysis_is_stored(
    report: IngestReport, read_model: sqlite3.Connection
) -> None:
    assert report.analyses_available == ANALYSES
    assert report.analyses == ANALYSES
    assert _count(read_model, "SELECT COUNT(*) FROM analysis") == ANALYSES


def test_none_was_dropped_for_want_of_a_datapoint(report: IngestReport) -> None:
    """All 1,031 explain a datapoint that survived the confidentiality filter.

    Zero today. The branch exists so that a future export whose commentary explains a
    confidential figure drops it and says so, rather than storing a note whose figure
    FR-50 forbids anyone to see.
    """
    assert report.analyses_without_a_datapoint == 0


def test_the_substantive_english_summaries_are_counted(
    report: IngestReport, read_model: sqlite3.Connection
) -> None:
    assert report.analyses_with_english_summary == WITH_ENGLISH_SUMMARY
    assert (
        _count(read_model, "SELECT COUNT(*) FROM analysis WHERE summary_en IS NOT NULL")
        == WITH_ENGLISH_SUMMARY
    )


def test_the_rows_that_say_nothing_are_kept_and_counted(
    report: IngestReport, read_model: sqlite3.Connection
) -> None:
    """A row with no prose is stored, because "an analysis exists and says nothing" is
    a different fact from "no analysis exists", and only the first is representable as
    a row."""
    empty = " AND ".join(f"{column} IS NULL" for _, column in PROSE_COLUMNS)
    assert report.analyses_without_prose == BLANK_IN_THE_EXPORT + DECODING_TO_NOTHING_WITH_SRO
    assert (
        _count(read_model, f"SELECT COUNT(*) FROM analysis WHERE {empty}")
        == report.analyses_without_prose
    )


def test_the_rows_whose_markup_decodes_to_nothing_stay_a_rejection_class(
    export: CmsExport,
) -> None:
    """14 rows publish markup in the analyst columns that renders as nothing at all.

    They are already reported as a rejection class. Counted from the export through the
    same decoder the ingest uses, so the number moves only when the data or the decoder
    does -- and either is something a reviewer should be made to look at.
    """

    def decodes_to_nothing(row: dict[str, str], columns: tuple[tuple[str, str], ...]) -> bool:
        raw = tuple(row[source].strip() for source, _ in columns)
        return any(raw) and not any(published_text(cell) for cell in raw)

    analyses = export.published_analyses()
    assert sum(decodes_to_nothing(row, ANALYST_PROSE_COLUMNS) for row in analyses) == (
        DECODING_TO_NOTHING
    )
    assert sum(decodes_to_nothing(row, PROSE_COLUMNS) for row in analyses) == (
        DECODING_TO_NOTHING_WITH_SRO
    )


# ------------------------------------------------------- the key, and what it guarantees


def test_the_key_is_the_datapoint_identity(read_model: sqlite3.Connection) -> None:
    """Every stored analysis carries the key of the datapoint it explains, exactly.

    The foreign key is on ``source_datapoint_id``, which is NOT NULL on both sides and
    therefore actually enforced; these three columns are the copy a question can be
    spelled in. This asserts the copy agrees with what it was copied from -- no
    constraint can, because a composite foreign key onto a nullable column is satisfied
    by default and 5,263 of 8,127 rows are national.
    """
    mismatched = _count(
        read_model,
        """
        SELECT COUNT(*) FROM analysis
        JOIN datapoint USING (source_datapoint_id)
        WHERE analysis.detail_id IS NOT datapoint.detail_id
           OR analysis.period IS NOT datapoint.period
           OR analysis.country_id IS NOT datapoint.country_id
        """,
    )
    assert mismatched == 0


def test_every_analysis_reaches_its_datapoint(read_model: sqlite3.Connection) -> None:
    assert (
        _count(
            read_model,
            """
            SELECT COUNT(*) FROM analysis
            WHERE source_datapoint_id NOT IN (SELECT source_datapoint_id FROM datapoint)
            """,
        )
        == 0
    )


def test_a_note_on_an_absent_datapoint_is_refused(read_model: sqlite3.Connection) -> None:
    """The foreign key is on, so an analysis cannot outlive the figure it explains."""
    with pytest.raises(sqlite3.IntegrityError):
        read_model.execute(
            """
            INSERT INTO analysis (
                detail_id, period, country_id, source_analysis_id, source_datapoint_id
            )
            SELECT detail_id, period, country_id, 'invented', 'no-such-datapoint'
            FROM datapoint LIMIT 1
            """
        )
    read_model.rollback()


def test_one_national_note_per_detail_and_period(read_model: sqlite3.Connection) -> None:
    """Two NULLs compare distinct, so the primary key does not constrain national rows.

    The partial unique index does. Without it a second national note on the same detail
    and period would insert cleanly and the fetch would return whichever came first.
    """
    row = read_model.execute(
        "SELECT detail_id, period FROM analysis WHERE country_id IS NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    with pytest.raises(sqlite3.IntegrityError):
        read_model.execute(
            """
            INSERT INTO analysis (
                detail_id, period, country_id, source_analysis_id, source_datapoint_id
            ) VALUES (?, ?, NULL, 'invented', 'invented')
            """,
            (row[0], row[1]),
        )
    read_model.rollback()


# ------------------------------------------------------------------- the prose itself


def test_the_stored_prose_is_the_decoded_text(
    export: CmsExport, read_model: sqlite3.Connection
) -> None:
    """Decoded once, at ingest, by the one decoder -- no answer-time path strips markup.

    Checked over every row and every column rather than on a sample: the export carries
    this prose as CMS-authored HTML on most rows, and a single column left raw is a
    ``<ul><li><p>`` reaching a reader.
    """
    stored = {
        str(row[0]): row[1:]
        for row in read_model.execute(
            "SELECT source_analysis_id, "
            + ", ".join(column for _, column in PROSE_COLUMNS)
            + " FROM analysis"
        )
    }
    assert len(stored) == ANALYSES
    for row in export.published_analyses():
        kept = stored[row["PublishedDataPointAnalysisId"]]
        expected = tuple(published_text(row[source].strip()) for source, _ in PROSE_COLUMNS)
        assert kept == expected


def test_the_stored_prose_carries_no_markup_but_for_one_escaped_span(
    read_model: sqlite3.Connection,
) -> None:
    """1,030 of 1,031 rows reach the table with no angle bracket left in any column.

    The exception is one Arabic SRO note, and it is the documented cost of ``content``'s
    order of operations rather than a missed tag. That module strips markup *before*
    unescaping, deliberately: an escaped tag is an angle bracket the author typed and
    wanted shown, and decoding first would delete it. This row has both -- a typed ``<``
    and an escaped ``<span style=...>`` -- so unescaping reassembles a span out of text
    that was never markup when the stripper ran.

    Pinned at one rather than asserted away. It is a finding for ``content``'s owner (a
    second strip after unescaping would fix it and would also delete the typed bracket
    the current order exists to protect), and a count is what makes a second such row
    arrive as a failure instead of as prose with ``style="color:black"`` in it.
    """
    columns = " OR ".join(f"{column} LIKE '%<%>%'" for _, column in PROSE_COLUMNS)
    assert _count(read_model, f"SELECT COUNT(*) FROM analysis WHERE {columns}") == 1


def test_a_summary_is_quoted_whole_and_not_truncated(read_model: sqlite3.Connection) -> None:
    """The longest published summary is stored entire.

    An answer quotes an analyst rather than paraphrasing, so a column that silently
    clipped at some length would be the engine rewriting a published statement.
    """
    longest = _scalar(
        read_model,
        "SELECT MAX(LENGTH(detailed_en)) FROM analysis WHERE detailed_en IS NOT NULL",
    )
    assert isinstance(longest, int)
    assert longest > 1_000


def test_a_refresh_replaces_the_commentary_rather_than_appending_it(
    export: CmsExport,
) -> None:
    """Twice ingested is once stored. The clear order is children first, so the foreign
    keys hold at every point of the refresh rather than only at its end."""
    with provision() as databases:
        ingest_published_layer(databases.read_model, export)
        second = ingest_published_layer(databases.read_model, export)
        assert second.analyses == ANALYSES
        assert _count(databases.read_model, "SELECT COUNT(*) FROM analysis") == ANALYSES


# ------------------------------------------------------------------ fetching one note


def test_a_note_is_fetched_by_the_complete_key(read_model: sqlite3.Connection) -> None:
    """The adapter takes the whole (detail, period, country) key and nothing less."""
    row = read_model.execute(
        """
        SELECT detail_id, period, country_id, source_datapoint_id
        FROM analysis WHERE summary_en IS NOT NULL LIMIT 1
        """
    ).fetchone()
    assert row is not None
    detail_id, period, country_id, source_datapoint_id = row

    note = ReadModelCommentary(read_model).note(str(detail_id), Period(str(period)), country_id)
    assert note is not None
    assert note.source_datapoint_id == source_datapoint_id
    assert note.detail_id == detail_id
    assert note.period == Period(str(period))
    assert note.country_id == country_id
    assert note.quotable(Lang.EN)


def test_a_key_with_no_note_is_a_miss_and_not_a_failure(
    read_model: sqlite3.Connection,
) -> None:
    """8% coverage means nine calls in ten miss, and a miss is the published state.

    Asserted against a real datapoint that publishes no commentary rather than an
    invented key, because the case that matters is the common one -- a figure the
    engine can answer and an analyst never wrote about.
    """
    row = read_model.execute(
        """
        SELECT detail_id, period, country_id FROM datapoint
        WHERE source_datapoint_id NOT IN (SELECT source_datapoint_id FROM analysis)
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    found = ReadModelCommentary(read_model).note(str(row[0]), Period(str(row[1])), row[2])
    assert found is None


def test_the_national_scope_is_selected_as_an_absent_country(
    read_model: sqlite3.Connection,
) -> None:
    """``IS NULL``, never ``= ?``. Two NULLs do not compare equal in SQL, so the
    parameterised form would lose every national note while looking correct (AD-5)."""
    row = read_model.execute(
        "SELECT detail_id, period FROM analysis WHERE country_id IS NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    commentary = ReadModelCommentary(read_model)
    assert commentary.note(str(row[0]), Period(str(row[1])), None) is not None
    # The same key with a country named is a different key, and holds nothing.
    assert commentary.note(str(row[0]), Period(str(row[1])), "no-such-country") is None


def test_a_dead_store_is_a_typed_failure_not_an_absence(
    read_model: sqlite3.Connection,
) -> None:
    """The distinction the port is declared for: a store that stopped answering must
    not reach a reader as "no commentary is published for this period"."""
    closed = sqlite3.connect(":memory:")
    closed.close()
    with pytest.raises(CommentaryUnavailable):
        ReadModelCommentary(closed).note("any", Period("2025"), None)


def test_the_quoted_passage_prefers_the_summary_over_the_detailed_analysis() -> None:
    """The summary is what an analyst wrote to be read *beside* the figure; the
    detailed analysis is what they wrote to be read instead of it. Falling back the
    other way would put several paragraphs where one sentence was published."""
    both = Commentary(
        detail_id="d",
        period=Period("2025"),
        country_id=None,
        source_datapoint_id="dp",
        summary=("the summary", None),
        detailed=("the detailed analysis", None),
    )
    assert both.quotable(Lang.EN) == "the summary"

    detailed_only = Commentary(
        detail_id="d",
        period=Period("2025"),
        country_id=None,
        source_datapoint_id="dp",
        detailed=("the detailed analysis", None),
    )
    assert detailed_only.quotable(Lang.EN) == "the detailed analysis"


def test_a_passage_never_crosses_languages() -> None:
    """An Arabic answer carrying an English paragraph is finding 121's failure with a
    source_ref attached: the reader asked in Arabic and would be shown text they may
    not read, sourced as though it were approved for them. Nothing, instead."""
    english_only = Commentary(
        detail_id="d",
        period=Period("2025"),
        country_id=None,
        source_datapoint_id="dp",
        summary=("the summary", None),
    )
    assert english_only.quotable(Lang.EN) == "the summary"
    assert english_only.quotable(Lang.AR) is None


def test_the_adapter_only_reads() -> None:
    """AD-20: `analysis` has one writer, the ingest. A fetch that wrote it is a second."""
    adapter = PROJECT_ROOT / "src" / "askai" / "adapters" / "readmodel" / "commentary.py"
    source = adapter.read_text(encoding="utf-8")
    for statement in ("INSERT", "UPDATE ", "DELETE", "CREATE", "DROP"):
        assert statement not in source.upper().replace("UPDATEDAT", "")
