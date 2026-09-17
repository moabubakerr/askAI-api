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
from askai.compile.resolve.decide import Disambiguation
from askai.domain.degradation import Degradation
from askai.domain.scope import CountryScope
from askai.domain.spec import Bound, Operation, Unbound
from askai.execute.value import Execution, Figure, FigureCause
from askai.messages import Catalogue, Lang, render, render_period
from askai.narrate.clarify import (
    ClarifyCode,
    clarification_for,
    clarify_message_id,
    named_options,
)
from askai.narrate.dispatch import (
    Composed,
    NotHeld,
    Request,
    Unwired,
    compose_operation,
)
from askai.narrate.package import AnswerPackage, PackageKind, PackageSource
from askai.narrate.premise import AssertedFigure, contradicts, correction_element
from askai.narrate.refusal import (
    RefusalCode,
    refusal_for,
    refusal_for_unbound,
    refusal_message_id,
    refusal_statement,
)
from askai.narrate.unapproved import CatalogueProbe, improved_refusal
from askai.observability.degradations import DegradationKind, degrade
from askai.ports.groups import GroupsPort
from askai.ports.presentation import PublishedDetail
from askai.ports.provenance_source import SourceCatalogue

__all__ = [
    "Answer",
    "AnswerMessage",
    "Where",
    "declare_agent",
    "external_package",
    "structured_package",
]


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
    AGENT_APPROVED = "agent.approved"
    AGENT_EXTERNAL = "agent.external"
    #: Story 2.9 -- the near miss, named as a suggestion and never as an answer.
    SUGGESTION = "suggestion.not_what_you_asked"
    SENTENCE_SEPARATOR = "refusal.sentence_separator"


@dataclass(frozen=True, slots=True)
class Statement:
    """What a package that carries no figure says, and the two names it says it under.

    Three values travelling together rather than a bare string, because Story 2.7 asks
    for both halves at once: the **code** is stable across an editorial change and is
    what a refusal is counted by, and the **message id** is what a reviewer opens the
    catalogue at. A sentence alone could be counted only by its own text, which is a
    count of typos the moment a wording is fixed.

    ``code`` is ``None`` exactly when this is a clarification. A clarification is not one
    of FR-38's six refusals -- it says the reader has not yet said enough, which is a
    different statement about the world -- and giving it a refusal code would put it in
    the refusal tally and make an engine that asks well look like an engine that fails.
    """

    kind: PackageKind
    message_id: str
    text: str
    code: RefusalCode | None = None

    #: Anything that went wrong *choosing* this statement -- today, an unapproved
    #: catalogue that could not be read (Story 2.8). Carried on the statement rather
    #: than returned beside it so that a branch cannot compose the sentence and drop the
    #: reason it is the weaker one; ``_stated`` splices these into the package.
    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        if (self.kind is PackageKind.REFUSAL) is not (self.code is not None):
            raise ValueError(
                f"a {self.kind.value} carrying code {self.code}; a refusal names one of "
                "the six causes and a clarification names none"
            )


def refused(code: RefusalCode, catalogue: Catalogue, lang: Lang) -> Statement:
    """The refusal for *code*, worded from the catalogue in the reader's language."""
    return Statement(
        kind=PackageKind.REFUSAL,
        message_id=refusal_message_id(code),
        text=refusal_statement(catalogue, lang, code),
        code=code,
    )


class Where:
    """The address a degradation raised here carries, so a rising rate can be traced."""

    NARRATE = "narrate.structured"


