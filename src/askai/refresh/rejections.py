"""What the export offered and the read model refused, by class, with counts and examples.

Purity: IO, never on the answer path.

Story 1.10. A row ingest does not load is not a row that did not exist, and the whole
point of this module is that the difference is written down. FR-110 asks for counts
*and* worked examples, and the two do different jobs: the count is what an auditor reads
six months later, and the examples are what a data steward opens the CMS with. A report
carrying only counts tells a steward that sixty-one things are wrong and nothing about
which sixty-one.

The survey is deliberately **separate from the ingest** and reads the export a second
time. Ingest's job is to refuse -- structurally, by filtering and by constraint -- and
folding a rejection census into it would make the census a side effect of the writer,
counted by the same code that decided. Here the export is examined on its own terms, and
the one number both sides compute (the confidential exclusion) is cross-checked by
:mod:`askai.refresh.run` rather than taken from one of them.

Four classes, and the fourth is not a drop:

``publication-state`` is content the CMS holds and publication did not approve, plus
anything the confidentiality flag removes. ``unresolvable-reference`` is a row that
names something nothing holds -- an indicator, a detail, a country, an author.
``malformed-content`` is a cell that is present and says nothing: markup with no text,
an identifier that is not one. ``ambiguous-identity`` is the odd one out: those rows are
loaded, and their identity is settled by the reviewed alias table rather than by being
thrown away. It is reported alongside the rest because a steward who is told two country
reference rows carry one ISO code can fix the reference table, and a steward who is told
nothing will meet the same two rows again next month.

Nothing here is swallowed. Every count is a count of rows this module walked, and no
class is reported as a bare total: each carries the reason it was refused in the same
record as the number.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.export import CmsExport, Row
from askai.adapters.readmodel.ingest import CONFIDENTIAL
from askai.domain.period import Period, PeriodFormatError
from askai.rules.loader import rules

__all__ = [
    "EXAMPLES_RULE",
    "RefreshSourceError",
    "Rejection",
    "RejectionClass",
    "RejectionExample",
    "counts_by_class",
    "example_budget",
    "survey_rejections",
]

#: The rule carrying how many worked examples each rejection keeps. Named here so a
#: rename in the data file fails at startup rather than silently reporting no examples.
EXAMPLES_RULE: Final = "R-REFRESH-REJECTION-EXAMPLES"
_EXAMPLES_KEY: Final = "examples_per_rejection"

#: The base-layer files the survey reads. Ingest reads neither -- the base layer has no
#: table in the read model -- but the defects live there, so the census does.
_BASE_CATALOGUE: Final = "Item_2_Indicators_Catalog"
_BASE_DETAILS: Final = "Item_4_IndicatorDetails"

#: The two loose content files. They sit beside the CMS directory, not inside it, and
#: carry the author reference the published layer has no column for.
_ARTICLES: Final = "Articles.csv"
_AUTHORS: Final = "Champions.csv"

#: An identifier in this export is a GUID. A value in an id column that is not one is a
#: placeholder, not a reference: it names nothing and never could, so it is malformed
#: content rather than an unresolvable reference, and the two are counted apart.
_IDENTIFIER: Final = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.IGNORECASE
)

#: The published prose columns of an analysis row, in both languages. An analysis whose
#: every one of these renders to nothing, while at least one arrived non-blank, carried
#: markup and no text.
_ANALYSIS_PROSE: Final = (
    "SummaryEN",
    "SummaryAR",
    "DetailedAnalysisEN",
    "DetailedAnalysisAR",
    "NPCAnalysisEN",
    "NPCAnalysisAR",
    "BenchmarkEN",
    "BenchmarkAR",
)

#: The published definition columns. "Defination" is the export's spelling.
_DEFINITION_PROSE: Final = ("DefinationEN", "DefinationAR")


class RefreshSourceError(RuntimeError):
    """A file the census reads is missing or unreadable, so the census is incomplete.

    Raised rather than skipped. A survey that quietly omitted the author reference would
    report zero unresolvable authors, which is the same number a clean export gives.
    """


class RejectionClass(StrEnum):
    """Why something the export carried is not answerable, at the level FR-110 names."""

    PUBLICATION_STATE = "publication-state"
    UNRESOLVABLE_REFERENCE = "unresolvable-reference"
    MALFORMED_CONTENT = "malformed-content"
    #: Loaded, not dropped -- see the module docstring.
    AMBIGUOUS_IDENTITY = "ambiguous-identity"


@dataclass(frozen=True, slots=True)
class RejectionExample:
    """One row a steward can open, named by its own identifier and by what is wrong."""

    #: How the source names the row -- an id, a code, a filename. Never a row number.
    identifier: str
    #: What was wrong with this particular row, in enough words to act on.
    detail: str


@dataclass(frozen=True, slots=True)
class Rejection:
    """One reason, its full count, and up to the budgeted number of worked examples."""

    rejection_class: RejectionClass
    reason: str
    #: Every row that matched, never truncated.
    count: int
    examples: tuple[RejectionExample, ...]
    #: Where the rows were read from, so the steward knows which file to open.
    source: str

    def __post_init__(self) -> None:
        if self.count < len(self.examples):
            raise ValueError(
                f"{self.reason!r} reports {self.count} rows and carries "
                f"{len(self.examples)} examples; the count is the whole of it and the "
                "examples are a sample of that, never the other way round"
            )

    @property
    def examples_are_truncated(self) -> bool:
        """Did the budget cut the examples? Said on the record, not inferred by a reader."""
        return self.count > len(self.examples)


def example_budget() -> int:
    """How many worked examples each rejection keeps, from the rule file (AD-11)."""
    budget = rules().value(EXAMPLES_RULE, _EXAMPLES_KEY)
    if not isinstance(budget, int) or isinstance(budget, bool):
        raise RefreshSourceError(
            f"{EXAMPLES_RULE} carries `{_EXAMPLES_KEY}` as {budget!r}; it is a count of "
            "example rows and must be an integer"
        )
    return budget


# ------------------------------------------------------------------ reading the sources


def _read_csv(path: Path) -> tuple[Row, ...]:
    if not path.is_file():
        raise RefreshSourceError(
            f"{path} is missing; the rejection census reads it, and a census that "
            "silently skipped a source would report a clean export"
        )
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return tuple(
                {str(key): str(value or "") for key, value in row.items()}
                for row in csv.DictReader(handle)
            )
    except OSError as error:
        raise RefreshSourceError(f"{path} cannot be read -- {error}") from error


def _by_prefix(directory: Path, prefix: str) -> tuple[Row, ...]:
    matches = sorted(directory.glob(f"{prefix}*.csv"))
    if len(matches) != 1:
        raise RefreshSourceError(
            f"{len(matches)} files match {prefix}*.csv in {directory}; the census reads "
            "exactly one export, and two in a directory would be surveyed as one"
        )
    return _read_csv(matches[0])


def _cell(row: Row, column: str) -> str:
    return row.get(column, "").strip()


def _fold(value: str) -> str:
    """Ids are spelled in either case across the export's files; compared in one."""
    return value.casefold()


