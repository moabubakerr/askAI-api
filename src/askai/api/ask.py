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

**The engine authenticates nothing** (AD-24). The caller identity arrives asserted by the
surrounding platform, is turned into a recordable value by ``observability/identity``, and
an unasserted one becomes ``Anonymous`` *with the reason recorded* -- which is why there
is no branch here that skips the identity when the header is missing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from askai.api.engine import Engine
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import Binding, CompiledQuestion
from askai.execute.value import Execution, execute_value
from askai.messages import Lang
from askai.narrate.package import AnswerPackage, PackageSource
from askai.narrate.structured import Answer, external_package, structured_package
from askai.observability.identity import CallerIdentity, caller_identity
from askai.observability.record import (
    AnswerRecord,
    BindingMechanism,
    FieldBinding,
    RuleFired,
)
from askai.observability.recorder import Recorder
from askai.ports.freshness import Freshness
from askai.ports.record import RecordRow
from askai.respond.order import ordered
from askai.respond.response import Response

__all__ = ["PACKAGE_ORDER", "Answered", "Ask", "answer_question"]

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


@dataclass(frozen=True, slots=True)
class Ask:
    """One request, as the engine sees it after the transport has been stripped off.

    There is **no lens field**, and there never will be (AD-23): the lens is a view over
    one answer, so a request that carried one would make the engine compose two different
    answers to the same question and lose the property FR-59b rests on.
    """

    question: str
    lang: Lang
    sources: tuple[PackageSource, ...]
    conversation_id: str | None = None
    #: The identity the surrounding platform asserted, or ``None`` when it asserted
    #: nothing. ``None`` is carried rather than defaulted so that "nothing was asserted"
    #: and "something blank was asserted" stay distinguishable (AD-24).
    asserted_identity: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a question is asked; an empty one has nothing to compile")
        if not self.sources:
            raise ValueError(
                "a request selects at least one source; selecting none is not a "
                "narrower question, it is no question"
            )


@dataclass(frozen=True, slots=True)
class Answered:
    """What answering produced: the response, and the one record written for it."""

    response: Response[AnswerPackage]
    record: RecordRow
    identity: CallerIdentity


def answer_question(engine: Engine, ask: Ask) -> Answered:
    """Answer *ask*, then write the single record describing what was answered."""
    moment = engine.now()
    compiled = compile_question(
        CompileInput(question=ask.question, today=moment.date()), engine.names
    )
    execution = execute_value(compiled, engine.datapoints)
    freshness = engine.freshness.freshness(moment)

    packages = _packages(engine, ask, compiled, execution)
    response = Response(
        conversation_id=ask.conversation_id or uuid.uuid4().hex,
        packages=ordered(packages, lambda package: package.source.value, PACKAGE_ORDER),
        freshness=freshness,
    )
    identity = caller_identity(ask.asserted_identity)
    record = Recorder(engine.records).record(
        _record(ask, compiled, response, identity, moment, freshness)
    )
    return Answered(response=response, record=record, identity=identity)


def _packages(
    engine: Engine, ask: Ask, compiled: CompiledQuestion, execution: Execution
) -> tuple[AnswerPackage, ...]:
    """One package per selected source. Never merged, never de-duplicated (AD-10)."""
    built: list[AnswerPackage] = []
    for source in ask.sources:
        match source:
            case PackageSource.APPROVED:
                built.append(_approved(engine, ask, compiled, execution))
            case PackageSource.EXTERNAL:
                built.append(external_package(compiled, engine.messages, ask.lang))
    return tuple(built)


def _approved(
    engine: Engine, ask: Ask, compiled: CompiledQuestion, execution: Execution
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
    )


# ------------------------------------------------------------------------ the record


def _record(
    ask: Ask,
    compiled: CompiledQuestion,
    response: Response[AnswerPackage],
    identity: CallerIdentity,
    moment: datetime,
    freshness: Freshness,
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
        degradations=tuple(
            degradation
            for package in response.packages
            for degradation in package.degradations
        ),
        # Empty on every Epic 1 answer, because nothing in this epic calls a model. The
        # field is populated rather than omitted so an old answer can say it used none.
        prompts=(),
        elements=tuple(
            placed.element for package in response.packages for placed in package.elements
        ),
        data_as_of=None if freshness.refreshed_at is None else freshness.refreshed_at.isoformat(),
        conversation_id=response.conversation_id,
        turn=FIRST_TURN,
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


