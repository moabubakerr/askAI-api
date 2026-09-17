"""The answer record: one value, complete by construction, bounded by construction.

Purity: pure -- it builds a row, it does not write one.

AD-16 says what a record must contain: the ``QuerySpec``, the binding mechanism per
field, the row ids used, the rules that fired, the caller identity, the degradations and
the prompt version where one applies. FR-74's point is the *months later* part: a card
questioned by the Council is defended from this row or it is not defended at all.

Three properties are structural here rather than hoped for.

**A record cannot be half-built.** ``AnswerRecord`` is frozen, every field is required
that AD-16 requires, and ``__post_init__`` rejects a record whose bindings do not cover
every bindable ``QuerySpec`` field. The field list is *derived* from ``QuerySpec``, so a
field added to the spec makes every record incomplete until someone says how it was
bound -- which is the failure surfacing at the build rather than in an audit.

**The binding mechanism is checked against the field state.** AD-19 fixes the precedence
``named-in-question ▸ inherited-from-history ▸ rule default ▸ Unbound``. A field that is
``Unbound`` must be recorded as such and a field that is bound must name one of the three
positive mechanisms; the two cannot disagree, because a record that says "rule default"
about a field the spec left unbound is worse than no record.

**Size is bounded, and every reduction is recorded.** NFR-9's retention is only workable
if one record cannot grow with the size of the answer it describes. So: identifiers are
length-checked at construction, free text is truncated, lists are capped, and the whole
row is measured and shrunk until it fits ``MAX_RECORD_BYTES``. Nothing is dropped
silently -- each reduction appends an entry to ``truncated`` saying which field, how many
survived and how many did not, so a reader of the record can always tell a short list
from a shortened one. A record that quietly grew without limit would be the defect;
a record that shrank without saying so would be a worse one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from askai.domain.admission import SourceAdmission
from askai.domain.degradation import Degradation
from askai.domain.element import Element
from askai.domain.scope import DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Deferred,
    Exact,
    LastN,
    Latest,
    Measure,
    Operation,
    QuerySpec,
    Range,
    Unbound,
)
from askai.messages.lang import Lang
from askai.observability.identity import MAX_ID_CHARS, Anonymous, Asserted, CallerIdentity
from askai.ports.external_agent import ExternalOutcome
from askai.ports.record import RecordRow

__all__ = [
    "MAX_DEGRADATIONS",
    "MAX_ELEMENTS",
    "MAX_LIST_ITEMS",
    "MAX_RECORD_BYTES",
    "MAX_TEXT_CHARS",
    "SPEC_FIELDS",
    "AnswerRecord",
    "BindingMechanism",
    "ExternalCall",
    "FieldBinding",
    "PromptUse",
    "RecordError",
    "RecordTooLarge",
    "RuleFired",
    "row_size_bytes",
    "to_row",
]

type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]

#: The hard ceiling on one serialised record, counting every column. Chosen so that a
#: year of answering at any plausible rate is a file an operator can keep, and so that
#: the bound bites long before sqlite or a backup does. It is not a reader-affecting
#: constant -- truncation changes what an auditor sees in the record and never what the
#: reader is told -- so it lives here rather than in ``rules/``.
MAX_RECORD_BYTES: Final = 16_384

#: Caps applied before the ceiling is even measured, so the common case is one pass.
MAX_TEXT_CHARS: Final = 1_000
MAX_LIST_ITEMS: Final = 200
MAX_DEGRADATIONS: Final = 50
MAX_ELEMENTS: Final = 100

#: The floor the shrink loop will not truncate text below: a record whose every string
#: had been reduced to nothing would be within its bound and useless.
MIN_TEXT_CHARS: Final = 80

#: Appended to anything that was cut, so a truncated value never reads as a whole one.
TRUNCATION_SUFFIX: Final = "..."

#: The ``QuerySpec`` fields a binder owns, derived rather than listed -- see the module
#: docstring. ``today`` is an input to compilation and ``spec_version`` is the shape,
#: so neither is bound by AD-19's precedence and neither takes a mechanism.
SPEC_FIELDS: Final = tuple(
    field.name for field in fields(QuerySpec) if field.name not in {"today", "spec_version"}
)


class RecordError(ValueError):
    """A record that cannot be written as given."""


class RecordTooLarge(RecordError):
    """The row exceeds the ceiling even with everything reducible reduced.

    Unreachable while identifiers are length-checked at construction, which is why that
    check is not a nicety. Raised rather than written, because a record over its bound
    breaks the one promise -- workable retention -- the bound exists to make.
    """


class BindingMechanism(StrEnum):
    """How a spec field got its value. AD-19's precedence, in precedence order."""

    NAMED_IN_QUESTION = "named-in-question"
    INHERITED_FROM_HISTORY = "inherited-from-history"
    RULE_DEFAULT = "rule-default"
    UNBOUND = "unbound"


