"""One question, answered: compile, fetch, compose, order, record. In that order.

Purity: edge.

This is Epic 1's answer path joined up, and the order of the five steps is the epic's
architecture restated as a call sequence:

1. ``compile/`` freezes one ``QuerySpec`` **before any data access** (AD-1), from a port
   that cannot return a value.
2. ``execute/`` produces the figure, by exact key, and records what it resolved a
   deferred period to (AD-3, FR-8).
3. ``narrate/`` builds the package -- the only layer that may (AD-10).
4. ``respond/`` puts the packages in order and never looks inside one (AD-10).
5. ``observability/`` writes **exactly one record**, after the package is final (AD-16).

Step 5 is last for a reason that is not stylistic. A record written before the package is
final describes an answer that was never given; a record written from two places is the
partial record AD-16 exists to prevent. The ``Recorder`` is constructed here, per request,
and is spent by its single write.

**The engine's only authorisation is membership of the admission set** (AD-24, Story
9.1). ``Ask.sources`` is a ``SourceAdmission``, and the three inhabitants of that type
*are* the three admissible selections -- so by the time a request reaches this module
there is nothing left to authorise. An out-of-set selection never becomes an ``Ask`` at
all: it is refused while the request body is being parsed, as a 4xx, rather than narrowed
to whatever subset the engine could serve. FR-82's *"never silently answered by a source
I did not choose"* is that refusal.

**The engine authenticates nothing** (AD-24). The caller identity arrives asserted by the
surrounding platform, is turned into a recordable value by ``observability/identity``, and
an unasserted one becomes ``Anonymous`` *with the reason recorded* -- which is why there
is no branch here that skips the identity when the header is missing.

**The external agent is fetched in parallel, from t=0, and abandoned here** (Story 9.6,
NFR-10). It is submitted before the question is even compiled and collected after the
packages are final, so the five steps above run *while* the third party is thinking and
the approved answer is never waiting on it. The deadline is enforced on this side: when
the budget expires the wait is dropped and the answer is composed without it, whatever
the platform is still doing. That is the only arrangement in which *"a slow or dead
external dependency cannot degrade, delay or block the approved answer"* is a property of
the code rather than a promise about the third party's latency.

**And the two answers never become one** (Story 9.7). The approved half is a tuple of
``AnswerPackage``; the external half is an ``ExternalAnswer``, a type with no ``elements``,
no ``spec`` and no ``row_ids`` for a figure to cross through. They are produced by
different functions from different inputs and are returned side by side. There is no
function in this module -- or anywhere -- that takes both and returns one, and
``mypy --strict`` refuses the one somebody would write.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from askai.api.engine import Engine
from askai.api.tiebreak import TieBreakRung
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import Binding, CompiledQuestion
from askai.domain.admission import PackageSource, SourceAdmission
from askai.execute.shapes import Executed, execute_operation
from askai.messages import Lang, render
from askai.narrate.package import AnswerPackage
from askai.narrate.structured import (
    Answer,
    AnswerMessage,
    declare_agent,
    external_package,
    structured_package,
)
from askai.observability.degradations import DegradationKind, degrade
from askai.observability.identity import CallerIdentity, caller_identity
from askai.observability.record import (
    AnswerRecord,
    BindingMechanism,
    ExternalCall,
    FieldBinding,
    RuleFired,
)
from askai.observability.recorder import Recorder
from askai.ports.external_agent import (
    ExternalOutcome,
    ExternalRequest,
    ExternalResult,
)
from askai.ports.freshness import Freshness
from askai.ports.record import RecordRow
from askai.respond.external import ExternalAnswer
from askai.respond.order import ordered
from askai.respond.response import Response

__all__ = [
    "PACKAGE_ORDER",
    "Answered",
    "Ask",
    "answer_question",
    "external_context_line",
]

#: The order packages are returned in, by source. Approved first, unconditionally: the
#: reader's own published data is the answer, and anything external is context beside it
#: (FR-84). The order is declared rather than emergent so that "Combined differs only by
#: returning two packages" stays true of the *sequence* as well as of the count.
PACKAGE_ORDER = (PackageSource.APPROVED.value, PackageSource.EXTERNAL.value)

#: The first turn of a conversation. The engine owns no session store (AD-24), so it
#: cannot know a request is the fifth turn of anything; it records the turn it can
#: defend, and the conversation id carries the thread the client is keeping.
FIRST_TURN = 1

#: What a fired rule's recorded outcome says. The rule *id* is the durable reference and
#: ``rules enumerate`` reads the statement back; copying reviewed prose into an audit row
#: on every answer would make the record grow with the rule catalogue (NFR-9).
RULE_APPLIED = "applied"

#: Where a degradation raised on this side of the external call says it happened. The
#: adapter has its own address, so a rising rate tells an abandonment the engine chose
#: from a platform that refused the job.
_WHERE = "api.ask:external"

#: What an abandoned job is called when the engine never learned its real id. A placeholder
#: rather than a ``None``, because the count of orphans is the number that says whether
#: the budget is too tight, and an orphan that did not increment it is unexamined.
_UNNAMED_JOB = "unknown"


@dataclass(frozen=True, slots=True)
class Ask:
    """One request, as the engine sees it after the transport has been stripped off.

    There is **no lens field**, and there never will be (AD-23): the lens is a view over
    one answer, so a request that carried one would make the engine compose two different
    answers to the same question and lose the property FR-59b rests on.
    """

    question: str
    lang: Lang
    #: The closed source admission set, never a loose tuple of source names (Story 9.1).
    #: A tuple could be empty, could repeat a source, and could carry one the engine has
    #: no composer for -- three states every reader of the field would have to reject
    #: again. ``SourceAdmission`` has three inhabitants and no fourth, so a value that
    #: exists here is already authorised and the answer path below has nothing to check.
    sources: SourceAdmission
    conversation_id: str | None = None
    #: The identity the surrounding platform asserted, or ``None`` when it asserted
    #: nothing. ``None`` is carried rather than defaulted so that "nothing was asserted"
    #: and "something blank was asserted" stay distinguishable (AD-24).
    asserted_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a question is asked; an empty one has nothing to compile")


@dataclass(frozen=True, slots=True)
class Answered:
    """What answering produced: the response, the external half, and the one record.

    **Two answers, in two fields of two types** (FR-85, AD-10). ``response`` carries the
    approved packages and ``external`` carries the third party's, and there is no third
    field holding a reconciliation of them because there is no type a reconciliation could
    be. A caller that wants both shows both, labelled; a caller that wants one takes one.
    Neither can take a blend, because none was made.

    ``external`` is ``None`` exactly when the admission did not admit the external agent.
    That is a different fact from an external call that failed -- which is an
    ``ExternalAnswer`` stating its gap -- and the two are kept apart here for the reason
    ``Absent`` and ``Failed`` are kept apart in ``observability/degradations``.
    """

    response: Response[AnswerPackage]
    record: RecordRow
    identity: CallerIdentity
    external: ExternalAnswer | None = None


def answer_question(engine: Engine, ask: Ask) -> Answered:
    """Answer *ask*, then write the single record describing what was answered.

    The external call is started **first** and collected **last**. Between those two
    lines sits the whole approved path, unchanged and unaware: it compiles, fetches,
    composes, orders and finishes without a single statement that waits on the third
    party. NFR-10 is that ordering.
    """
    moment = engine.now()
    request = _external_request(ask, moment)
    with _ExternalCall(engine, request) as in_flight:
        rung = None if engine.model is None else TieBreakRung(engine.model)
        compiled = compile_question(
            CompileInput(question=ask.question, today=moment.date()),
            engine.names,
            engine.candidates,
            tie_break=rung,
        )
        # One execution, in whatever shape the bound operation asks for. Not a ladder of
        # per-operation call sites: `execute_operation` is one function over the closed
        # `Operation`, and what comes back is the closed `Executed`, so an operation added
        # to the domain fails to type-check somewhere rather than falling through to the
        # single-figure fetch -- which is the defect this line replaces.
        execution = execute_operation(compiled, engine.datapoints)
        freshness = engine.freshness.freshness(moment)

        packages = _packages(engine, ask, compiled, execution)
        response = Response(
            conversation_id=ask.conversation_id or uuid.uuid4().hex,
            packages=ordered(packages, lambda package: package.source.value, PACKAGE_ORDER),
            freshness=freshness,
        )
        # Collected only now: every guard the approved half runs has already run, and the
        # external half is appended to the answer rather than composed into it (AD-10).
        result = in_flight.collect()

    external = None if result is None else _external_answer(engine, ask, result)
    identity = caller_identity(ask.asserted_identity)
    record = Recorder(engine.records).record(
        _record(ask, compiled, response, identity, moment, freshness, rung, result)
    )
    return Answered(
        response=response, record=record, identity=identity, external=external
    )


# -------------------------------------------------------------- the external agent (9.6)


#: What the outbound context line is made of. A list of ``field=value`` pairs the engine
#: composes from the request alone -- never from the published layer, which has no field
#: on ``ExternalRequest`` to travel in (NFR-4a). Deterministic, so the line recorded on an
#: answer is reproducible from the same request months later (AD-17).
_CONTEXT_SEPARATOR = "; "


def external_context_line(lang: Lang, moment: datetime) -> str:
    """The deterministic context sent alongside the reader's question, and nothing more.

    Exported and kept to one expression so that *"what the engine sends is explicit and
    minimal"* (NFR-4a) is a thing a test reads rather than a claim about a call site. Two
    facts: which language to answer in, and the date the question was asked on -- the
    second because a third party asked *"what is inflation now"* with no date answers
    about its own today, which is not necessarily the reader's.

    There is no figure, no indicator id, no period key and no row here, and there is
    nowhere for one to be added without this function changing -- which is the review a
    line like this deserves.
    """
    return _CONTEXT_SEPARATOR.join(
        (f"language={lang.value}", f"asked_on={moment.date().isoformat()}")
    )


def _external_request(ask: Ask, moment: datetime) -> ExternalRequest | None:
    """The outbound request, or ``None`` when this admission admits no external agent.

    FR-79 read from the other end: an approved-only request does not merely ignore the
    external answer, it never makes the call. The check is here, once, at the only place
    the call is started.
    """
    if not ask.sources.admits_source(PackageSource.EXTERNAL):
        return None
    return ExternalRequest(
        question=ask.question,
        context=external_context_line(ask.lang, moment),
    )


class _ExternalCall:
    """One external call, in flight on its own thread, abandoned on its own budget.

    A context manager because the abandonment has to happen whatever the approved path
    did -- including raising. ``__exit__`` shuts the pool down **without waiting**, so a
    third party that never answers holds a worker thread and nothing else; it does not
    hold the request, the response, or the reader.

    A thread rather than an event loop: the approved path is synchronous, sqlite-bound and
    deliberately single-threaded (see ``api/app.py`` on why the handlers are ``async``),
    and making it awaitable in order to overlap one outbound call would be rewriting the
    engine around its least important dependency.

    ``collect`` is total and returns within the budget measured from construction. A
    result, or the abandonment stated as one -- never an exception, because an exception
    here would be the external half degrading the approved answer, which is the single
    thing NFR-10 forbids.
    """

    def __init__(self, engine: Engine, request: ExternalRequest | None) -> None:
        self._engine = engine
        self._request = request
        self._started = time.monotonic()
        self._pool: ThreadPoolExecutor | None = None
        self._future: Future[ExternalResult] | None = None
        if request is not None and engine.external is not None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="askai-external")
            self._future = self._pool.submit(engine.external.ask, request)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def collect(self) -> ExternalResult | None:
        """What the external agent produced, or ``None`` if none was asked."""
        request = self._request
        if request is None:
            return None
        if self._future is None:
            return self._unwired(request)
        remaining = request.budget.total_seconds - (time.monotonic() - self._started)
        try:
            return self._future.result(timeout=max(remaining, 0.0))
        except FutureTimeout:
            return self._abandoned(request)

    def _unwired(self, request: ExternalRequest) -> ExternalResult:
        """No platform is configured. Stated as an outcome, never as a silent skip."""
        return ExternalResult(
            outcome=ExternalOutcome.UNAVAILABLE,
            request=request,
            elapsed_seconds=self._elapsed(),
            degradations=(
                degrade(
                    DegradationKind.EXTERNAL_AGENT_UNAVAILABLE,
                    _WHERE,
                    "no external agent platform is configured in this deployment; the "
                    "reader selected it, so the gap is stated rather than the selection "
                    "quietly narrowed (FR-82, FR-89)",
                ),
            ),
        )

    def _abandoned(self, request: ExternalRequest) -> ExternalResult:
        """The budget expired on this side. The worker keeps running; the answer does not.

        The job id is unknown here by construction -- the adapter never got far enough to
        return one -- and that is recorded as what it is. An orphan whose name the engine
        never learned is the worst kind, and naming it *unknown* is how it stays counted.
        """
        return ExternalResult(
            outcome=ExternalOutcome.ABANDONED,
            request=request,
            elapsed_seconds=self._elapsed(),
            orphaned_job=_UNNAMED_JOB,
            degradations=(
                degrade(
                    DegradationKind.EXTERNAL_AGENT_UNAVAILABLE,
                    _WHERE,
                    f"the {request.budget.total_seconds}s external budget expired with the "
                    "call still outstanding; it was abandoned client-side without the "
                    "engine ever learning a job id, and the approved answer was composed "
                    "without waiting (NFR-10)",
                ),
            ),
        )

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)


def _external_answer(engine: Engine, ask: Ask, result: ExternalResult) -> ExternalAnswer:
    """The third party's half, caveated unconditionally, and never an empty card.

    The caveat is attached here on **every** path -- the answer, the timeout, the dead
    platform, the deployment with no platform at all -- because FR-84 says *always* and
    not *when they disagree*. ``ExternalAnswer`` refuses to be built without one, so this
    is a restatement rather than the guarantee.

    The band check is **not** applied, and that absence is deliberate rather than
    pending. FR-88a requires a check to state its own limits to the reader, in the
    reader's own language, from the reviewed bilingual catalogue -- and the catalogue has
    no such sentence yet. A check shown without its limits implies a verification that did
    not happen, which is worse than no check at all, so the honest build is this one:
    ``check`` stays ``None``, nothing downstream may read that as a clean result, and the
    ratified band in ``respond/external.py`` is tested and ready for the sentence.
    """
    caveat = render(engine.messages, ask.lang, AnswerMessage.EXTERNAL_CAVEAT)
    agent = declare_agent(engine.messages, ask.lang, PackageSource.EXTERNAL)
    answered = result.outcome is ExternalOutcome.ANSWERED
    return ExternalAnswer(
        agent=agent,
        caveat=caveat,
        outcome=result.outcome,
        prose=result.prose if answered else "",
        reason=""
        if answered
        else render(engine.messages, ask.lang, AnswerMessage.EXTERNAL_UNAVAILABLE),
        elapsed_seconds=result.elapsed_seconds,
        degradations=result.degradations,
    )


def _packages(
    engine: Engine, ask: Ask, compiled: CompiledQuestion, execution: Executed
) -> tuple[AnswerPackage, ...]:
    """One package per admitted source. Never merged, never de-duplicated (AD-10).

    **One answer path, and no Combined-specific composition.** The loop reads the sources
    off the admission and dispatches each to its own composer; there is no branch here
    naming ``BOTH``, so the approved package returned for Combined is produced by the
    same ``_approved`` call, from the same inputs, as the one returned for the approved
    layer alone. That is Story 9.1's *"composed identically in every case that admits
    it"* stated as a call graph rather than as a rule two branches have to keep agreeing
    on -- and it is why the ladder of three routing paths the predecessor kept cannot be
    written here: there is one path, parameterised by a closed type.
    """
    built: list[AnswerPackage] = []
    for source in ask.sources.admits:
        match source:
            case PackageSource.APPROVED:
                built.append(_approved(engine, ask, compiled, execution))
            case PackageSource.EXTERNAL:
                built.append(external_package(compiled, engine.messages, ask.lang))
    return tuple(built)


def _approved(
    engine: Engine, ask: Ask, compiled: CompiledQuestion, execution: Executed
) -> AnswerPackage:
    """The approved package, with the published detail read *after* the fetch.

    The presentation port is asked only once a figure exists. That ordering is not an
    optimisation: it keeps the catalogue that can name a unit out of reach while the spec
    is being bound, so AD-1's "before any data access" is a property of what was
    available rather than of what was called.
    """
    figure = execution.figure
    published = None
    country_name = None
    if figure is not None:
        published = engine.presentation.detail(figure.detail_id, ask.lang)
        if figure.country_id is not None:
            country_name = engine.presentation.country(figure.country_id, ask.lang)
    return structured_package(
        Answer(
            question=compiled,
            execution=execution,
            lang=ask.lang,
            published=published,
            country_name=country_name,
        ),
        engine.messages,
        engine.formatter,
        engine.placement,
        engine.sources,
        groups=engine.groups,
    )


# ------------------------------------------------------------------------ the record


def _record(
    ask: Ask,
    compiled: CompiledQuestion,
    response: Response[AnswerPackage],
    identity: CallerIdentity,
    moment: datetime,
    freshness: Freshness,
    rung: TieBreakRung | None,
    external: ExternalResult | None,
) -> AnswerRecord:
    """The one record for this request, built from the finished packages.

    Everything AD-16 asks for comes from values that already exist: the spec and the
    per-field mechanism from ``compile/``, the row ids and the fired rules from the
    packages, the degradations from the same, and the identity from ``observability/``.
    Nothing is recomputed, so the record cannot disagree with the answer it describes.
    """
    return AnswerRecord(
        record_id=uuid.uuid4().hex,
        recorded_at=moment,
        identity=identity,
        language=ask.lang,
        question=ask.question,
        spec=compiled.spec,
        bindings=tuple(_binding(binding, response) for binding in compiled.bindings),
        row_ids=tuple(
            row_id for package in response.packages for row_id in package.row_ids
        ),
        rules_fired=tuple(
            RuleFired(rule_id=rule_id, outcome=RULE_APPLIED)
            for rule_id in dict.fromkeys(
                rule_id for package in response.packages for rule_id in package.rules_fired
            )
        ),
        degradations=(
            *(
                degradation
                for package in response.packages
                for degradation in package.degradations
            ),
            # What the model rung counted, which no package carries: a tie-break that
            # fell back changed nothing the reader sees -- they are asked the question
            # the deterministic ladder had already composed -- and everything about how
            # the answer was reached (AD-15, AD-16).
            *(() if rung is None else rung.degradations),
            # What the external call counted, which no approved package carries and must
            # not: a third party that timed out is a fact about the answer, and putting it
            # on the approved package would be the external half degrading the approved
            # one -- the crossing NFR-10 and AD-10 both forbid, in opposite directions.
            *(() if external is None else external.degradations),
        ),
        # Empty unless a model was configured *and* a tie reached the rung, which is
        # every answer on a deployment with no model (NFR-6). The field is populated
        # rather than omitted so an old answer can say it used none (AD-29).
        prompts=() if rung is None else rung.prompts,
        elements=tuple(
            placed.element for package in response.packages for placed in package.elements
        ),
        data_as_of=None if freshness.refreshed_at is None else freshness.refreshed_at.isoformat(),
        conversation_id=response.conversation_id,
        turn=FIRST_TURN,
        # FR-90: the agent the reader selected, in the reader's own spelling, on every
        # answer -- including the ones that never went near a third party, because "which
        # agent was asked" is not recoverable from the packages afterwards.
        agent=ask.sources.value,
        external_call=_external_record(external),
    )


def _external_record(external: ExternalResult | None) -> ExternalCall | None:
    """The external call as the audit row holds it: what went out, and what it did.

    What came *back* is deliberately not here. The record stores the outbound payload
    (NFR-4a) and the outcome, and copying the third party's prose in would make one row
    grow with the length of somebody else's essay -- which is the bound Story 1.16 put on
    the record in the first place (NFR-9).
    """
    if external is None:
        return None
    return ExternalCall(
        outcome=external.outcome,
        sent_question=external.request.question,
        sent_context=external.request.context,
        job_id=external.job_id,
        orphaned_job=external.orphaned_job,
        elapsed_seconds=external.elapsed_seconds,
    )


def _binding(binding: Binding, response: Response[AnswerPackage]) -> FieldBinding:
    """One spec field, its mechanism, and -- for a deferred period -- what it became.

    ``Precedence`` and ``BindingMechanism`` spell the four rungs identically, so the
    mechanism is *read across* rather than mapped through a table here: a table would be
    a second statement of AD-19's ladder, free to drift from the first.
    """
    return FieldBinding(
        field=binding.field.value,
        mechanism=BindingMechanism(binding.precedence.value),
        note=_resolution_note(binding, response),
    )


def _resolution_note(binding: Binding, response: Response[AnswerPackage]) -> str:
    """What ``execute/`` resolved a deferred field to -- the question an old answer is
    asked most often, and the one the spec alone cannot answer."""
    if binding.field.value != "period":
        return ""
    for package in response.packages:
        resolution = package.resolution
        if resolution is None or not resolution.was_deferred or resolution.period is None:
            continue
        return f"resolved to {resolution.period.value} by {resolution.resolved_by}"
    return ""