# ------------------------------------------------------------------- building a finding


def _rejection(
    rejection_class: RejectionClass,
    reason: str,
    source: str,
    matches: Sequence[RejectionExample],
    budget: int,
) -> Rejection:
    ordered = sorted(matches, key=lambda example: (example.identifier, example.detail))
    return Rejection(
        rejection_class=rejection_class,
        reason=reason,
        count=len(ordered),
        examples=tuple(ordered[:budget]),
        source=source,
    )


# --------------------------------------------------------------------- the four classes


def _publication_state(export: CmsExport, budget: int) -> Iterable[Rejection]:
    published = export.published_indicators()
    approved = {_fold(_cell(row, "SourceIndicatorId")) for row in published}
    base = _by_prefix(export.cms_directory, _BASE_CATALOGUE)
    withheld = [
        RejectionExample(
            identifier=_cell(row, "Id"),
            detail=f"held in the CMS as {_cell(row, 'NameEN') or 'an unnamed entry'}",
        )
        for row in base
        if _fold(_cell(row, "Id")) not in approved
    ]
    yield _rejection(
        RejectionClass.PUBLICATION_STATE,
        "the CMS holds this indicator and publication never approved it, so it has no "
        "row in the read model and is reachable only as a name",
        _BASE_CATALOGUE,
        withheld,
        budget,
    )

    confidential_ids = {
        _cell(row, "Id")
        for row in export.reference_priority_types()
        if _cell(row, "NameEN") == CONFIDENTIAL
    }
    flagged = [
        # The name is deliberately not carried. FR-50 keeps a confidential indicator out
        # of every count, list and total; a report that spelled its name would have put
        # it back into one.
        RejectionExample(
            identifier=_cell(row, "PublishedIndicatorId"),
            detail="carries the confidentiality flag",
        )
        for row in published
        if _cell(row, "IndicatorPriorityTypeId") in confidential_ids
    ]
    yield _rejection(
        RejectionClass.PUBLICATION_STATE,
        "the indicator is flagged confidential, so it is excluded from the read model "
        "entirely and cannot appear in any answer, count, list or group total",
        "P01_Published_Indicators",
        flagged,
        budget,
    )


