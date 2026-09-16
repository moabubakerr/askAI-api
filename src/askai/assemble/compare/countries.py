"""Countries lined up at one stated period -- and everything that was asked for and empty.

Purity: pure.

Story 4.4, and the row-level half of Story 4.3. ``selection.py`` decided *who* the
answer covers from the configuration; this module composes the answer from what actually
came back, and the two refusals it can reach are the ones only the rows can tell apart.

**One period, and the answer says which** (FR-22). Countries are compared at a common
period, which is an argument here and not something chosen from whichever rows turned
up: an answer assembled from each country's own latest reading would compare 2026 with
2019 and present it as a comparison. ``readings.at_period`` turns any figure that is not
at the stated period into the absence it is, so the comparison cannot quietly straddle
two.

**A country in the bound set with no row is in the answer** (FR-22, AD-7's spirit). It
gets an element of class ``absent`` naming the gap, and is not dropped. Dropping is the
failure this whole epic is shaped around: a shorter list reads exactly like a complete
one, and 268 of 289 details plus one of the 21 declared sets make emptiness the normal
case rather than the exceptional one.

**"Declared but publishes nothing" is its own statement** (FR-11, R-166). ``Total
Population`` declares nine benchmark countries in the published configuration and
publishes all 208 of its datapoints nationally, so the configuration promises a
comparison the data cannot supply. That is a **different** refusal, with a different
message id, from "this indicator declares no benchmark countries" -- the first is a data
gap and the second is a configuration gap, and a QC tester is entitled to tell them
apart from the answer alone.

**The narrowing is stated** (FR-57). When the answer covers fewer countries than the
question implied -- because a named country is not declared, or because a declared one
published nothing -- the answer says so, in its own element, rather than leaving the
reader to count.

An absence carries the provenance of the lookup that found nothing, which is what
``assemble.elements.absent`` is for. Note that such a reference does **not** resolve
against the published layer, because the row it names is the row that does not exist:
these elements are composed here and the admission decision belongs to the layer that
packages them, which is not this one.
"""

from __future__ import annotations

from askai.assemble.compare.composed import Composed
from askai.assemble.compare.readings import CountryReading, at_period, with_figures
from askai.assemble.compare.selection import (
    NotComparable,
    Selection,
    SelectionRefusal,
)
from askai.assemble.elements import absent, derived, measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Placement, Role
from askai.domain.period import Period
from askai.execute.value import Figure
from askai.messages import Catalogue, Lang, compose_counted, render, render_period
from askai.ports.presentation import PublishedDetail
from askai.rules.countries import Country, HomeCountry

__all__ = [
    "CompareMessage",
    "compare_countries",
    "country_line",
    "refusal_statement",
]


class CompareMessage:
    """The message ids this package renders. Ids, not wording -- the wording is data.

    A plain class of constants rather than a ``StrEnum``, following
    ``narrate.structured.AnswerMessage``: these are looked up by value only and nothing
    compares two of them, so an enum would invite someone to.
    """

    COUNTRIES_HEADLINE = "compare.countries_headline"
    COUNTRY_VALUE = "compare.country_value"
    COUNTRY_ABSENT = "compare.country_absent"
    NARROWED = "sentence.compare_narrowed"

    NO_DECLARED_BENCHMARKS = "compare.no_declared_benchmarks"
    NAMED_NOT_DECLARED = "compare.named_not_declared"
    DECLARED_BUT_NO_ROWS = "compare.declared_but_no_rows"
    NO_COUNTRY_ROWS_AT_ALL = "compare.no_country_rows_at_all"

    NATIONAL = "scope.national"
    LIST_SEPARATOR = "scope.list_separator"

    COUNTED_COUNTRY = "count.country"