@dataclass(frozen=True, slots=True)
class FieldBinding:
    """One spec field, and the mechanism that bound it.

    ``note`` is where a ``Deferred`` field records what ``execute/`` resolved it to --
    *"latest"* becoming ``2025-Q2`` is the single most-asked question of an old answer,
    and the spec alone cannot answer it.
    """

    field: str
    mechanism: BindingMechanism
    note: str = ""

    def __post_init__(self) -> None:
        if self.field not in SPEC_FIELDS:
            raise RecordError(
                f"{self.field!r} is not a bindable QuerySpec field; expected one of "
                f"{sorted(SPEC_FIELDS)}"
            )


@dataclass(frozen=True, slots=True)
class RuleFired:
    """One rule that took part in the answer, and what it decided."""

    rule_id: str
    outcome: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise RecordError("a fired rule must name its rule id")


@dataclass(frozen=True, slots=True)
class PromptUse:
    """``prompt_id@version`` and its hash -- AD-29's traceability, per answer.

    Empty on every Epic 1 answer, because nothing in that epic calls a model. The field
    exists anyway: "where one applies" is a property of the answer, and a record shape
    that gained a column the first time a model was called would leave every earlier
    answer unable to say it used none.
    """

    prompt_id: str
    version: str
    prompt_hash: str

    def __post_init__(self) -> None:
        for name, value in (
            ("prompt_id", self.prompt_id),
            ("version", self.version),
            ("prompt_hash", self.prompt_hash),
        ):
            if not value.strip():
                raise RecordError(f"a recorded prompt needs its {name}; AD-29 traces on all three")


