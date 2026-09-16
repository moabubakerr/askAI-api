"""Answer -> package, with no prose. The composition Epic 1 ships and NFR-8 keeps.

Purity: pure; calls one port -- ``SourceCatalogue``, to admit what it composed.

This is the whole of ``narrate/`` in Epic 1. It takes what the earlier layers produced --
the frozen spec, what the fetch did, and how the published layer spells the detail -- and
returns one ``AnswerPackage``. It writes no sentence of its own: every word comes from
the bilingual catalogue by id, every figure comes through the single ``Formatter``, and
every element is admitted against the loaded published layer before it is allowed into
the package (AD-7).

**No prose, permanently.** Nothing here calls a model; there is no model client on the
answer path and ``tests/test_assemble.py`` scans for the import. Generated prose arrives
in Epic 8 *behind a guard*, and this path stays: NFR-8 makes the structured answer what
the system falls back to whenever the model is unavailable, so it is a supported state
rather than a stage on the way to one.

**Nothing here chooses a mode or a lens.** The composer holds a ``Role`` and asks
``Placement``; AD-18's *"decided once by the element's position"* is true because no
module in this package names a ``FormatMode`` member, which is asserted as a scan.

**Absence, refusal and failure are three answers, not one.** A detail that publishes
nothing, a question that did not say enough, and a read model that would not answer reach
a reader as three different statements with three different message ids -- the findings
23/128/150 failure, closed off at the point the reader-facing wording is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from askai.assemble.elements import measured
from askai.assemble.format import Formatter, PublishedFormat
from askai.assemble.provenance import Admitted, Provenance, Refused, admit
from askai.assemble.roles import Placed, Placement, Role
from askai.assemble.scope import scope_element
from askai.compile.binding import CompiledQuestion, SpecField, UnboundReason
from askai.domain.degradation import Degradation
from askai.domain.scope import CountryScope
from askai.domain.spec import Bound, Unbound
from askai.execute.value import Execution, Figure, FigureCause
from askai.messages import Catalogue, Lang, render, render_period
from askai.narrate.package import AnswerPackage, PackageKind, PackageSource
from askai.observability.degradations import DegradationKind, degrade
from askai.ports.presentation import PublishedDetail
from askai.ports.provenance_source import SourceCatalogue

__all__ = ["Answer", "AnswerMessage", "Where", "external_package", "structured_package"]


class AnswerMessage:
    """The message ids this module renders. Ids, not wording -- the wording is data.

    A plain class of constants rather than a ``StrEnum`` because these are looked up by
    value only; nothing compares two of them, and an enum would invite someone to.
    """

    VALUE = "answer.value"
    VALUE_FOR_COUNTRY = "answer.value_for_country"
    WHICH_INDICATOR = "clarify.which_indicator"
    WHICH_PERIOD = "clarify.which_period"
    NOT_PUBLISHED = "refusal.not_published"
    NOT_SUPPORTED = "refusal.not_supported"
    DATA_UNAVAILABLE = "failure.data_unavailable"
    EXTERNAL_UNAVAILABLE = "failure.external_unavailable"
    EXTERNAL_CAVEAT = "caveat.external"


class Where:
    """The address a degradation raised here carries, so a rising rate can be traced."""

    NARRATE = "narrate.structured"


#: The rules this composition relies on, recorded by id on every package it builds.
#: ``R-ROLE-FORMAT-MODE`` decides the precision of the headline figure and
#: ``R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT`` decides how many decimals that is; both
#: fired for any answer carrying a figure, and the record says so.
_FIGURE_RULES = ("R-ROLE-FORMAT-MODE", "R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT")


@dataclass(frozen=True, slots=True)
class Answer:
    """Everything composing one package depends on, stated rather than reached for.

    ``published`` is ``None`` exactly when no detail was bound, or when the bound detail
    is not in the published layer -- which is a different thing from a detail that
    publishes no rows, and is composed differently below.
    """

    question: CompiledQuestion
    execution: Execution
    lang: Lang
    published: PublishedDetail | None = None
    #: The published name of the country the figure was read in, when the scope named
    #: one. ``None`` for national scope, which is the *absence* of a country (AD-5).
    country_name: str | None = None


def structured_package(
    answer: Answer,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: SourceCatalogue,
) -> AnswerPackage:
    """The approved package for *answer*: elements and no prose, or a stated non-answer."""
    figure = answer.execution.figure
    if figure is None or answer.published is None:
        return _not_an_answer(answer, catalogue)
    return _an_answer(answer, figure, answer.published, catalogue, formatter, placement, sources)


# ---------------------------------------------------------------------- the answer


def _an_answer(
    answer: Answer,
    figure: Figure,
    published: PublishedDetail,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: SourceCatalogue,
) -> AnswerPackage:
    """One figure, said in words, with the statement of what the answer did beside it."""
    provenance = Provenance(
        detail_id=figure.detail_id,
        period=figure.period,
        country=figure.country_id,
        source_id=published.source_id,
    )
    headline = _headline(answer, figure, published, provenance, catalogue, formatter, placement)
    composed = (headline, scope_element(catalogue, answer.lang, provenance, _scope(answer)))

    admitted: list[Placed] = []
    degradations: list[Degradation] = list(answer.execution.degradations)
    for placed in composed:
        match admit(placed.element, sources):
            case Admitted():
                admitted.append(placed)
            case Refused(degradation=degradation):
                degradations.append(degradation)

    if not admitted:
        # Every element was refused, so there is no answer left to give -- and it is a
        # failure of the closed-world check, never "no approved figures for that period".
        return _stated(
            answer,
            PackageKind.REFUSAL,
            render(catalogue, answer.lang, AnswerMessage.DATA_UNAVAILABLE),
            tuple(degradations),
        )
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=PackageKind.ANSWER,
        spec=answer.question.spec,
        bindings=answer.question.bindings,
        resolution=answer.execution.resolution,
        elements=tuple(admitted),
        degradations=tuple(degradations),
        row_ids=tuple(
            reading.figure.source_datapoint_id for reading in answer.execution.readings
        )
        or (figure.source_datapoint_id,),
        rules_fired=_rules_fired(answer),
    )


def _headline(
    answer: Answer,
    figure: Figure,
    published: PublishedDetail,
    provenance: Provenance,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> Placed:
    """The figure the reader reads first, written at the precision its role calls for.

    The mode is asked for by role and never named here (AD-18, FR-48), and the value goes
    through the single ``Formatter`` -- the only route from a published value to a string.
    """
    role = Role.HEADLINE
    written = formatter.format(
        _value(figure),
        PublishedFormat(unit=published.unit, spec=published.value_format),
        placement.mode_for(role),
        answer.lang,
    )
    period = render_period(catalogue, answer.lang, figure.period)
    if answer.country_name is None:
        content = render(
            catalogue,
            answer.lang,
            AnswerMessage.VALUE,
            detail=published.name,
            value=written.value,
            unit=written.unit,
            period=period,
        )
    else:
        content = render(
            catalogue,
            answer.lang,
            AnswerMessage.VALUE_FOR_COUNTRY,
            detail=published.name,
            country=answer.country_name,
            value=written.value,
            unit=written.unit,
            period=period,
        )
    return Placed(element=measured(content, provenance), role=role)


def _value(figure: Figure) -> Decimal:
    """The published digits, as ``execute/`` parsed them.

    A pass-through with a name, so that the one place a figure enters composition is a
    line a reviewer can see -- and so that nothing here is tempted to convert, scale or
    re-parse a value that was already read from its row.
    """
    return figure.value


def _rules_fired(answer: Answer) -> tuple[str, ...]:
    """The rules that took part in this answer, by id.

    The resolution rule is included only when a period was actually deferred, because a
    record naming a rule that did not fire is the confusion AD-15 exists to end.
    """
    fired = list(_FIGURE_RULES)
    resolved_by = answer.execution.resolution.resolved_by
    if resolved_by is not None:
        fired.append(resolved_by)
    return tuple(fired)


def _scope(answer: Answer) -> CountryScope:
    """The country scope the spec bound, which a single row's country cannot report.

    Read off the spec rather than off the figure: whether one country was asked for or
    one of several compared is a fact about the question, and AD-1 gives ``compile/`` the
    last word on it.
    """
    state = answer.question.spec.country_scope
    if isinstance(state, Bound):
        return state.value
    raise ValueError(
        "an answer was composed for a question whose country scope is not bound; the "
        "fetch refuses that state before a figure exists, so reaching here means a "
        "figure arrived without one"
    )


# ------------------------------------------------- refusal, clarification and failure


def _not_an_answer(answer: Answer, catalogue: Catalogue) -> AnswerPackage:
    """What the reader is told when there is no figure -- and which of the three it is."""
    if answer.execution.figure is not None:
        # A figure whose detail is not in the published layer. The row exists and the
        # catalogue does not, which is the store disagreeing with itself: a failure,
        # counted, never rendered as "nothing is published".
        return _stated(
            answer,
            PackageKind.REFUSAL,
            render(catalogue, answer.lang, AnswerMessage.DATA_UNAVAILABLE),
            (
                degrade(
                    DegradationKind.ADAPTER_UNAVAILABLE,
                    Where.NARRATE,
                    "a figure was fetched for a detail the published catalogue does not "
                    "hold, so it cannot be named, formatted or sourced",
                ),
            ),
        )
    kind, statement = _stated_cause(answer, catalogue)
    return _stated(answer, kind, statement, answer.execution.degradations)


def _stated_cause(answer: Answer, catalogue: Catalogue) -> tuple[PackageKind, str]:
    """The kind of non-answer this is, and the sentence that says so.

    Exhaustive over the closed ``FigureCause`` set. A cause with no wording would reach a
    reader as a blank, which is the shape an error used to take.
    """
    lang = answer.lang
    cause = answer.execution.cause
    match cause:
        case FigureCause.DETAIL_NOT_BOUND:
            return _unbound_detail(answer, catalogue)
        case FigureCause.PERIOD_NOT_BOUND:
            return _unbound_period(answer, catalogue)
        case (
            FigureCause.COUNTRY_SCOPE_NOT_BOUND
            | FigureCause.MEASURE_NOT_BOUND
            | FigureCause.OPERATION_NOT_BOUND
            | FigureCause.OPERATION_IS_NOT_A_VALUE
            | FigureCause.SCOPE_IS_NOT_ONE_SERIES
            | FigureCause.CHANGE_IS_A_PUBLISHED_COLUMN
        ):
            return PackageKind.REFUSAL, render(catalogue, lang, AnswerMessage.NOT_SUPPORTED)
        case (
            FigureCause.DETAIL_PUBLISHES_NOTHING
            | FigureCause.SCOPE_PUBLISHES_NOTHING
            | FigureCause.NO_READING_AT_OR_BEFORE_TODAY
            | FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD
            | FigureCause.MEASURE_NOT_PUBLISHED
            | FigureCause.VALUE_IS_NOT_A_FIGURE
        ):
            return PackageKind.REFUSAL, render(catalogue, lang, AnswerMessage.NOT_PUBLISHED)
        case FigureCause.LOOKUP_FAILED:
            # The one cause that is a failure rather than an absence, and it says so in
            # its own words: "the data could not be read" is not "there is no data".
            return PackageKind.REFUSAL, render(catalogue, lang, AnswerMessage.DATA_UNAVAILABLE)
        case None:
            raise ValueError(
                "an execution with no figure and no cause; the two agree by construction, "
                "so reaching here means an Execution was built outside execute/"
            )


def _unbound_detail(answer: Answer, catalogue: Catalogue) -> tuple[PackageKind, str]:
    """A question that named no indicator, or named one two details publish.

    The second is a clarification and not a refusal, and the difference matters: 257 of
    320 published names are shared, so "which of these did you mean" is the commonest
    thing the engine has to say, and saying "that is not published" instead would be
    false on the most frequent question it gets.
    """
    reason, particulars = _unbound(answer, SpecField.DETAIL)
    if reason == UnboundReason.DETAIL_NAME_IS_SHARED.value:
        return PackageKind.CLARIFICATION, render(
            catalogue, answer.lang, AnswerMessage.WHICH_INDICATOR, options=particulars
        )
    return PackageKind.REFUSAL, render(
        catalogue, answer.lang, AnswerMessage.NOT_PUBLISHED
    )


def _unbound_period(answer: Answer, catalogue: Catalogue) -> tuple[PackageKind, str]:
    """A grain the detail does not publish is a refusal; an unclear period is a question.

    FR-6: no adjacent grain is ever substituted, so a reader who asked for a quarter of
    something published only yearly is told the published data cannot answer it as asked
    rather than being handed the year.
    """
    reason, _ = _unbound(answer, SpecField.PERIOD)
    if reason == UnboundReason.GRAIN_NOT_PUBLISHED.value:
        return PackageKind.REFUSAL, render(
            catalogue, answer.lang, AnswerMessage.NOT_SUPPORTED
        )
    return PackageKind.CLARIFICATION, render(
        catalogue, answer.lang, AnswerMessage.WHICH_PERIOD, detail=_detail_name(answer)
    )


def _detail_name(answer: Answer) -> str:
    """What to call the indicator in a clarification: its published name, else its id.

    The id is not reader-facing text and is not pretending to be: it is what the engine
    has when the catalogue could not name the thing, and showing it beats showing a gap
    in a sentence.
    """
    if answer.published is not None:
        return answer.published.name
    state = answer.question.spec.detail
    return state.value if isinstance(state, Bound) else ""


def _unbound(answer: Answer, field: SpecField) -> tuple[str, str]:
    """The code and the particulars an ``Unbound`` field carries.

    ``compile/`` spells an ``UnboundReason`` into the reason with the particulars after
    it, precisely so that a composer can branch on the code without reading English out
    of a sentence -- which is what it would have to do if the reason were free text.
    """
    state = answer.question.state_of(field)
    if not isinstance(state, Unbound):
        return "", ""
    code, _, particulars = state.reason.partition(": ")
    return code, particulars


def _stated(
    answer: Answer,
    kind: PackageKind,
    statement: str,
    degradations: tuple[Degradation, ...],
) -> AnswerPackage:
    """A package that carries no figure, and says why in the reader's own language."""
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=kind,
        spec=answer.question.spec,
        bindings=answer.question.bindings,
        resolution=answer.execution.resolution,
        reason=statement,
        degradations=degradations,
    )


# ---------------------------------------------------------------- the external half


def external_package(
    question: CompiledQuestion, catalogue: Catalogue, lang: Lang
) -> AnswerPackage:
    """The external package this epic can build: the agent is not wired, and it says so.

    AD-15's rule for a missing external source is to *"degrade to the approved answer
    with the gap stated, never to a blended one that hides which half is missing"*. The
    gap is stated as its own package, returned beside the approved one and never merged
    into it, with the unconditional external caveat (FR-84, FR-88) attached -- so a
    client that renders both sees exactly which half it is missing.
    """
    return AnswerPackage(
        source=PackageSource.EXTERNAL,
        kind=PackageKind.REFUSAL,
        spec=question.spec,
        bindings=question.bindings,
        reason=render(catalogue, lang, AnswerMessage.EXTERNAL_UNAVAILABLE),
        caveat=render(catalogue, lang, AnswerMessage.EXTERNAL_CAVEAT),
        degradations=(
            degrade(
                DegradationKind.EXTERNAL_AGENT_UNAVAILABLE,
                Where.NARRATE,
                "no external agent is configured in this build; the gap is stated as its "
                "own package rather than blended into the approved one",
            ),
        ),
    )
