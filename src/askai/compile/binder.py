"""The one place a ``QuerySpec`` is constructed.

Purity: pure; asks the catalogue port for names and nothing else.

AD-1: a frozen spec is produced **exactly once per answerable question, before any data
access**, and no layer past ``compile/`` may set, widen or reinterpret a field. Both
halves are structural here rather than promised. The spec is built in exactly one
function, and the only thing this module can reach is ``CataloguePort`` -- a port with no
method that returns a value, a row or a period that exists in the data. A binder that
wanted to peek at the newest row has nothing to peek with.

AD-19: every field walks one ladder -- **named-in-question, inherited-from-history, rule
default, ``Unbound``** -- and exactly one binder owns each field's final value. The
ladder is stated as data in ``R-BIND-PRECEDENCE`` and walked here in that order; the
account of which rung each field came off leaves with the spec, on ``CompiledQuestion``.

FR-4 and FR-5, which are the same decision seen from two sides: a grain the question
names wins over everything, **including the grain of the most recent row**; a question
naming no grain uses the detail's **declared default**, which is why the grain comes off
the catalogue and the newest row is not reachable from here at all. FR-6: a named grain
the detail does not publish leaves the period ``Unbound`` with that as its reason -- no
adjacent grain is ever substituted.

AD-17: ``today`` arrives on ``CompileInput``. Nothing here reads a clock, so the same
question, history and ``today`` compile to the same spec on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from askai.compile.binding import (
    Binding,
    BoundBy,
    CompiledQuestion,
    Precedence,
    SpecField,
    UnboundReason,
    unbound,
)
from askai.compile.lexicon import (
    benchmark_words,
    default_country_scope,
    default_measure,
    default_operation,
    default_period_is_latest,
    grain_words,
    latest_words,
    measure_words,
    readings_for_latest,
)
from askai.compile.periods import PeriodRefusal, grain_of, implied_grain, period_named
from askai.compile.question import Question, Span
from askai.compile.resolve import (
    Disambiguation,
    QuestionSignals,
    Refusal,
    Resolution,
    Resolved,
    resolve,
    window_for,
)
from askai.domain.period import Grain
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named
from askai.domain.spec import (
    Bound,
    FieldState,
    LastN,
    Latest,
    Measure,
    Operation,
    PeriodSpec,
    QuerySpec,
    Unbound,
    period_field,
)
from askai.ports.catalogue import CataloguePort
from askai.ports.resolution import CandidatePort

__all__ = ["CompileInput", "compile_question"]


@dataclass(frozen=True, slots=True)
class CompileInput:
    """Everything compiling a question depends on, stated rather than reached for.

    ``today`` is a field because AD-17 makes determinism a gate: a clock read inside
    pure code would mean the same question compiled differently tomorrow, and the corpus
    entry that pins a date would have nothing to pin it to.

    ``history`` is the reader's earlier questions, oldest first. It is an *input* to
    compiling, never a store another layer reads (AD-19): a follow-up overrides only the
    fields its own question names, and everything else inherits unchanged.
    """

    question: str
    today: date
    history: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Resolved[T]:
    """One field's value and the rung of the ladder it came off."""

    state: FieldState[T]
    precedence: Precedence
    bound_by: BoundBy | None

    def binding(self, field: SpecField) -> Binding:
        return Binding(field=field, precedence=self.precedence, bound_by=self.bound_by)


def _from_reader[T](state: FieldState[T]) -> _Resolved[T]:
    """The reader said it in this question."""
    return _Resolved(
        state=state, precedence=Precedence.NAMED_IN_QUESTION, bound_by=BoundBy.READER
    )


def _from_history[T](state: FieldState[T]) -> _Resolved[T]:
    """The reader said it in an earlier turn, and this question did not override it."""
    return _Resolved(
        state=state, precedence=Precedence.INHERITED_FROM_HISTORY, bound_by=BoundBy.READER
    )


def _from_rules[T](value: T) -> _Resolved[T]:
    """Nobody said it, and a rule in ``rules/`` says what happens then."""
    return _Resolved(
        state=Bound(value), precedence=Precedence.RULE_DEFAULT, bound_by=BoundBy.RULE
    )


def _not_bound[T](state: Unbound) -> _Resolved[T]:
    """Nobody said it and no rule covers it: the answer is a clarification or a refusal."""
    return _Resolved(state=state, precedence=Precedence.UNBOUND, bound_by=None)


def _inherited[T](earlier: CompiledQuestion | None, field: SpecField) -> _Resolved[T] | None:
    """What an earlier turn bound *field* to, if it bound it to anything.

    An earlier ``Unbound`` is not inherited: carrying forward "the reader was not
    specific enough" would answer this question with the previous one's ambiguity.
    """
    if earlier is None:
        return None
    state = earlier.state_of(field)
    if isinstance(state, Unbound):
        return None
    inherited: FieldState[T] = state  # type: ignore[assignment]
    return _from_history(inherited)