def compare_countries(
    published: PublishedDetail,
    selection: Selection,
    readings: tuple[CountryReading, ...],
    period: Period,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
) -> Composed:
    """Line the selection's countries up at *period*, naming every gap.

    *readings* is what came back for the selection -- both halves of the union, the
    national one included. It is bound to *period* before anything is composed, so a
    figure from another period cannot reach the comparison as though it belonged to it.
    """
    bound = at_period(readings, period)
    if not with_figures(bound):
        # Declared, fetched, and empty. The configuration promised a comparison the data
        # cannot supply, which is a data gap and says so in its own words.
        return Composed(
            reason=render(
                catalogue,
                lang,
                CompareMessage.NO_COUNTRY_ROWS_AT_ALL,
                detail=published.name,
                period=render_period(catalogue, lang, period),
            )
        )

    lines = [
        country_line(reading, published, period, catalogue, formatter, placement, lang)
        for reading in bound
    ]
    headline = _headline(published, period, catalogue, lang, bound)
    narrowing = _narrowing(selection, bound, published, catalogue, lang)
    return Composed(elements=(headline, *lines, *narrowing))


def country_line(
    reading: CountryReading,
    published: PublishedDetail,
    period: Period,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    lang: Lang,
) -> Placed:
    """One country's row in the comparison -- its figure, or the gap where one is not.

    Both branches produce an element and neither produces ``None``. That is the whole
    reason this is one function: a caller cannot compose the published half and forget
    the empty half, because there is one call and it always returns something to show.
    """
    role = Role.SERIES
    name = _country_words(reading, catalogue, lang)
    if reading.figure is None:
        return Placed(
            element=absent(
                render(
                    catalogue,
                    lang,
                    CompareMessage.COUNTRY_ABSENT,
                    country=name,
                    period=render_period(catalogue, lang, period),
                ),
                _absent_provenance(reading, published, period),
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
                CompareMessage.COUNTRY_VALUE,
                country=name,
                value=written.value,
                unit=written.unit,
            ),
            _found_provenance(reading.figure, published),
        ),
        role=role,
    )


def refusal_statement(
    refusal: NotComparable, published: PublishedDetail, catalogue: Catalogue, lang: Lang
) -> str:
    """What the reader is told when the configuration cannot support a comparison.

    Exhaustive over the closed ``SelectionRefusal``. The two members reach a reader as
    two different sentences, which is the whole of Story 4.3's first half: a country that
    was never declared and an indicator that declares nobody are different facts, and an
    engine that says one of them for both will say the wrong one on whichever is commoner
    -- which here is the indicator, by 268 to 21.
    """
    match refusal.refusal:
        case SelectionRefusal.NO_DECLARED_SET:
            return render(
                catalogue,
                lang,
                CompareMessage.NO_DECLARED_BENCHMARKS,
                detail=published.name,
            )
        case SelectionRefusal.NO_NAMED_COUNTRY_IS_DECLARED:
            return compose_counted(
                catalogue,
                lang,
                CompareMessage.NAMED_NOT_DECLARED,
                CompareMessage.COUNTED_COUNTRY,
                len(refusal.named),
                detail=published.name,
                countries=_listed(refusal.named, catalogue, lang),
            )
        case _:
            raise ValueError(
                f"{refusal.refusal!r} is not a selection refusal this composition can "
                "state; a refusal the engine can reach is one it has to be able to say"
            )


# ------------------------------------------------------------------ the pieces


def _headline(
    published: PublishedDetail,
    period: Period,
    catalogue: Catalogue,
    lang: Lang,
    bound: tuple[CountryReading, ...],
) -> Placed:
    """*"Inflation, compared across countries at Q1 2026."*

    Class ``derived``: the statement is computed from the bound spec and the period the
    figures were read at, with both stated in it. It carries the provenance of the first
    published reading, so the headline of a comparison cannot outlive every figure in it.
    It carries no figure of its own, which is why no ``FormatMode`` is asked for here.
    """
    anchor = with_figures(bound)[0]
    assert anchor.figure is not None
    return Placed(
        element=derived(
            render(
                catalogue,
                lang,
                CompareMessage.COUNTRIES_HEADLINE,
                detail=published.name,
                period=render_period(catalogue, lang, period),
            ),
            _found_provenance(anchor.figure, published),
        ),
        role=Role.SCOPE,
    )


