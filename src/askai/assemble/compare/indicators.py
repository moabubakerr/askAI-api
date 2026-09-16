"""Indicators lined up, each at its own period and in its own unit (FR-24, FR-47).

Purity: pure.

Story 4.5, and it is the mirror image of ``countries.py``. There, the whole point is a
**common** period: countries measured at different times are not a comparison. Here, the
whole point is that periods are **not** forced into agreement -- several indicators
whose latest readings fall in different months are a perfectly good comparison, and
forcing them onto one period would either discard readings or invent them.

So each figure is shown **with its own period beside it**, and that is structural rather
than careful: ``IndicatorReading.period`` is read off the reading's own figure, and there
is no signature in this module that takes a period at all -- so there is no call through
which one indicator could be handed another's. The period a reading carries in its own
right, ``asked``, reaches only the sentence for an indicator that published *nothing*,
where there is no figure for it to be mistaken for.

**Different units are stated, not reconciled** (FR-47). Each figure is rendered in its
own published unit, and where the units differ the answer says the figures are not
directly comparable. It does not convert, it does not normalise to an index, and it does
not quietly drop the unit so that two incommensurable numbers sit next to each other
looking like a ranking. Nothing here computes across indicators at all, which is why
there is no extremum in this module: an extremum over incommensurable quantities is the
F-027 class of answer, and ``extrema.py`` takes one scope at a time for that reason.

**Each part was bound independently** (FR-12). A multi-part question reaches this module
as several readings that were each bound through the identical path; this module lines
them up and never re-binds one. There is no ``QuerySpec`` here and no field to widen.
"""

from __future__ import annotations

from askai.assemble.compare.composed import Composed
from askai.assemble.compare.readings import IndicatorReading
from askai.assemble.elements import absent, derived, measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.messages import Catalogue, Lang, render, render_period
from askai.ports.presentation import PublishedDetail

__all__ = ["IndicatorMessage", "compare_indicators", "units_differ"]


class IndicatorMessage:
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    HEADLINE = "compare.indicators_headline"
    VALUE = "compare.indicator_value"
    ABSENT = "compare.indicator_absent"
    UNITS_DIFFER = "compare.units_differ"


def compare_indicators(
    readings: tuple[IndicatorReading, ...],
    publications: dict[str, PublishedDetail],
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
) -> Composed:
    """Line *readings* up, each at its own period, each in its own published unit.

    *publications* is how each detail is published -- its name, unit and Format field,
    and who published it -- keyed by detail id. Handed in rather than looked up, because
    ``assemble/`` reads no store: an indicator whose publication is missing cannot be
    named, formatted or sourced, and is refused rather than shown half-composed.
    """
    if not readings:
        raise ValueError(
            "a cross-indicator comparison is composed from the indicators it compares; "
            "an empty list is a question that bound nothing, which is refused earlier"
        )
    missing = tuple(
        reading.detail_id for reading in readings if reading.detail_id not in publications
    )
    if missing:
        raise KeyError(
            f"no published detail for {missing}; a figure whose detail the published "
            "catalogue does not hold cannot be named, formatted or sourced (AD-6)"
        )

    lines = [
        _indicator_line(
            reading, publications[reading.detail_id], catalogue, formatter, placement, lang
        )
        for reading in readings
    ]
    notes = _unit_note(readings, publications, catalogue, lang)
    headline = _headline(readings, publications, catalogue, lang)
    return Composed(elements=(headline, *lines, *notes))


def units_differ(
    readings: tuple[IndicatorReading, ...], publications: dict[str, PublishedDetail]
) -> bool:
    """Are these indicators published in more than one unit?

    Compared on the published unit strings exactly as published. Two details publishing
    ``%`` and ``Percent`` would read as differing here, and that is the safe direction to
    be wrong in: over-stating that two figures are not commensurable costs a sentence,
    and under-stating it is FR-47's defect.
    """
    return len({publications[reading.detail_id].unit for reading in readings}) > 1


def _indicator_line(
    reading: IndicatorReading,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
) -> Placed:
    """One indicator's row: its figure and **its own** period, or the gap where one is not."""
    role = Role.SERIES
    if reading.figure is None:
        return Placed(
            element=absent(
                render(
                    catalogue,
                    lang,
                    IndicatorMessage.ABSENT,
                    detail=published.name,
                    period=render_period(catalogue, lang, reading.asked),
                ),
                _anchor(reading, published),
            ),
            role=role,
        )
    written = formatter.format(
        reading.figure.value,
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        lang,
    )
    return Placed(
        element=measured(
            render(
                catalogue,
                lang,
                IndicatorMessage.VALUE,
                detail=published.name,
                value=written.value,
                unit=written.unit,
                # Read off the figure, so the period shown is the period the figure was
                # read at and there is no second opinion about it (FR-24).
                period=render_period(catalogue, lang, reading.figure.period),
            ),
            _anchor(reading, published),
        ),
        role=role,
    )


def _headline(
    readings: tuple[IndicatorReading, ...],
    publications: dict[str, PublishedDetail],
    catalogue: Catalogue,
    lang: Lang,
) -> Placed:
    """*"Compared across indicators, each at its own latest period."*

    The statement that says what the comparison did, and specifically what it did
    **not** do: it did not align the periods. A reader who is not told that will assume
    it, which is the false alignment FR-24 forbids.
    """
    first = readings[0]
    return Placed(
        element=derived(
            render(catalogue, lang, IndicatorMessage.HEADLINE),
            _anchor(first, publications[first.detail_id]),
        ),
        role=Role.SCOPE,
    )


def _unit_note(
    readings: tuple[IndicatorReading, ...],
    publications: dict[str, PublishedDetail],
    catalogue: Catalogue,
    lang: Lang,
) -> tuple[Placed, ...]:
    """FR-47's caveat, attached when and only when the units actually differ."""
    if not units_differ(readings, publications):
        return ()
    first = readings[0]
    return (
        Placed(
            element=derived(
                render(catalogue, lang, IndicatorMessage.UNITS_DIFFER),
                _anchor(first, publications[first.detail_id]),
            ),
            role=Role.NOTE,
        ),
    )


def _anchor(reading: IndicatorReading, published: PublishedDetail) -> Provenance:
    """Where a statement about *reading* points.

    A reading with a figure points at that figure's row, at the period it was read at. A
    reading without one points at the detail and the period the question **asked** about
    -- which is the lookup that found nothing, and is what ``absent`` documents its
    provenance to be. Such a reference does not resolve against the published layer, by
    construction: that is the content of the element rather than a defect in it.
    """
    if reading.figure is not None:
        return Provenance(
            detail_id=reading.figure.detail_id,
            period=reading.figure.period,
            country=reading.figure.country_id,
            source_id=published.source_id,
        )
    return Provenance(
        detail_id=reading.detail_id,
        period=reading.asked,
        country=None,
        source_id=published.source_id,
    )