# ------------------------------------------------------------------------------- detail


def _bind_detail(
    question: Question,
    earlier: CompiledQuestion | None,
    catalogue: CataloguePort,
    resolution: Resolution | None,
) -> tuple[_Resolved[str], Span | None]:
    """The detail, and the span its name occupied if the reader typed one.

    Two rungs, in this order, and the order is the whole design.

    **Exact normalised-name lookup first.** It is Epic 1's only rung and it stays first
    because it is the cheapest and the most reliable: measured at 96% recall@1 over the
    labelled set, against 21.4% for paraphrases through the index. A reader who typed a
    published name has already told us which detail they mean, and running a similarity
    search over that would be replacing certainty with a ranking.

    **Then AD-25's ladder**, for the reader who paraphrased -- which, with 257 of 320
    published names ambiguous, is most readers. It arrives here already resolved: the
    caller ran it, because ``compile/`` may not reach an adapter and the port that
    produces candidates is one. What reaches this function is a value.

    A name published by two details still refuses rather than choosing, and that is
    unchanged: an exactly typed ambiguous name is an ambiguity the reader created and the
    engine cannot resolve for them. The difference is that the ladder's own disambiguation
    now has somewhere to go instead of being flattened into the same refusal.
    """
    for span in question.spans():
        found = catalogue.details_named(span.text)
        if not found:
            continue
        if len(found) == 1:
            return _from_reader(Bound(found[0])), span
        return _not_bound(unbound(UnboundReason.DETAIL_NAME_IS_SHARED, ", ".join(found))), span

    # The reader named no published detail exactly. AD-25's ladder is the next rung, and
    # it is consulted before history: a follow-up that names a *new* subject is a new
    # question about that subject, and inheriting the earlier detail would answer the
    # previous question with this one's words.
    if isinstance(resolution, Resolved):
        return (
            _Resolved(
                state=Bound(resolution.detail_id),
                precedence=Precedence.NAMED_IN_QUESTION,
                # FR-14's axis: the reader's words chose it, but a semantic match is what
                # read them. `SEMANTIC` has been in `BoundBy` since Epic 1 for this rung.
                bound_by=BoundBy.SEMANTIC,
            ),
            None,
        )

    carried: _Resolved[str] | None = _inherited(earlier, SpecField.DETAIL)
    if carried is not None:
        return carried, None
    return _not_bound(_unresolved(question, resolution)), None


def _unresolved(question: Question, resolution: Resolution | None) -> Unbound:
    """Why no detail bound -- taken from the ladder when it ran, so the cause is specific.

    *"Several indicators match and I cannot tell which you mean"* and *"I hold nothing
    like that"* are different facts about the world and a reader acts on them differently
    (AD-15). Flattening both into ``NO_DETAIL_NAMED`` is what this avoids; Story 2.7
    phrases the six refusals from these causes and Story 2.11 puts the closed question.
    """
    match resolution:
        case Disambiguation(candidates=candidates):
            return unbound(
                UnboundReason.SEVERAL_INDICATORS_MATCH,
                ", ".join(offered.surface for offered in candidates),
            )
        case Refusal(cause=cause, vetoed_by=vetoed_by):
            particulars = ", ".join(signal.value for signal in vetoed_by)
            return unbound(
                UnboundReason.NO_INDICATOR_RESOLVED,
                f"{cause.value}{f'; ruled out by {particulars}' if particulars else ''}",
            )
        case _:
            return unbound(UnboundReason.NO_DETAIL_NAMED, " ".join(question.words))


# ------------------------------------------------------------------------------- period


def _named_grain(question: Question, *, excluding: Span | None) -> Grain | None:
    """The interval the question named in words, if it named one (FR-4).

    A month name or a quarter phrase carrying no year counts too, and counts as the
    reader naming it (FR-5): *"What was inflation in April?"* names no period -- picking
    the year would be compile inventing one -- but it does say monthly.
    """
    found = question.names_one_of(grain_words(), excluding=excluding)
    if found is not None:
        return found[0]
    return implied_grain(question, excluding=excluding)


def _latest_at(interval: Grain | None) -> PeriodSpec:
    """"The latest reading", at *interval* when one is known.

    ``Latest`` carries no interval, so a known one is expressed as the last *n* readings
    at it -- ``n`` being ``R-BIND-GRAIN-FROM-DECLARED-DEFAULT``'s ``readings``. Both
    forms need the data to resolve, so both leave the field ``Deferred`` (AD-1).
    """
    if interval is None:
        return Latest()
    return LastN(n=readings_for_latest(), grain=interval)