def declare_agent(catalogue: Catalogue, lang: Lang, source: PackageSource) -> str:
    """The reader-facing declaration of which agent produced a package (FR-83).

    Rendered here, from the bilingual catalogue, at the moment the package is built --
    the same route every other sentence in an answer takes. Nothing downstream of this
    chooses the wording, translates it or decides whether to show it, which is what makes
    *"in both languages and in both lenses"* a property of the value rather than a
    requirement on every client that renders one.

    Exhaustive over the closed ``PackageSource`` rather than a lookup with a fallback: a
    source added to the enum without a declaration fails to type-check here, where a
    ``.get`` would have shipped a package declaring nothing at all.
    """
    match source:
        case PackageSource.APPROVED:
            message = AnswerMessage.AGENT_APPROVED
        case PackageSource.EXTERNAL:
            message = AnswerMessage.AGENT_EXTERNAL
    return render(catalogue, lang, message)


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

    #: A figure the question itself asserts, where the question asserted one (FR-41).
    #: ``None`` is *"the reader asserted nothing"* and is not the same as asserting a
    #: figure that happens to agree -- the second is a correction that was not needed and
    #: the first is a question with no premise in it at all.
    premise: AssertedFigure | None = None

    #: The published name of an indicator the resolution considered and did **not** bind,
    #: where there is one worth naming (FR-39, Story 2.9). Named as a suggestion in its
    #: own sentence, clearly marked as not what was asked; never used to answer, and
    #: never turned into a figure -- a figure exists only where a row does (AD-3).
    suggestion: str | None = None

    #: Story 2.8, FR-38a. One question over the base CMS layer -- *"does the unapproved
    #: catalogue hold what this reader named?"* -- taking the reader's words and
    #: answering yes, no, or *it could not be read*. ``None`` in a deployment wired
    #: without the base layer, which answers exactly as it did before.
    #:
    #: A callable and not the port, deliberately: **this field is the whole of the
    #: crossing**, and a boolean is the only thing that can travel along it. Nothing on
    #: this type, and nothing on the package built from it, can carry a value, a period,
    #: a definition or a name from an unapproved row, because no such type is reachable
    #: from here (R-UNAPPROVED-LEAKS-NOTHING).
    unapproved: CatalogueProbe | None = None

    #: The words the reader used for the indicator, where something upstream knows them
    #: more precisely than the question does. ``None`` falls back to the particulars
    #: ``compile/`` recorded on the unbound detail, which for a question that named
    #: nothing resolvable is the question itself -- and which is what the probe is built
    #: to read (``adapters.readmodel.unpublished.existence_probe``).
    named_indicator: str | None = None


def structured_package(
    answer: Answer,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: SourceCatalogue,
    groups: GroupsPort | None = None,
) -> AnswerPackage:
    """The approved package for *answer*: elements and no prose, or a stated non-answer.

    **The operation decides which composer answers**, and until this branch existed
    nothing read the field: every question, whatever its verb, reached the value
    composition below. A question that bound an operation other than ``value`` is routed
    by ``narrate.dispatch``; everything else is the path Epic 1 shipped, unchanged, down
    to the order of its two checks.

    *groups* is optional because it is a port a process either was wired with or was not,
    and a process without one still answers every value question exactly as before. An
    operation that needs it and does not have it is refused *as unsupported*, which is
    what it is -- never as "nothing is published", which would be false.
    """
    routed = _routed(answer, catalogue, placement, sources, groups)
    if routed is not None:
        return routed
    figure = answer.execution.figure
    if figure is None or answer.published is None:
        return _not_an_answer(answer, catalogue)
    return _an_answer(answer, figure, answer.published, catalogue, formatter, placement, sources)


# ---------------------------------------------------------------- the other operations


def _routed(
    answer: Answer,
    catalogue: Catalogue,
    placement: Placement,
    sources: SourceCatalogue,
    groups: GroupsPort | None,
) -> AnswerPackage | None:
    """The package for a non-value operation, or ``None`` when this is the value path.

    ``None`` for an ``Unbound`` operation as well as for ``value``: an unbound field is
    ``compile/``'s statement that the reader was not specific enough, ``execute/`` already
    turns it into ``OPERATION_NOT_BOUND``, and routing on a field that was never bound
    would be this layer reinterpreting one (AD-1).

    ``None`` also for a question that is not answerable at all, whatever its operation,
    and that ordering is load-bearing. *"What is <a name two details publish>?"* binds
    ``definition`` and binds no detail, and it is a **clarification** -- "which of these
    did you mean" -- not "this engine cannot answer definitions". 257 of 320 published
    names are shared, so the wrong branch here would be the commonest answer the engine
    gives. An unbound field is the reader's question to finish; the operation only decides
    which composer answers one that is finished.
    """
    if not answer.question.is_answerable:
        return None
    state = answer.question.spec.operation
    if not isinstance(state, Bound) or state.value is Operation.VALUE:
        return None
    match compose_operation(
        Request(
            operation=state.value,
            lang=answer.lang,
            catalogue=catalogue,
            # The rule set the answer is being composed under, taken from the collaborator
            # that was handed it. Asking `rules()` here would read a second rule set, and
            # two rule sets in one answer is the drift `Placement` takes one to prevent.
            rule_set=placement.rule_set,
            detail_id=_detail_id(answer),
            detail_name=_detail_name(answer),
            groups=groups,
        )
    ):
        case Composed(elements=elements, rules_fired=fired):
            return _element_answer(answer, elements, fired, catalogue, sources)
        case NotHeld():
            # The published layer holds no such detail at all, which is cause one and
            # not cause five: the engine could have answered the question, and there is
            # nothing to answer it about.
            return _stated(
                answer,
                catalogue,
                _refusal_with_particulars(answer, catalogue, RefusalCode.NO_SUCH_INDICATOR),
                answer.execution.degradations,
            )
        case Unwired():
            return _stated(
                answer,
                catalogue,
                refused(RefusalCode.QUESTION_NOT_SUPPORTED, catalogue, answer.lang),
                answer.execution.degradations,
            )