@dataclass(frozen=True, slots=True)
class ExternalCall:
    """The external call this answer made: what went out, and what came back (Story 9.9).

    **What the engine sent is recorded, and it is two strings** (NFR-4a). ``sent_question``
    is the reader's own question and ``sent_context`` is the deterministic context line
    the engine composed; together they are the whole outbound payload, so an auditor
    months later can reconstruct exactly what a third party was told. There is no field
    here for a figure, a row id or a spec, which is the same absence ``ExternalRequest``
    has -- *"never approved data"* is a property of the shape rather than a rule the
    recorder has to keep.

    **The outcome is one of four** and it is the port's own closed enum, not a second
    spelling of it. A record that said "failed" could not tell a dead platform from a slow
    one from a budget the engine chose to cut short, and those are three different
    conversations with three different people.

    ``orphaned_job`` is how the accepted cost stops being an unexamined one: a job the
    engine abandoned client-side may still be running, and the id of it is written down on
    the answer that abandoned it. It is ``None`` when the budget expired before the
    adapter ever handed a job id back -- an orphan whose name the engine never learned,
    which is the worst kind and is exactly why ``ABANDONED`` is itself a recorded outcome
    rather than a field that has to be populated to count. Counting these over a window is
    how anyone finds out whether the budget is too tight.

    Every string here is bounded by the same reduction the rest of the row is (NFR-9) --
    see ``_external_payload`` -- so a long question or a chatty platform cannot push one
    record past Story 1.16's ceiling.
    """

    outcome: ExternalOutcome
    sent_question: str
    sent_context: str
    job_id: str | None = None
    orphaned_job: str | None = None
    #: Wall-clock seconds the call took. Recorded on every answer so Combined latency can
    #: be measured against ``[ASSUMPTION A4]``'s ~2x baseline instead of believed (NFR-3).
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.sent_question.strip():
            raise RecordError(
                "an external call records the question it sent; a blank one would make "
                "the outbound payload unreconstructable, which is the whole of NFR-4a"
            )
        if not self.sent_context.strip():
            raise RecordError("an external call records the context line it sent")
        if self.orphaned_job is not None and self.outcome is not ExternalOutcome.ABANDONED:
            raise RecordError(
                f"a {self.outcome.value} call naming an orphaned job; a job is orphaned by "
                "being abandoned, and recording one against any other outcome would "
                "inflate the count the budget is tuned against"
            )
        if self.elapsed_seconds < 0.0:
            raise RecordError("elapsed time is measured forwards")


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """Everything AD-16 requires of one answer, as one frozen value.

    Built from the finished package and never amended: there is no setter, no
    ``add_degradation`` and no ``merge``. The recorder hands it to ``RecordPort`` once.
    """

    record_id: str
    recorded_at: datetime
    identity: CallerIdentity
    language: Lang
    question: str
    spec: QuerySpec
    bindings: tuple[FieldBinding, ...]
    row_ids: tuple[str, ...] = ()
    rules_fired: tuple[RuleFired, ...] = ()
    degradations: tuple[Degradation, ...] = ()
    prompts: tuple[PromptUse, ...] = ()
    elements: tuple[Element, ...] = ()
    data_as_of: str | None = None
    conversation_id: str | None = None
    turn: int | None = None
    #: The agent the reader selected, in the reader's own spelling (FR-90, Story 9.9).
    #: The admission's value, not a derived label: ``approved+external`` on the row says
    #: what was asked for, which is the question an audit starts from and is not
    #: recoverable from the packages -- an admission that admitted the external agent and
    #: got nothing looks, in the packages alone, like one that never asked.
    agent: str = SourceAdmission.APPROVED_ONLY.value
    #: The external call, or ``None`` when the admission did not admit one. ``None`` means
    #: *no call was made*, which is a different fact from a call that failed, and the two
    #: are kept apart here for the reason ``Absent`` and ``Failed`` are kept apart.
    external_call: ExternalCall | None = None

    def __post_init__(self) -> None:
        self._check_identifiers()
        self._check_time()
        self._check_bindings()
        self._check_conversation()
        self._check_agent()
        if not self.question.strip():
            raise RecordError("a record needs the question it answered")

    # -- invariants ---------------------------------------------------------------

    def _check_identifiers(self) -> None:
        """Every id the record stores is length-checked here, and only here.

        This is what makes the size bound total: text and lists are reducible, an
        identifier is not, so the only way a row can exceed its ceiling after reduction
        is an id nobody bounded.
        """
        for name, value in (
            ("record_id", self.record_id),
            ("conversation_id", self.conversation_id),
            ("data_as_of", self.data_as_of),
        ):
            if value is None:
                continue
            if not value.strip():
                raise RecordError(f"{name} is blank; omit it rather than storing an empty string")
            if len(value) > MAX_ID_CHARS:
                raise RecordError(
                    f"{name} is {len(value)} characters, the record stores at most "
                    f"{MAX_ID_CHARS}; an unbounded identifier defeats the size bound"
                )

    def _check_time(self) -> None:
        if self.recorded_at.tzinfo is None:
            raise RecordError(
                "recorded_at must carry a timezone; a naive timestamp on an audit row "
                "is unanswerable the moment anyone asks which clock it is in"
            )
        if self.recorded_at.utcoffset() != UTC.utcoffset(None):
            raise RecordError("recorded_at must be UTC; the spine stores UTC internally")

    def _check_bindings(self) -> None:
        recorded = [binding.field for binding in self.bindings]
        if sorted(recorded) != sorted(SPEC_FIELDS):
            raise RecordError(
                f"the record binds {sorted(recorded)}, the spec has {sorted(SPEC_FIELDS)}; "
                "AD-16 records the binding mechanism per field, so a field with no "
                "mechanism -- or one named twice -- is an incomplete record"
            )
        for binding in self.bindings:
            unbound_state = isinstance(getattr(self.spec, binding.field), Unbound)
            unbound_mechanism = binding.mechanism is BindingMechanism.UNBOUND
            if unbound_state != unbound_mechanism:
                raise RecordError(
                    f"{binding.field} is recorded as {binding.mechanism.value} but the "
                    f"spec field is {type(getattr(self.spec, binding.field)).__name__}; "
                    "the record may not disagree with the spec it describes"
                )

    def _check_conversation(self) -> None:
        if (self.conversation_id is None) != (self.turn is None):
            raise RecordError(
                "conversation_id and turn are recorded together or not at all; a turn "
                "number with no conversation cannot be ordered against anything"
            )
        if self.turn is not None and self.turn < 1:
            raise RecordError(f"turn numbering starts at 1, got {self.turn}")

    def _check_agent(self) -> None:
        """The recorded agent is one of the three admissions, and the call agrees with it.

        Two halves, both of them the same argument. A free-text agent would make a count
        of agents a count of typos -- ``DegradationKind``'s reason, at a different grain.
        And a record claiming an external call under an approved-only admission would be a
        record that disagrees with the request it describes, which is the failure mode
        ``_check_bindings`` exists to prevent one field at a time.
        """
        try:
            admission = SourceAdmission(self.agent)
        except ValueError:
            raise RecordError(
                f"{self.agent!r} is not one of the three admissions; the record stores "
                "the reader's selection in the reader's own spelling, and a value outside "
                "the closed set could only have come from a request that was never served"
            ) from None
        if self.external_call is not None and admission is SourceAdmission.APPROVED_ONLY:
            raise RecordError(
                "an external call recorded under the approved-only admission; the engine "
                "never reaches an external service for an answer that did not admit one "
                "(FR-79), so a record saying it did is a record that is wrong"
            )


