"""*"What periods exist for this?"* -- stated per grain, and never merged into one list.

Purity: pure.

FR-4, and the reason it is its own acceptance criterion: **90 of the 289 published details
publish at more than one grain**. A detail publishing monthly through 2025 and yearly back
to 2010 has two calendars, and merging them produces a single span -- *"2010 to 2025"* --
that is true of neither. A reader planning a query against it asks for a month in 2012 and
gets nothing, having been told the data was there.

So the calendar is grouped by grain, each span stated with the grain it belongs to, and
the grain is read off the period rather than carried beside it: a ``Period`` owns its
grain, so there is no signature here taking both and therefore no way to state a grain the
periods do not have.

**The 28 details that publish nothing get their own sentence.** *"Published but carries no
data points"* and *"no such detail"* are different answers, and the first is the one 28 of
289 details deserve. Returning the empty calendar for both would tell those readers their
indicator does not exist -- the findings 23/128/150 failure, arriving through an emptiness
check instead of through a caught exception.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from askai.assemble.meta.reference import CatalogueReference, ReferenceKind, catalogue_element
from askai.assemble.roles import Placed, Role
from askai.domain.element import ElementClass
from askai.domain.period import Grain, Period
from askai.messages import Catalogue, CatalogueError, Lang, render, render_period

__all__ = ["PeriodsMessage", "calendars_by_grain", "periods_element"]


class PeriodsMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    STATEMENT = "periods.statement"
    AT_GRAIN = "periods.at_grain"
    AT_GRAIN_SINGLE = "periods.at_grain_single"
    SEPARATOR = "periods.separator"
    NONE_PUBLISHED = "periods.none_published"

    #: The same grain ids ``assemble/scope.py`` renders. The ids are repeated and the
    #: *wording* is not: both modules read the one catalogue entry, so a change to how a
    #: language says "quarterly" reaches both by editing one line of YAML.
    GRAIN_MONTHLY = "grain.monthly"
    GRAIN_QUARTERLY = "grain.quarterly"
    GRAIN_YEARLY = "grain.yearly"


def calendars_by_grain(periods: Iterable[Period]) -> dict[Grain, tuple[Period, ...]]:
    """*periods*, split by the grain each one owns, in calendar order within each grain.

    A plain function over the periods rather than a query, so the split is testable
    without a store and so the read model is never asked to classify a period -- it has no
    grain column to classify one by, which is the point of a period spelling that carries
    its own grain.

    Returned in ``Grain`` declaration order rather than in the order the periods arrived,
    so the same detail states its calendars the same way on every run (AD-17).
    """
    grouped: dict[Grain, list[Period]] = {}
    for period in periods:
        grouped.setdefault(period.grain, []).append(period)
    return {
        grain: tuple(sorted(found, key=lambda period: period.start))
        for grain, found in ((grain, grouped.get(grain, [])) for grain in Grain)
        if found
    }


def periods_element(
    catalogue: Catalogue,
    lang: Lang,
    detail_id: str,
    detail_name: str,
    periods: Sequence[Period],
) -> Placed:
    """What *detail_id* publishes, said per grain -- or that it publishes nothing.

    Role ``evidence``: this is the published calendar shown as published, which is what
    lets a reader check that a figure they were given sits inside it.

    Class turns on the answer, not on the question. A calendar is ``measured`` -- it is
    read off the published rows. *"Published but carries no data points"* is ``absent``,
    which is a class carrying content rather than a missing element: it is the common case
    for 28 of 289 details, and an engine that expresses it by returning nothing produces an
    answer that is silently shorter.
    """
    reference = CatalogueReference(kind=ReferenceKind.DETAIL, key=detail_id)
    calendars = calendars_by_grain(periods)
    if not calendars:
        content = render(catalogue, lang, PeriodsMessage.NONE_PUBLISHED.value, detail=detail_name)
        return Placed(
            element=catalogue_element(content, ElementClass.ABSENT, reference),
            role=Role.EVIDENCE,
        )
    separator = render(catalogue, lang, PeriodsMessage.SEPARATOR.value)
    content = render(
        catalogue,
        lang,
        PeriodsMessage.STATEMENT.value,
        detail=detail_name,
        calendars=separator.join(
            _calendar(catalogue, lang, grain, found) for grain, found in calendars.items()
        ),
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, reference),
        role=Role.EVIDENCE,
    )


def _calendar(catalogue: Catalogue, lang: Lang, grain: Grain, periods: tuple[Period, ...]) -> str:
    """One grain's span -- *"monthly, January 2020 to April 2026"*.

    A grain publishing exactly one period gets its own wording rather than a span whose
    ends are the same period written twice, which reads as a defect even when it is not.
    """
    first, last = periods[0], periods[-1]
    grain_words = _grain_words(catalogue, lang, grain)
    if first == last:
        return render(
            catalogue,
            lang,
            PeriodsMessage.AT_GRAIN_SINGLE.value,
            grain=grain_words,
            period=render_period(catalogue, lang, first),
        )
    return render(
        catalogue,
        lang,
        PeriodsMessage.AT_GRAIN.value,
        grain=grain_words,
        first=render_period(catalogue, lang, first),
        last=render_period(catalogue, lang, last),
    )


def _grain_words(catalogue: Catalogue, lang: Lang, grain: Grain) -> str:
    """*grain*, written as the language writes it.

    Exhaustive on the enum with no fallback, for the reason ``assemble/scope.py`` gives:
    a default here would put one grain's word on another's calendar, and a calendar is
    exactly where that mislabelling would be believed.
    """
    match grain:
        case Grain.MONTHLY:
            message = PeriodsMessage.GRAIN_MONTHLY
        case Grain.QUARTERLY:
            message = PeriodsMessage.GRAIN_QUARTERLY
        case Grain.YEARLY:
            message = PeriodsMessage.GRAIN_YEARLY
        case _:
            raise CatalogueError(
                f"{grain!r} has no word in the catalogue; a grain a detail publishes at "
                "is a grain the calendar has to be able to name"
            )
    return render(catalogue, lang, message.value)