def _element_answer(
    answer: Answer,
    elements: tuple[Placed, ...],
    rules_fired: tuple[str, ...],
    catalogue: Catalogue,
    sources: SourceCatalogue,
) -> AnswerPackage:
    """Admit what a composer built, and refuse what does not resolve (AD-7).

    The same admission the value path runs, over elements that carry a *catalogue*
    reference rather than a datapoint one. It is the same step deliberately: a definition
    quoted from a detail the last refresh removed is exactly as unsourced as a figure from
    a retired row, and it is refused with a typed degradation rather than shown.
    """
    admitted: list[Placed] = []
    degradations: list[Degradation] = list(answer.execution.degradations)
    for placed in elements:
        match admit(placed.element, sources):
            case Admitted():
                admitted.append(placed)
            case Refused(degradation=degradation):
                degradations.append(degradation)
    if not admitted:
        # Every element was refused against the loaded published layer, so what this is
        # is a closed-world check that failed -- cause six, and never "nothing is
        # published", which would be a statement about the data rather than about here.
        return _stated(
            answer,
            catalogue,
            refused(RefusalCode.DATA_COULD_NOT_BE_REACHED, catalogue, answer.lang),
            tuple(degradations),
        )
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=PackageKind.ANSWER,
        agent=declare_agent(catalogue, answer.lang, PackageSource.APPROVED),
        spec=answer.question.spec,
        bindings=answer.question.bindings,
        resolution=answer.execution.resolution,
        elements=tuple(admitted),
        degradations=tuple(degradations),
        rules_fired=rules_fired,
    )


def _detail_id(answer: Answer) -> str | None:
    """The bound detail, or ``None``. Never repaired and never guessed at (AD-1)."""
    state = answer.question.spec.detail
    return state.value if isinstance(state, Bound) else None


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
    # FR-58: the correction leads, because it answers the question that was actually
    # asked. It is prepended to the tuple rather than sorted into it later, so "first" is
    # a property of what this function builds and not of what a client does with it.
    composed = (
        *_premise_correction(
            answer, figure, published, provenance, catalogue, formatter, placement
        ),
        headline,
        scope_element(catalogue, answer.lang, provenance, _scope(answer)),
    )

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
            catalogue,
            refused(RefusalCode.DATA_COULD_NOT_BE_REACHED, catalogue, answer.lang),
            tuple(degradations),
        )
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=PackageKind.ANSWER,
        agent=declare_agent(catalogue, answer.lang, PackageSource.APPROVED),
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


