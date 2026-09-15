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
    question: Question, earlier: CompiledQuestion | None, catalogue: CataloguePort
) -> tuple[_Resolved[str], Span | None]:
    """The detail, by exact normalised-name lookup, and the span its name occupied.

    Epic 1 resolution is this and nothing else. A name published by two details is
    refused rather than chosen between -- choosing is what a similarity score does, and
    AD-25 puts that behind structural discrimination in Epic 2.
    """
    for span in question.spans():
        found = catalogue.details_named(span.text)
        if not found:
            continue
        if len(found) == 1:
            return _from_reader(Bound(found[0])), span
        return _not_bound(unbound(UnboundReason.DETAIL_NAME_IS_SHARED, ", ".join(found))), span

    carried: _Resolved[str] | None = _inherited(earlier, SpecField.DETAIL)
    if carried is not None:
        return carried, None
    return _not_bound(unbound(UnboundReason.NO_DETAIL_NAMED, " ".join(question.words))), None


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


def compile_question(request: CompileInput, catalogue: CataloguePort) -> CompiledQuestion:
    """Bind every field once, then freeze the spec. The only ``QuerySpec`` construction.

    History is compiled first, by this same function, so a follow-up inherits what the
    earlier turn actually bound rather than a second reading of the earlier words.
    """
    earlier = _earlier_turn(request, catalogue)
    question = Question.parse(request.question)

    detail, span = _bind_detail(question, earlier, catalogue)
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
