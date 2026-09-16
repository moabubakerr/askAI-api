"""The structural facts stage 2 discriminates on, read off the published export.

Purity: IO -- it reads the CMS export through the published-layer reader and nothing else.

Story 2.4 names six signals, and four of them are questions about the catalogue rather
than about the question: which periods a detail publishes, which grains that implies,
which countries it benchmarks against, what shape its unit is, and which group or sector
its indicator belongs to. This module reads those off the export at build time so that a
candidate can carry them as values.

**Coverage, never content.** Every fact here says that a row *exists*. Not one says what
is in it. ``P03`` carries the published values and this module reads its keys -- detail,
period, country -- and discards everything else in the row before it reaches a
:class:`~askai.ports.resolution.CandidateFacts`. That is the same line ``CataloguePort``
draws for the binder, drawn again here, because stage 2 deciding *which* indicator the
reader meant must not be able to look at a figure while deciding.

**The unit is carried as published, not as a shape.** Classifying ``bn QAR`` as an amount
is a reviewed decision and lives in ``rules/`` (``R-RESOLVE-UNIT-SHAPES``). Baking the
classification into the generation file would freeze one reviewer's reading of it into
every index ever built, and re-deriving a shape would then be a rebuild rather than a rule
edit -- which is backwards, because the whole point of AD-11 is that the reviewed thing is
the cheap thing to change.

**The entity is folded at build time.** The signal asks whether the reader's question
names the sector, and that comparison is against a folded question, so the entity name is
put through the engine's one ``normalise()`` (AD-26) here rather than 289 times per
question. Both published languages are kept: a reader writes *"the tourism sector"* or
*"قطاع السياحة"*, and an entity findable in only one of them is finding 121 again.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from askai.adapters.readmodel.export import CmsExport, Row
from askai.adapters.readmodel.ingest import CONFIDENTIAL
from askai.domain.normalise import normalise

__all__ = ["DetailFacts", "PublishedPeriod", "detail_facts"]

_INDICATOR_ID: Final = "PublishedIndicatorId"
_DETAIL_ID: Final = "PublishedIndicatorDetailId"
_PRIORITY_ID: Final = "IndicatorPriorityTypeId"
_ENTITY_ID: Final = "IndicatorEntityTypeId"
_CLASSIFICATION: Final = "EntityClassificationName"
_UNIT: Final = "UnitEN"
_PERIOD: Final = "Period"
_COUNTRY: Final = "CountryId"

#: The separator joining an entity's two published spellings in one column. A tab, because
#: an entity name may contain any punctuation a publisher chose but cannot contain this.
ENTITY_SEPARATOR: Final = "\t"


@dataclass(frozen=True, slots=True)
class PublishedPeriod:
    """One (period, country) key a detail publishes a row for. A key, never a value."""

    period: str
    country_id: str | None


@dataclass(frozen=True, slots=True)
class DetailFacts:
    """Everything the generation records about one detail, ready to be written."""

    detail_id: str
    indicator_id: str
    unit_name: str
    entity_folded: str
    classification: str
    periods: tuple[PublishedPeriod, ...]


def _cell(row: Row, column: str) -> str:
    return row.get(column, "").strip()


def _confidential(export: CmsExport) -> frozenset[str]:
    """The priority-type ids FR-50 refuses, read the way the ingest reads them."""
    return frozenset(
        _cell(row, "Id")
        for row in export.reference_priority_types()
        if _cell(row, "NameEN") == CONFIDENTIAL
    )


def _entity_names(export: CmsExport) -> Mapping[str, tuple[str, str]]:
    """Each entity id to its two published spellings, as published."""
    return {
        _cell(row, "Id").upper(): (_cell(row, "NameEN"), _cell(row, "NameAR"))
        for row in export.entity_names()
        if _cell(row, "Id")
    }


def _folded_entity(names: tuple[str, str] | None) -> str:
    """An entity's spellings, folded once and joined, or empty when it has none.

    Folded here rather than at query time because the comparison is always against a
    folded question and the answer never changes between builds. Blank spellings are
    dropped rather than joined as empties: an empty side would fold to ``""``, and ``""``
    is a substring of every question, so the signal would agree with everything.
    """
    if names is None:
        return ""
    folded = [normalise(name) for name in names]
    return ENTITY_SEPARATOR.join(part for part in folded if part)


def detail_facts(export: CmsExport) -> tuple[DetailFacts, ...]:
    """Every answerable detail's structural facts, in export order.

    A detail whose indicator is confidential or absent is skipped, exactly as
    :mod:`askai.adapters.index.names` skips its surfaces: a detail with no answerable
    parent is not a candidate, and facts for one would describe something no question may
    reach.
    """
    refused = _confidential(export)
    indicators = {
        _cell(row, _INDICATOR_ID): row
        for row in export.published_indicators()
        if _cell(row, _PRIORITY_ID) not in refused
    }
    entities = _entity_names(export)
    periods = _periods_by_detail(export)

    facts: list[DetailFacts] = []
    for detail in export.published_details():
        indicator_id = _cell(detail, _INDICATOR_ID)
        indicator = indicators.get(indicator_id)
        if indicator is None:
            continue
        detail_id = _cell(detail, _DETAIL_ID)
        entity_id = _cell(indicator, _ENTITY_ID).upper()
        facts.append(
            DetailFacts(
                detail_id=detail_id,
                indicator_id=indicator_id,
                unit_name=_cell(detail, _UNIT),
                entity_folded=_folded_entity(entities.get(entity_id)),
                classification=_cell(indicator, _CLASSIFICATION),
                periods=tuple(periods.get(detail_id, ())),
            )
        )
    return tuple(facts)


def _periods_by_detail(export: CmsExport) -> Mapping[str, list[PublishedPeriod]]:
    """The (period, country) keys each detail publishes, read off the datapoints.

    The value columns of ``P03`` are never touched. This reads three key columns and
    discards the row, which is what keeps a *coverage* fact from becoming a figure.
    """
    found: dict[str, list[PublishedPeriod]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for row in export.published_datapoints():
        detail_id = _cell(row, _DETAIL_ID)
        period = _cell(row, _PERIOD)
        if not detail_id or not period:
            continue
        country = _cell(row, _COUNTRY)
        key = (detail_id, period, country)
        if key in seen:
            continue
        seen.add(key)
        found[detail_id].append(
            PublishedPeriod(period=period, country_id=country or None)
        )
    return found