# ------------------------------------------------------------------- the size bound


@dataclass(frozen=True, slots=True)
class _Budget:
    """How much of each reducible part the row may keep on this attempt."""

    items: int
    degradations: int
    elements: int
    text: int

    def halved(self) -> _Budget:
        return _Budget(
            items=self.items // 2,
            degradations=self.degradations // 2,
            elements=self.elements // 2,
            text=max(MIN_TEXT_CHARS, self.text // 2),
        )

    def exhausted(self) -> bool:
        return (
            self.items == 0
            and self.degradations == 0
            and self.elements == 0
            and self.text == MIN_TEXT_CHARS
        )


def row_size_bytes(row: RecordRow) -> int:
    """The serialised size of a whole row, columns included.

    Measured over every column rather than over the JSON payloads alone: the bound is a
    promise about what a record costs to keep, and the question, the ids and the
    timestamps are stored too.
    """
    return len(json.dumps(_row_payload(row), ensure_ascii=False).encode("utf-8"))


def to_row(record: AnswerRecord) -> RecordRow:
    """Flatten *record* into the row the record store writes, within the size bound.

    One pass in the ordinary case. An oversized answer -- a thousand row ids, a long
    question, a degradation with a stack of detail -- is reduced by successive halving
    until it fits, with every reduction recorded in the row's ``truncated`` list.
    """
    budget = _Budget(
        items=MAX_LIST_ITEMS,
        degradations=MAX_DEGRADATIONS,
        elements=MAX_ELEMENTS,
        text=MAX_TEXT_CHARS,
    )
    while True:
        row = _row_at(record, budget)
        if row_size_bytes(row) <= MAX_RECORD_BYTES:
            return row
        if budget.exhausted():
            raise RecordTooLarge(
                f"the record for {record.record_id} is over {MAX_RECORD_BYTES} bytes "
                "with every reducible part reduced; an identifier is unbounded"
            )
        budget = budget.halved()


def _row_at(record: AnswerRecord, budget: _Budget) -> RecordRow:
    trimmed: list[JsonValue] = []
    question = _text(record.question, budget.text, "question", trimmed)
    spec_json = json.dumps(
        _spec_payload(record, budget, trimmed), ensure_ascii=False, sort_keys=True
    )
    answer_json = json.dumps(
        _evidence_payload(record, budget, trimmed), ensure_ascii=False, sort_keys=True
    )
    asserted = isinstance(record.identity, Asserted)
    return RecordRow(
        record_id=record.record_id,
        recorded_at=record.recorded_at.isoformat(),
        caller_id=record.identity.caller_id if isinstance(record.identity, Asserted) else None,
        identity_asserted=asserted,
        language=record.language.value,
        question=question,
        spec_version=record.spec.spec_version,
        spec_json=spec_json,
        answer_json=answer_json,
        data_as_of=record.data_as_of,
        conversation_id=record.conversation_id,
        turn=record.turn,
    )


def _row_payload(row: RecordRow) -> dict[str, JsonValue]:
    return {
        "record_id": row.record_id,
        "recorded_at": row.recorded_at,
        "caller_id": row.caller_id,
        "identity_asserted": row.identity_asserted,
        "language": row.language,
        "question": row.question,
        "spec_version": row.spec_version,
        "spec_json": row.spec_json,
        "answer_json": row.answer_json,
        "data_as_of": row.data_as_of,
        "conversation_id": row.conversation_id,
        "turn": row.turn,
    }


# --------------------------------------------------------------------- the payloads


def _spec_payload(record: AnswerRecord, budget: _Budget, trimmed: list[JsonValue]) -> JsonValue:
    """The spec as served, each field carrying the mechanism that bound it."""
    mechanisms = {binding.field: binding for binding in record.bindings}
    payload: dict[str, JsonValue] = {
        "spec_version": record.spec.spec_version,
        "today": record.spec.today.isoformat(),
    }
    for name in SPEC_FIELDS:
        binding = mechanisms[name]
        field: dict[str, JsonValue] = {
            "binding": binding.mechanism.value,
            "state": _state_payload(getattr(record.spec, name), budget, trimmed, name),
        }
        if binding.note:
            field["note"] = _text(binding.note, budget.text, f"binding.{name}", trimmed)
        payload[name] = field
    return payload


def _state_payload(
    state: object, budget: _Budget, trimmed: list[JsonValue], field: str
) -> JsonValue:
    match state:
        case Bound(value=value):
            return {"bound": _value_payload(value, budget, trimmed, field)}
        case Deferred(request=request):
            return {"deferred": _value_payload(request, budget, trimmed, field)}
        case Unbound(reason=reason):
            return {"unbound": _text(reason, budget.text, f"{field}.reason", trimmed)}
        case _:
            raise RecordError(
                f"{field} holds {type(state).__name__}, which is not a field state; "
                "a record cannot describe a spec shape it does not recognise"
            )


def _value_payload(
    value: object, budget: _Budget, trimmed: list[JsonValue], field: str
) -> JsonValue:
    """Serialise one bound value. Exhaustive: an unknown shape raises rather than
    reaching the record as ``repr`` output nobody can parse later."""
    match value:
        # StrEnum members are `str` instances, so these come first or they never match.
        case Measure() | Operation():
            return value.value
        case str():
            return _text(value, budget.text, field, trimmed)
        case Exact(period=period):
            return {"exact": period.value}
        case Range(start=start, end=end):
            return {"range": {"start": start.value, "end": end.value}}
        case Latest():
            return {"latest": True}
        case LastN(n=count, grain=grain):
            return {"last_n": {"n": count, "grain": grain.value}}
        case DeclaredBenchmarks():
            return {"declared_benchmarks": True}
        # ``National`` has no field to put a country in (AD-5), so it serialises to a
        # marker; ``Named`` carries a list a caller sized, which is exactly the kind of
        # unbounded input the ceiling exists for and is capped like any other list.
        case National():
            return {"national": True}
        case Named(countries=countries):
            kept, dropped = _capped(sorted(countries), budget.items, f"{field}.countries", trimmed)
            return {"named": {"countries": list(kept), "dropped": dropped}}
        case _:
            raise RecordError(
                f"{field} holds {type(value).__name__}, which the record has not been "
                "told how to serialise; a spec value reaching the record as repr output "
                "is unreadable by the audit it exists for"
            )


def _evidence_payload(
    record: AnswerRecord, budget: _Budget, trimmed: list[JsonValue]
) -> JsonValue:
    """Everything the spec does not say: what was read, what fired, what went wrong."""
    row_ids, _ = _capped(list(record.row_ids), budget.items, "row_ids", trimmed)
    rules, _ = _capped(list(record.rules_fired), budget.items, "rules_fired", trimmed)
    degradations, _ = _capped(
        list(record.degradations), budget.degradations, "degradations", trimmed
    )
    elements, _ = _capped(list(record.elements), budget.elements, "elements", trimmed)
    payload: dict[str, JsonValue] = {
        "identity": _identity_payload(record.identity, budget, trimmed),
        "row_ids": [_text(row_id, budget.text, "row_id", trimmed) for row_id in row_ids],
        "row_id_count": len(record.row_ids),
        "rules_fired": [
            {
                "rule_id": rule.rule_id,
                "outcome": _text(rule.outcome, budget.text, "rule.outcome", trimmed),
            }
            for rule in rules
        ],
        "degradations": [
            {
                "kind": degradation.kind,
                "where": degradation.where,
                "detail": _text(degradation.detail, budget.text, "degradation.detail", trimmed),
            }
            for degradation in degradations
        ],
        "degradation_count": len(record.degradations),
        "prompts": [
            {"prompt_id": prompt.prompt_id, "version": prompt.version, "hash": prompt.prompt_hash}
            for prompt in record.prompts
        ],
        # Class and provenance, never content: the figures are reconstructible from the
        # row ids, and copying the answer's prose in would make the record grow with it.
        "elements": [
            {
                "class": element.element_class.value,
                "source_ref": _text(element.source_ref, budget.text, "source_ref", trimmed),
            }
            for element in elements
        ],
        "element_count": len(record.elements),
        "data_as_of": record.data_as_of,
        # FR-90: which agent the reader selected, and what the external call did. Both on
        # the one record AD-16 allows, never on a second row written from a second place.
        "agent": record.agent,
        "external_call": _external_payload(record.external_call, budget, trimmed),
    }
    if trimmed:
        payload["truncated"] = list(trimmed)
    return payload


def _external_payload(
    call: ExternalCall | None, budget: _Budget, trimmed: list[JsonValue]
) -> JsonValue:
    """The external call, or ``null`` for an answer that never made one.

    Both outbound strings go through ``_text``, so the row a chatty question produces is
    reduced like every other and the NFR-9 ceiling holds whatever the reader typed. The
    prose that came *back* is deliberately absent: the record stores what was sent and
    what the call did, and copying a third party's answer in would make one audit row grow
    with the length of somebody else's essay.
    """
    if call is None:
        return None
    return {
        "outcome": call.outcome.value,
        "sent": {
            "question": _text(call.sent_question, budget.text, "external.question", trimmed),
            "context": _text(call.sent_context, budget.text, "external.context", trimmed),
        },
        "job_id": call.job_id,
        "orphaned_job": call.orphaned_job,
        # Whole milliseconds: the record's JSON holds no float anywhere, and a latency
        # measured to the microsecond would be reporting precision the clock does not
        # have. This is the number ``[ASSUMPTION A4]`` is tested against.
        "elapsed_ms": round(call.elapsed_seconds * 1000),
    }


def _identity_payload(
    identity: CallerIdentity, budget: _Budget, trimmed: list[JsonValue]
) -> JsonValue:
    """AD-24's negative case, written down rather than left as a NULL to interpret."""
    match identity:
        case Asserted(caller_id=caller_id):
            return {"asserted": True, "caller_id": caller_id}
        case Anonymous(reason=reason):
            return {
                "asserted": False,
                "anonymous": True,
                "reason": _text(reason, budget.text, "identity.reason", trimmed),
            }
        case _:
            raise RecordError(f"{type(identity).__name__} is not a caller identity")


# ------------------------------------------------------------------ the reductions


def _text(value: str, limit: int, field: str, trimmed: list[JsonValue]) -> str:
    """Truncate *value* to *limit* characters, recording the cut where it is visible."""
    if len(value) <= limit:
        return value
    trimmed.append({"field": field, "kept": limit, "dropped": len(value) - limit})
    return value[:limit] + TRUNCATION_SUFFIX


def _capped[T](
    values: list[T], limit: int, field: str, trimmed: list[JsonValue]
) -> tuple[list[T], int]:
    """Keep the first *limit* of *values*, recording how many did not survive.

    The first, not a sample: row ids and fired rules are produced in the order the
    answer used them, so the head is the part a reconstruction starts from.
    """
    if len(values) <= limit:
        return values, 0
    dropped = len(values) - limit
    trimmed.append({"field": field, "kept": limit, "dropped": dropped})
    return values[:limit], dropped