def _unresolvable_references(export: CmsExport, budget: int) -> Iterable[Rejection]:
    base_catalogue = {
        _fold(_cell(row, "Id"))
        for row in _by_prefix(export.cms_directory, _BASE_CATALOGUE)
    }
    orphans = [
        RejectionExample(
            identifier=_cell(row, "IndicatorDetailId"),
            detail=f"names indicator {_cell(row, 'IndicatorId') or '(blank)'}, which the "
            "catalogue does not hold",
        )
        for row in _by_prefix(export.cms_directory, _BASE_DETAILS)
        if _fold(_cell(row, "IndicatorId")) not in base_catalogue
    ]
    yield _rejection(
        RejectionClass.UNRESOLVABLE_REFERENCE,
        "the detail names an indicator no catalogue row holds, so there is nothing for "
        "it to hang from and no answer it could contribute to",
        _BASE_DETAILS,
        orphans,
        budget,
    )

    indicators = {_cell(row, "PublishedIndicatorId") for row in export.published_indicators()}
    stranded_details = [
        RejectionExample(
            identifier=_cell(row, "PublishedIndicatorDetailId"),
            detail=f"names published indicator {_cell(row, 'PublishedIndicatorId') or '(blank)'}, "
            "which is not in the published catalogue",
        )
        for row in export.published_details()
        if _cell(row, "PublishedIndicatorId") not in indicators
    ]
    yield _rejection(
        RejectionClass.UNRESOLVABLE_REFERENCE,
        "the published detail names an indicator the published catalogue does not "
        "carry, so it is not loaded",
        "P02_Published_IndicatorDetails",
        stranded_details,
        budget,
    )

    details = {_cell(row, "PublishedIndicatorDetailId") for row in export.published_details()}
    countries = {_cell(row, "Id") for row in export.reference_countries()}
    stranded_points: list[RejectionExample] = []
    for row in export.published_datapoints():
        detail_id = _cell(row, "PublishedIndicatorDetailId")
        country_id = _cell(row, "CountryId")
        if detail_id not in details:
            stranded_points.append(
                RejectionExample(
                    identifier=_cell(row, "PublishedDataPointId"),
                    detail=f"names detail {detail_id or '(blank)'}, which is not published",
                )
            )
        elif country_id and country_id not in countries:
            stranded_points.append(
                RejectionExample(
                    identifier=_cell(row, "PublishedDataPointId"),
                    detail=f"names country {country_id}, which the reference does not hold",
                )
            )
    yield _rejection(
        RejectionClass.UNRESOLVABLE_REFERENCE,
        "the datapoint names a detail or a country nothing published holds, so its "
        "figure has no key to be stored under",
        "P03_Published_DataPoints",
        stranded_points,
        budget,
    )

    yield _unresolvable_authors(export, budget)


def _unresolvable_authors(export: CmsExport, budget: int) -> Rejection:
    """Article authors that name nobody. Counted by distinct id, not by article.

    Thirty-two ids across eighty-four articles is a register problem; eighty-four is the
    same problem counted by its blast radius, and a steward fixing it works through the
    ids. The identifier on each example is therefore the author id, and the detail says
    how many articles hang off it.
    """
    known = {_fold(_cell(row, "Id")) for row in _read_csv(export.loose_directory / _AUTHORS)}
    articles = _read_csv(export.loose_directory / _ARTICLES)
    unresolved: dict[str, int] = {}
    for row in articles:
        author = _cell(row, "AuthorId")
        if not _IDENTIFIER.match(author) or _fold(author) in known:
            continue
        unresolved[author] = unresolved.get(author, 0) + 1
    return _rejection(
        RejectionClass.UNRESOLVABLE_REFERENCE,
        "the article names an author id the register does not hold, so the piece has no "
        "attributable author and no provenance an answer could cite",
        _ARTICLES,
        [
            RejectionExample(
                identifier=author,
                detail=f"named by {count} article(s); no register entry carries this id",
            )
            for author, count in unresolved.items()
        ],
        budget,
    )


