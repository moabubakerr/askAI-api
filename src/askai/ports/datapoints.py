"""``DatapointsPort`` -- the published rows as ``execute/`` is allowed to see them.

Purity: declaration only.

AD-3: *only ``execute/`` may produce a numeric value, and only by exact key lookup on
``(detail, period, country)``. No similarity search returns a figure. A number that
cannot be traced to a row does not exist.* This port is written so that the first half
is the only shape available and the second half is structural.

There is exactly one method that can return a published value, ``row``, and it takes the
whole key -- a detail, a period and a country -- with no method anywhere on the port that
returns "the newest", "the nearest" or "the best match". Resolving *which* period is the
latest therefore cannot be done by asking for a value: it is done by reading the series'
calendar (``periods``, which returns no figures at all) and then fetching the candidates
by exact key until one carries a published reading. A fetch that wanted to score rows has
nothing to score with.

**The national marker is the absence of a country, spelled ``None``.** Not a name, not a
code, not a sentinel string: the home country appears in none of the 8,127 published
rows, so a filter naming it would match nothing while looking entirely correct (AD-5).
``None`` cannot be compared to a name by accident, and there is nothing to spell wrongly.

**There is no grain anywhere on this port.** ``Period`` owns its grain, the key does not
contain one, and the read model has no grain column -- so a fetch cannot ask for "the
monthly row for 2025" and get something the data cannot represent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from askai.domain.period import Grain, Period
from askai.domain.spec import Measure

__all__ = ["DatapointRow", "DatapointsPort", "DatapointsUnavailable", "UnpublishedMeasure"]


class DatapointsUnavailable(RuntimeError):
    """The read model could not answer -- the port's own typed failure.

    Declared on the port rather than raised as whatever the driver raises, so the layer
    above catches one named thing instead of a broad ``Exception``: AD-15 permits broad
    handling only at an adapter boundary, and this is how the boundary hands a failure
    across as a value's worth of information rather than as a stack trace.

    A failure, never an absence. "This detail publishes nothing" is a perfectly good
    answer and does not raise; this is the store not working.
    """


class UnpublishedMeasure(LookupError):
    """A measure was asked for that is not a column on a datapoint row.

    ``Measure.CHANGE`` is the one case today: a change value is *selected* from the
    published column matching the grain and the basis (AD-4), which is a different
    selection with its own story. Raised rather than returning ``None``, because
    ``None`` here would read as "this row publishes no change", which is a claim about
    the data rather than about the call.
    """


@dataclass(frozen=True, slots=True)
class DatapointRow:
    """One published row, exactly as the read model holds it.

    The value columns are the published **text**, never a float and never a parsed
    number: a published decimal read back through a float is the rounding defect
    arriving through the storage layer, so the exact digits travel to the one place that
    turns them into a ``Decimal``.
    """

    detail_id: str
    period: Period
    #: ``None`` is the national marker, and the only way to say "national" here.
    country_id: str | None
    #: The published row's own identifier -- what makes a figure traceable (AD-3).
    source_datapoint_id: str
    actual: str | None
    target: str | None
    baseline: str | None

    @property
    def grain(self) -> Grain:
        """Read off the period, which owns it. There is no grain column to disagree."""
        return self.period.grain

    @property
    def is_national(self) -> bool:
        return self.country_id is None

    def cell(self, measure: Measure) -> str | None:
        """The published text for *measure*, or ``None`` when this row publishes none.

        Exhaustive on purpose: a measure added to the closed set later raises here
        rather than silently selecting the actual, which would serve one quantity under
        another quantity's name.
        """
        match measure:
            case Measure.ACTUAL:
                return self.actual
            case Measure.TARGET:
                return self.target
            case Measure.BASELINE:
                return self.baseline
            case Measure.CHANGE:
                raise UnpublishedMeasure(
                    "change is not a measure column on a datapoint: it is selected from "
                    "the published column matching the grain and the basis (AD-4)"
                )


class DatapointsPort(Protocol):
    """The read model as the fetch sees it: a calendar, and one row at a time by key."""

    def publishes(self, detail_id: str) -> bool:
        """Does this detail have any published row at all, at any period or country?

        Asked so that "this detail publishes nothing" -- true of 28 of the 289 published
        details -- is a stated cause rather than an empty result indistinguishable from
        a country that happens to have no rows.
        """
        ...

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        """Every period this detail publishes a row for, in the given country scope.

        The series' calendar and nothing else: no values cross this method, so choosing
        which period is "the latest" never touches a figure. ``country_id`` of ``None``
        selects the national rows -- the ones carrying no country at all.
        """
        ...

    def row(self, detail_id: str, period: Period, country_id: str | None) -> DatapointRow | None:
        """The one row at this exact key, or ``None`` when the key names no row.

        The only method on this port that can return a published value, and it takes the
        complete key. ``None`` means the key is absent from the read model; it never
        means "near miss" or "try the next one", because nothing here looks for one.
        """
        ...