def _unpublished(catalogue: CataloguePort, detail_id: str | None, interval: Grain) -> bool:
    """Does the bound detail publish at *interval*? FR-6: if not, it is stated, not swapped."""
    if detail_id is None:
        return False
    published = catalogue.published_grains(detail_id)
    return bool(published) and interval not in published


def _refuse_interval(catalogue: CataloguePort, detail_id: str, interval: Grain) -> Unbound:
    published = ", ".join(sorted(catalogue.published_grains(detail_id)))
    return unbound(UnboundReason.GRAIN_NOT_PUBLISHED, f"{interval.value}; published: {published}")


def _bind_period(
    question: Question,
    earlier: CompiledQuestion | None,
    catalogue: CataloguePort,
    detail_id: str | None,
    today: date,
    *,
    excluding: Span | None,
) -> _Resolved[PeriodSpec]:
    """The period, by AD-19's ladder, with FR-4 and FR-6 applied to whatever named a grain.

    Every shape of period expression -- absolute, relative, span, open span, in either
    language -- is read by ``compile.periods`` and arrives here as one ``PeriodSpec``, so
    this stays the ladder it was and does not become a second parser (FR-7).
    """
    named = period_named(question, today, excluding=excluding)
    if isinstance(named, PeriodRefusal):
        return _not_bound(unbound(named.reason, named.particulars))

    # A period expression names its own interval, and that interval is one the reader
    # named -- "over the last 5 years" says yearly as surely as the word "yearly" does.
    interval = grain_of(named) if named is not None else _named_grain(question, excluding=excluding)
    if interval is not None and _unpublished(catalogue, detail_id, interval):
        assert detail_id is not None  # _unpublished is False without a bound detail
        return _not_bound(_refuse_interval(catalogue, detail_id, interval))

    if named is not None:
        return _from_reader(period_field(named))

    if question.names(latest_words(), excluding=excluding) is not None:
        at = interval if interval is not None else _declared(catalogue, detail_id)
        return _from_reader(period_field(_latest_at(at)))
    if interval is not None:
        # A grain named with no period is "the latest, at that grain" -- and it outranks
        # whatever an earlier turn carried, which is FR-4's "wins over every signal".
        return _from_reader(period_field(_latest_at(interval)))

    carried: _Resolved[PeriodSpec] | None = _inherited(earlier, SpecField.PERIOD)
    if carried is not None:
        return carried
    if not default_period_is_latest():  # pragma: no cover -- one member today
        raise ValueError("R-BIND-PERIODLESS-IS-LATEST names a default this binder cannot build")
    latest = period_field(_latest_at(_declared(catalogue, detail_id)))
    return _Resolved(
        state=latest, precedence=Precedence.RULE_DEFAULT, bound_by=BoundBy.RULE
    )


def _declared(catalogue: CataloguePort, detail_id: str | None) -> Grain | None:
    """The detail's *declared* default interval -- never the interval of its newest row."""
    return None if detail_id is None else catalogue.default_grain(detail_id)


# ------------------------------------------------------------------------ country scope


def _bind_country_scope(
    question: Question, earlier: CompiledQuestion | None, catalogue: CataloguePort
) -> _Resolved[CountryScope]:
    """The scope, which is a query shape and never a country filter value (AD-5).

    The home country is in no published row and so in no catalogue of countries: naming
    it matches nothing here and falls through to the national default. That is the whole
    mechanism -- there is no name to special-case and no list to keep in step.
    """
    named: list[str] = []
    for span in question.spans():
        found = catalogue.country_named(span.text)
        if found is not None and found not in named:
            named.append(found)
    if named:
        return _from_reader(Bound(Named(countries=frozenset(named))))
    if question.names(benchmark_words()) is not None:
        return _from_reader(Bound(DeclaredBenchmarks()))

    carried: _Resolved[CountryScope] | None = _inherited(earlier, SpecField.COUNTRY_SCOPE)
    if carried is not None:
        return carried
    return _from_rules(default_country_scope())


# ------------------------------------------------------------------ measure and operation


def _bind_measure(
    question: Question, earlier: CompiledQuestion | None, *, excluding: Span | None
) -> _Resolved[Measure]:
    """The measure. A measure word inside the detail's own published name does not count."""
    found = question.names_one_of(measure_words(), excluding=excluding)
    if found is not None:
        return _from_reader(Bound(found[0]))
    carried: _Resolved[Measure] | None = _inherited(earlier, SpecField.MEASURE)
    if carried is not None:
        return carried
    return _from_rules(default_measure())


def _bind_operation(earlier: CompiledQuestion | None) -> _Resolved[Operation]:
    """The operation, which in this epic is always the rule default.

    Operation classification is one of the four bounded model call-sites (AD-22) and this
    epic makes no model call, so nothing here classifies: the field is bound by a rule,
    it says so, and the epic that adds the classifier replaces a named default rather
    than an assumption.
    """
    carried: _Resolved[Operation] | None = _inherited(earlier, SpecField.OPERATION)
    if carried is not None:
        return carried
    return _from_rules(default_operation())