def _malformed_content(export: CmsExport, budget: int) -> Iterable[Rejection]:
    empty_definitions = [
        RejectionExample(
            identifier=f"{_cell(row, 'PublishedIndicatorDetailId')}.{column}",
            detail=f"published as {_cell(row, column)[:60]!r}, which renders to no text",
        )
        for row in export.published_details()
        for column in _DEFINITION_PROSE
        if _cell(row, column) and not (published_text(_cell(row, column)) or "").strip()
    ]
    yield _rejection(
        RejectionClass.MALFORMED_CONTENT,
        "the published definition is present but carries no text once decoded -- markup "
        "with nothing in it, or a bare dash -- so it is stored as absent rather than as "
        "a definition that says nothing",
        "P02_Published_IndicatorDetails",
        empty_definitions,
        budget,
    )

    empty_analyses = [
        RejectionExample(
            identifier=_cell(row, "PublishedDataPointAnalysisId"),
            detail=f"every prose column of datapoint {_cell(row, 'PublishedDataPointId')} "
            "renders to no text",
        )
        for row in export.published_analyses()
        if any(_cell(row, column) for column in _ANALYSIS_PROSE)
        and not any(
            (published_text(_cell(row, column)) or "").strip() for column in _ANALYSIS_PROSE
        )
    ]
    yield _rejection(
        RejectionClass.MALFORMED_CONTENT,
        "the analysis carries prose columns that decode to nothing at all, so there is "
        "no analyst text behind a row that claims to have one",
        "P04_Published_DataPointAnalysis",
        empty_analyses,
        budget,
    )

    placeholder_authors = [
        RejectionExample(
            identifier=_cell(row, "Id"),
            detail=f"author id is {_cell(row, 'AuthorId')!r}, which is not an identifier",
        )
        for row in _read_csv(export.loose_directory / _ARTICLES)
        if _cell(row, "AuthorId") and not _IDENTIFIER.match(_cell(row, "AuthorId"))
    ]
    yield _rejection(
        RejectionClass.MALFORMED_CONTENT,
        "the article's author column holds a placeholder rather than an identifier, so "
        "it names nobody and never could",
        _ARTICLES,
        placeholder_authors,
        budget,
    )

    yield _rejection(
        RejectionClass.MALFORMED_CONTENT,
        "the datapoint's period cannot be read, so the grain the period carries cannot "
        "be recovered and the row has no place in the key",
        "P03_Published_DataPoints",
        list(_unreadable_periods(export.published_datapoints())),
        budget,
    )


def _unreadable_periods(datapoints: Sequence[Row]) -> Iterable[RejectionExample]:
    for row in datapoints:
        period = _cell(row, "Period")
        try:
            Period(period)
        except PeriodFormatError as error:
            yield RejectionExample(
                identifier=_cell(row, "PublishedDataPointId"),
                detail=f"period {period!r} -- {error}",
            )


def _ambiguous_identity(export: CmsExport, budget: int) -> Iterable[Rejection]:
    by_code: dict[str, list[str]] = {}
    for row in export.reference_countries():
        code = _cell(row, "Code")
        if code:
            by_code.setdefault(code, []).append(_cell(row, "NameEN"))
    shared = [
        RejectionExample(
            identifier=code,
            detail="published under " + " and ".join(sorted(names)) + ", which are one country",
        )
        for code, names in by_code.items()
        if len(names) > 1
    ]
    yield _rejection(
        RejectionClass.AMBIGUOUS_IDENTITY,
        "two reference rows publish one ISO code under different names; both rows load, "
        "and the reviewed alias table decides they are one country before any row is "
        "fetched -- so no answer shows the country twice, and the reference still needs "
        "a steward",
        "P14_Ref_Countries",
        shared,
        budget,
    )


def survey_rejections(export: CmsExport, budget: int | None = None) -> tuple[Rejection, ...]:
    """Every class of thing *export* offers that the read model does not answer from.

    *budget* of ``None`` reads the example count from the rule file. It is injectable so
    a test can state the budget it means rather than depending on the shipped one.

    Every class is reported, including the ones that matched nothing: a clean export and
    an unsurveyed one produce different reports, and a class that vanishes when it is
    empty makes those two indistinguishable.
    """
    limit = example_budget() if budget is None else budget
    return (
        *_publication_state(export, limit),
        *_unresolvable_references(export, limit),
        *_malformed_content(export, limit),
        *_ambiguous_identity(export, limit),
    )


def counts_by_class(rejections: Sequence[Rejection]) -> Mapping[RejectionClass, int]:
    """Total rows refused per class, for the one-line summary a scheduled job logs."""
    totals: dict[RejectionClass, int] = {member: 0 for member in RejectionClass}
    for rejection in rejections:
        totals[rejection.rejection_class] += rejection.count
    return totals