def _narrowing(
    selection: Selection,
    bound: tuple[CountryReading, ...],
    published: PublishedDetail,
    catalogue: Catalogue,
    lang: Lang,
) -> tuple[Placed, ...]:
    """FR-57: when the answer covers less than the question implied, it says so.

    Two ways to cover less, and each gets its own sentence rather than one vague one: a
    country the reader named that the detail does not declare (a configuration gap), and
    a declared country that published nothing at the stated period (a data gap). Both are
    notes rather than series, because a caveat is what they are.
    """
    notes: list[Placed] = []
    anchor = with_figures(bound)[0]
    assert anchor.figure is not None
    provenance = _found_provenance(anchor.figure, published)

    if selection.not_declared:
        notes.append(
            Placed(
                element=derived(
                    compose_counted(
                        catalogue,
                        lang,
                        CompareMessage.NAMED_NOT_DECLARED,
                        CompareMessage.COUNTED_COUNTRY,
                        len(selection.not_declared),
                        detail=published.name,
                        countries=_listed(selection.not_declared, catalogue, lang),
                    ),
                    provenance,
                ),
                role=Role.NOTE,
            )
        )

    empty = tuple(reading for reading in bound if not reading.published)
    if empty:
        notes.append(
            Placed(
                element=derived(
                    compose_counted(
                        catalogue,
                        lang,
                        CompareMessage.DECLARED_BUT_NO_ROWS,
                        CompareMessage.COUNTED_COUNTRY,
                        len(empty),
                        detail=published.name,
                        countries=_listed(
                            tuple(
                                _country_words(reading, catalogue, lang) for reading in empty
                            ),
                            catalogue,
                            lang,
                        ),
                    ),
                    provenance,
                ),
                role=Role.NOTE,
            )
        )

    if notes:
        notes.append(
            Placed(
                element=derived(
                    compose_counted(
                        catalogue,
                        lang,
                        CompareMessage.NARROWED,
                        CompareMessage.COUNTED_COUNTRY,
                        len(with_figures(bound)),
                    ),
                    provenance,
                ),
                role=Role.NOTE,
            )
        )
    return tuple(notes)


def _country_words(reading: CountryReading, catalogue: Catalogue, lang: Lang) -> str:
    """What to call this member of the union in the reader's language.

    The home country is called by the catalogue's phrase for national scope, in both
    languages, because it has no name here to call it by -- ``HomeCountry`` carries no
    code and ``CountryReading`` gives it no name. That is AD-5 reaching the sentence a
    reader actually sees.
    """
    match reading.identity:
        case HomeCountry():
            return render(catalogue, lang, CompareMessage.NATIONAL)
        case Country():
            # Refused at construction when it is missing, so this is a name and not a
            # fallback; the assertion tells the type checker rather than checking again.
            assert reading.name is not None
            return reading.name


def _listed(names: tuple[str, ...], catalogue: Catalogue, lang: Lang) -> str:
    """*names*, joined the way the language joins a list.

    The separator is a message id and not a comma written here: which mark separates a
    list, and whether a space follows it, is a per-language editorial decision, and the
    English one reaching an Arabic sentence is exactly the drift the two files exist to
    prevent.
    """
    return render(catalogue, lang, CompareMessage.LIST_SEPARATOR).join(names)


def _found_provenance(figure: Figure, published: PublishedDetail) -> Provenance:
    """Where this figure came from, derived from the row rather than supplied beside it."""
    return Provenance(
        detail_id=figure.detail_id,
        period=figure.period,
        country=figure.country_id,
        source_id=published.source_id,
    )


def _absent_provenance(
    reading: CountryReading, published: PublishedDetail, period: Period
) -> Provenance:
    """The key that was looked up and found nothing, which is an absence's whole content.

    The country segment carries the ISO code this layer knows the country by. It is a
    description of the lookup and not a join key: the reference names a row that does not
    exist, so it is the one kind of reference that resolving against the published layer
    must answer *no* to, and saying which key was asked for is the point of showing it.
    """
    match reading.identity:
        case HomeCountry():
            country = None
        case Country(code=code):
            country = code
    return Provenance(
        detail_id=published.detail_id,
        period=period,
        country=country,
        source_id=published.source_id,
    )
