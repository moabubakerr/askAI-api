"""What came back for each member of a selection -- including the ones that came back empty.

Purity: pure.

A comparison is composed from a list of *outcomes*, not from a list of figures. That is
the whole content of this module, and it is the difference between an answer a Council
member can act on and one they cannot: a country in the bound set with no row at the
common period **appears in the answer, with an element of class ``absent`` naming the
gap**. It is not dropped. A list that silently shortens reads exactly like a complete
one, and the reader has no way to tell that the country they cared about was fetched and
found empty rather than never asked about.

So ``CountryReading`` carries an identity always and a figure sometimes, and the two
composers downstream branch on which. The absent branch is not an error path; on the one
detail among the 21 declared sets that publishes zero country rows, it is every branch.

**The home country is carried as an identity with no name.** ``HomeCountry`` has no code
and this type gives it no ``name``, so the phrase a reader sees for it comes from
``scope.national`` in the bilingual catalogue -- the same phrase the scope element uses,
and the only place either language says it. A ``name`` on the home country's reading
would be a country name in the engine, which is the literal the whole tree is scanned
for.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.domain.period import Period
from askai.execute.value import Figure
from askai.rules.countries import Country, CountryIdentity, HomeCountry

__all__ = ["CountryReading", "IndicatorReading", "at_period", "with_figures"]


@dataclass(frozen=True, slots=True)
class CountryReading:
    """One member of a country selection, and what the fetch found for it.

    ``figure`` is ``None`` when the country was in the bound set and published no row at
    the period asked for. That is a stated absence, and the composer says so; it is not
    a reason to leave the country out.
    """

    identity: CountryIdentity

    figure: Figure | None = None

    name: str | None = None
    """The country's published name in the reader's language. ``None`` for the home
    country, whose phrase is ``scope.national`` and is not a name."""

    def __post_init__(self) -> None:
        match self.identity:
            case HomeCountry():
                if self.name is not None:
                    raise ValueError(
                        "the national selection carries no country name; national scope "
                        "is the absence of a country, and the answer says so through the "
                        "catalogue's own phrase for it (AD-5)"
                    )
                if self.figure is not None and not self.figure.is_national:
                    raise ValueError(
                        "the national reading carries a figure fetched for a country; "
                        "the national series is the rows with no country value at all"
                    )
            case Country(code=code):
                if not (self.name or "").strip():
                    raise ValueError(
                        f"the reading for `{code}` has no published name; a comparison "
                        "names the countries it lined up, and a code is not reader-facing"
                    )
                if self.figure is not None and self.figure.is_national:
                    raise ValueError(
                        f"the reading for `{code}` carries the national figure; a country "
                        "row and the national series are different rows"
                    )

    @property
    def is_national(self) -> bool:
        """Whether this is the national half of the union rather than a benchmark."""
        return isinstance(self.identity, HomeCountry)

    @property
    def published(self) -> bool:
        return self.figure is not None


@dataclass(frozen=True, slots=True)
class IndicatorReading:
    """One indicator in a cross-indicator comparison, at **its own** period.

    The period a figure is *presented* at is read off the figure and never taken from
    anywhere else, which is FR-24's "no false alignment is forced" made unrepresentable
    rather than remembered: several indicators whose latest readings differ are shown at
    their own periods because ``period`` below has nowhere else to read one from.

    ``asked`` is the other period, and it is deliberately a different field with a
    different job. It is what this part of the question bound, it is used only to source
    and word an *absence* -- there is no figure to read a period off when there is no
    figure -- and it never reaches a sentence that carries a value.
    """

    detail_id: str
    name: str
    asked: Period
    """The period this part of the question bound. Used to source a *absence* -- the
    lookup that found nothing -- and never to present a figure: a figure is shown at the
    period it was read at, which is read off the figure below. Holding the asked period
    and the read period in one place is what makes "no false alignment" checkable, since
    a reader can see the two disagree where an element assembled from one field never
    could."""

    figure: Figure | None = None

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise ValueError("an indicator reading names the detail it is a reading of")
        if not self.name.strip():
            raise ValueError(
                f"the reading for `{self.detail_id}` has no published name; a comparison "
                "names the indicators it lined up"
            )
        if self.figure is not None and self.figure.detail_id != self.detail_id:
            raise ValueError(
                f"the reading for `{self.detail_id}` carries a figure from "
                f"`{self.figure.detail_id}`; a reading and its figure are one row"
            )

    @property
    def period(self) -> Period | None:
        """The period this indicator's own figure was read at, or ``None`` if there is none."""
        return None if self.figure is None else self.figure.period


def with_figures(readings: tuple[CountryReading, ...]) -> tuple[CountryReading, ...]:
    """The readings that published something, in the order they were given.

    Named rather than written inline at each call site, because the *other* half is the
    one the answer must not lose: every caller of this is a step that computes over
    figures, and each of them is followed by a step that says what happened to the rest.
    """
    return tuple(reading for reading in readings if reading.published)


def at_period(readings: tuple[CountryReading, ...], period: Period) -> tuple[CountryReading, ...]:
    """*readings*, with any figure that is not at *period* turned into a stated absence.

    The guard behind FR-22. Countries are compared at a **common** period, and a reading
    whose figure came from a different one is not evidence about the period being stated
    -- so it becomes the absence it is, keeping the country in the answer, rather than
    being shown beside figures it does not belong with.
    """
    return tuple(
        reading
        if reading.figure is not None and reading.figure.period == period
        else CountryReading(identity=reading.identity, name=reading.name)
        for reading in readings
    )