# --------------------------------------------------------------------------- the binder


def compile_question(
    request: CompileInput,
    catalogue: CataloguePort,
    candidates: CandidatePort | None = None,
) -> CompiledQuestion:
    """Bind every field once, then freeze the spec. The only ``QuerySpec`` construction.

    History is compiled first, by this same function, so a follow-up inherits what the
    earlier turn actually bound rather than a second reading of the earlier words.

    *candidates* of ``None`` compiles with exact normalised-name lookup alone -- Epic 1's
    behaviour exactly, and the reason every existing caller and every corpus entry keeps
    compiling to the spec it did. It is an argument rather than a field on ``CompileInput``
    because it is a *port*, and the input is a value a test can write down.

    The ladder runs **before** the binders, not inside one, because AD-25 stage 2 uses
    signals the compiler has already extracted and the period binder is what extracts
    them. That ordering is resolved below: the period is read first for its grain and
    span, resolution consumes them, and the detail binds from the result.
    """
    earlier = _earlier_turn(request, catalogue)
    question = Question.parse(request.question)

    resolution = _resolve(request, question, catalogue, candidates)
    detail, span = _bind_detail(question, earlier, catalogue, resolution)
    detail_id = detail.state.value if isinstance(detail.state, Bound) else None
    period = _bind_period(question, earlier, catalogue, detail_id, request.today, excluding=span)
    scope = _bind_country_scope(question, earlier, catalogue)
    measure = _bind_measure(question, earlier, excluding=span)
    operation = _bind_operation(earlier)

    spec = QuerySpec(
        detail=detail.state,
        period=period.state,
        country_scope=scope.state,
        measure=measure.state,
        operation=operation.state,
        today=request.today,
    )
    return CompiledQuestion(
        spec=spec,
        bindings=(
            detail.binding(SpecField.DETAIL),
            period.binding(SpecField.PERIOD),
            scope.binding(SpecField.COUNTRY_SCOPE),
            measure.binding(SpecField.MEASURE),
            operation.binding(SpecField.OPERATION),
        ),
        resolution=resolution,
    )


def _resolve(
    request: CompileInput,
    question: Question,
    catalogue: CataloguePort,
    candidates: CandidatePort | None,
) -> Resolution | None:
    """Run AD-25's ladder, or ``None`` when no candidate port was supplied.

    Skipped entirely when the reader typed a published name exactly: that rung has already
    won, a search would not change the answer, and doing the work anyway would make every
    exactly-named question pay for a stage it does not use.

    The signals handed to stage 2 are read off the *same* ``Question`` the binders read,
    through the same period parser, so stage 2 discriminates on what the period binder
    will actually bind rather than on a second reading of the words.
    """
    if candidates is None:
        return None
    if any(catalogue.details_named(span.text) for span in question.spans()):
        return None
    return resolve(
        request.question,
        candidates,
        _question_signals(question, request.today, catalogue),
    )


def _question_signals(
    question: Question, today: date, catalogue: CataloguePort
) -> QuestionSignals:
    """What the other binders have already extracted, as stage 2 reads it.

    Read through ``compile.periods`` and ``CataloguePort`` -- the same two things the
    period and country binders use -- so this cannot become a second parser that disagrees
    with the first about what the reader said (AD-25).
    """
    named = period_named(question, today, excluding=None)
    if isinstance(named, PeriodRefusal):
        # A period the reader spelled and the engine refused. The refusal is the period
        # binder's to state; resolution proceeds with no period signal rather than
        # inventing one, so the reader still learns *which indicator* they meant.
        return QuestionSignals(countries=_named_countries(question, catalogue))
    grain = grain_of(named) if named is not None else _named_grain(question, excluding=None)
    return QuestionSignals(
        grain=grain,
        window=window_for(named),
        countries=_named_countries(question, catalogue),
    )


def _named_countries(question: Question, catalogue: CataloguePort) -> frozenset[str]:
    """The countries the reader named, resolved by the same lookup the scope binder uses."""
    return frozenset(
        found
        for span in question.spans()
        if (found := catalogue.country_named(span.text)) is not None
    )


def _earlier_turn(request: CompileInput, catalogue: CataloguePort) -> CompiledQuestion | None:
    """The most recent turn, compiled the same way, or ``None`` when this is the first.

    Compiled rather than remembered: history is an input, and reconstructing it through
    the one binder is what stops a second, weaker reading of an earlier question growing
    somewhere else.
    """
    if not request.history:
        return None
    return compile_question(
        CompileInput(
            question=request.history[-1],
            today=request.today,
            history=request.history[:-1],
        ),
        catalogue,
    )