def _premise_correction(
    answer: Answer,
    figure: Figure,
    published: PublishedDetail,
    provenance: Provenance,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> tuple[Placed, ...]:
    """The correction, where the question asserted a figure the data contradicts (FR-41).

    An empty tuple where the question asserted nothing, and an empty tuple where it
    asserted the published figure -- a premise the data *supports* needs no correction,
    and manufacturing one would train a reader to ignore them.

    Returned as a tuple so the caller splices it, which is what keeps the correction's
    position a fact about composition. It is admitted against the published layer with
    every other element (AD-7): a correction sourced to a row the last refresh retired is
    exactly as unsourced as the headline would be, and is refused the same way.
    """
    premise = answer.premise
    if premise is None or not contradicts(premise, figure.value):
        return ()
    return (
        correction_element(
            catalogue,
            answer.lang,
            formatter,
            placement,
            provenance,
            published,
            figure.value,
            render_period(catalogue, answer.lang, figure.period),
        ),
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
            catalogue,
            refused(RefusalCode.DATA_COULD_NOT_BE_REACHED, catalogue, answer.lang),
            (
                degrade(
                    DegradationKind.ADAPTER_UNAVAILABLE,
                    Where.NARRATE,
                    "a figure was fetched for a detail the published catalogue does not "
                    "hold, so it cannot be named, formatted or sourced",
                ),
            ),
        )
    return _stated(
        answer, catalogue, _stated_cause(answer, catalogue), answer.execution.degradations
    )


def _stated_cause(answer: Answer, catalogue: Catalogue) -> Statement:
    """Which non-answer this is: one closed question, or one of FR-38's six refusals.

    **Total over the closed ``FigureCause`` set, and total onto the six.** Every branch
    ends in ``refusal_for`` or ``refusal_for_unbound``, both of which are table lookups
    over a closed set checked complete at import -- so there is no cause that reaches a
    reader as a blank, and no two causes that reach one as the same sentence. That is the
    whole of Story 2.7 at the one point where the wording is chosen.

    **A clarification is tried first** and is not one of the six. An unbound field is the
    reader's question to finish, and *"which of these did you mean"* is the commonest
    thing this engine has to say: 257 of 320 published names are shared, so answering
    those with a refusal would be false on the most frequent question it gets.
    """
    cause = answer.execution.cause
    match cause:
        case FigureCause.DETAIL_NOT_BOUND:
            return _unbound_field(answer, catalogue, SpecField.DETAIL, cause)
        case FigureCause.PERIOD_NOT_BOUND:
            return _unbound_field(answer, catalogue, SpecField.PERIOD, cause)
        case None:
            raise ValueError(
                "an execution with no figure and no cause; the two agree by construction, "
                "so reaching here means an Execution was built outside execute/"
            )
        case _:
            return _refusal_with_particulars(answer, catalogue, refusal_for(cause))


def _unbound_field(
    answer: Answer, catalogue: Catalogue, field: SpecField, cause: FigureCause
) -> Statement:
    """An unbound field: the closed question it can be put as, else its refusal.

    ``compile/`` spells an ``UnboundReason`` into the reason, so the branch here is on a
    code rather than on English read back out of a sentence. A reason this build does not
    recognise falls back to the ``FigureCause`` mapping rather than raising: an engine
    compiled against a newer ``compile/`` should refuse honestly, not fail to answer.
    """
    reason, particulars = _unbound(answer, field)
    if reason not in set(UnboundReason):
        return _refusal_with_particulars(answer, catalogue, refusal_for(cause))
    code = UnboundReason(reason)
    asked = clarification_for(code)
    if asked is not None:
        return _asked(answer, catalogue, asked, particulars)
    return _refusal_with_particulars(answer, catalogue, refusal_for_unbound(code))


def _asked(
    answer: Answer, catalogue: Catalogue, code: ClarifyCode, particulars: str
) -> Statement:
    """One closed question, naming the candidates or the missing dimension (FR-92).

    The candidates come from the resolution where the ladder ran and named them, and from
    the ``Unbound`` particulars where an exact shared name was the cause. Either way the
    question names them: there is no branch here that asks the reader to rephrase, and
    ``tests/test_refusals.py`` asserts no message in either language could.
    """
    message_id = clarify_message_id(code)
    match code:
        case ClarifyCode.WHICH_INDICATOR:
            text = render(
                catalogue,
                answer.lang,
                message_id,
                options=_candidates(answer, catalogue, particulars),
            )
        case ClarifyCode.WHICH_PERIOD:
            text = render(
                catalogue, answer.lang, message_id, detail=_detail_name(answer)
            )
    return Statement(kind=PackageKind.CLARIFICATION, message_id=message_id, text=text)


def _candidates(answer: Answer, catalogue: Catalogue, particulars: str) -> str:
    """The indicators a closed question offers, joined in the reader's own language.

    AD-25's resolution carries the published surface that actually matched, which is the
    spelling to offer the reader; it is preferred over the ``Unbound`` particulars for
    exactly that reason. The particulars are the fallback for the rung that needs no
    ladder -- an exactly typed name two details publish.
    """
    resolution = answer.question.resolution
    if isinstance(resolution, Disambiguation) and resolution.candidates:
        return named_options(
            catalogue,
            answer.lang,
            [offered.surface for offered in resolution.candidates],
        )
    return particulars


def _refusal_with_particulars(
    answer: Answer, catalogue: Catalogue, code: RefusalCode
) -> Statement:
    """One of the six, with the detail's name where the sentence names one.

    Two of the six speak *about* an indicator -- it is published and empty, or it
    publishes nothing here -- so they take its name; the other four speak about the
    question or about the engine and take no parameter. The split is read off the
    catalogue's own parameter set rather than restated here, so adding a parameter to a
    refusal is an edit to the message and to nothing else.

    **The unapproved catalogue is asked here, and nowhere else** (Story 2.8). It is the
    one point at which *"I hold nothing matching that"* is about to be said, so it is the
    one point at which the base layer can contradict it -- and asking once means the
    improvement cannot be applied on one branch and forgotten on another. What comes back
    is a code and any degradation collected on the way; the *name* the reader is refused
    about is still ``_detail_name``, off the published layer, and never the unapproved
    spelling that matched.
    """
    verdict = improved_refusal(code, _named_indicator(answer), answer.unapproved)
    code = verdict.code
    message_id = refusal_message_id(code)
    parameters = catalogue.parameters(message_id)
    text = render(
        catalogue,
        answer.lang,
        message_id,
        **({"detail": _detail_name(answer)} if "detail" in parameters else {}),
    )
    return Statement(
        kind=PackageKind.REFUSAL,
        message_id=message_id,
        text=_with_suggestion(answer, catalogue, code, text),
        code=code,
        degradations=verdict.degradations,
    )


def _named_indicator(answer: Answer) -> str:
    """The reader's own words for the indicator, as the unapproved catalogue is asked.

    The explicit field where something upstream set one, and otherwise the particulars
    ``compile/`` recorded on the unbound detail -- which for a question naming nothing
    resolvable is the question's own words. Either is the reader's text and neither is a
    published name, which is what makes the probe's answer *"the reader named something
    the CMS holds"* rather than *"the engine found a near neighbour"*.
    """
    if answer.named_indicator is not None:
        return answer.named_indicator
    _, particulars = _unbound(answer, SpecField.DETAIL)
    return particulars


def _with_suggestion(
    answer: Answer, catalogue: Catalogue, code: RefusalCode, text: str
) -> str:
    """FR-39: the near miss may be *named*, in its own sentence, and never answered with.

    Only on ``NO_SUCH_INDICATOR``, because that is the only cause for which a similar
    indicator is a useful thing to hear about -- offering one beside *"the data could not
    be read"* would suggest the engine is proposing a workaround for its own outage.

    The suggestion is appended as a second sentence with its own message id rather than
    folded into the refusal's wording. That is what lets a reviewer read the two side by
    side and confirm the second cannot be mistaken for an answer, and it keeps the
    refusal's own sentence identical whether or not a near miss was found.
    """
    if code is not RefusalCode.NO_SUCH_INDICATOR or not answer.suggestion:
        return text
    separator = render(catalogue, answer.lang, AnswerMessage.SENTENCE_SEPARATOR)
    named = render(
        catalogue, answer.lang, AnswerMessage.SUGGESTION, suggestion=answer.suggestion
    )
    return f"{text}{separator}{named}"


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
    catalogue: Catalogue,
    statement: Statement,
    degradations: tuple[Degradation, ...],
) -> AnswerPackage:
    """A package that carries no figure, and says why in the reader's own language.

    The sentence, the id it was worded from and the machine code all come off one
    ``Statement``, so a package cannot carry a refusal counted as one cause and worded as
    another (Story 2.7). Exactly one ``reason_id`` reaches the package, which is also
    FR-93's *"at most one clarifying question per turn"* made structural.

    It declares its agent like any other package. A refusal is the answer most likely to
    be read as *"the system does not know"*, and the reader is owed the knowledge that it
    is the approved published data that does not hold it (FR-83).

    Whatever went wrong *choosing* the statement is appended to whatever went wrong
    producing it, in that order, so a refusal that was weakened by an unreadable
    unapproved catalogue says so on the same package that carries the weaker sentence.
    """
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=statement.kind,
        agent=declare_agent(catalogue, answer.lang, PackageSource.APPROVED),
        spec=answer.question.spec,
        bindings=answer.question.bindings,
        resolution=answer.execution.resolution,
        reason=statement.text,
        reason_id=statement.message_id,
        refusal_code=statement.code,
        degradations=(*degradations, *statement.degradations),
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
        agent=declare_agent(catalogue, lang, PackageSource.EXTERNAL),
        spec=question.spec,
        bindings=question.bindings,
        reason=render(catalogue, lang, AnswerMessage.EXTERNAL_UNAVAILABLE),
        reason_id=AnswerMessage.EXTERNAL_UNAVAILABLE,
        # An unreachable dependency, said as one. It is the sixth cause and never the
        # first: *"no external agent is wired"* is a fact about this deployment, and
        # rendering it as an absence in the data would be the AD-15 defect crossing the
        # approved/external line (findings 23, 128, 150).
        refusal_code=RefusalCode.DATA_COULD_NOT_BE_REACHED,
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
