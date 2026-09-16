"""``ModelPort`` -- one single-shot, budgeted, validated model call, and nothing more.

Purity: declarations only.

AD-9 gives the engine's own model calls their own port, separate from
``ExternalAgentPort``, and says no module outside ``adapters/`` knows the protocol.
AD-22 says what may be asked of it: **four call sites**, each *"single-shot, budgeted,
validated against a closed domain, and discardable"*, and *"no component may loop, plan,
re-plan, call a tool of its own choosing, or decide what to do next."*

This port is shaped so that most of that is unrepresentable rather than forbidden:

**Single-shot.** One instruction and one input, both plain strings. There is no message
list, so there is no conversation to continue; there is no ``stream`` flag, so there is
nothing to consume incrementally; there are no tool definitions, so the model has
nothing to call. A caller wanting a second turn has to write a second call, which a
reviewer sees.

**Bounded to four sites.** ``CallSite`` is closed for the reason ``DegradationKind`` is.
A fifth model call cannot be made without adding a member here, where it is reviewed
against AD-22 rather than argued about at the call site.

**Budgeted.** ``Budget`` is a required field, not a default. The runtime's window is
shared between prompt and completion, so the caller states its share explicitly.

**Validated, always.** ``ModelCall.validate`` is a required field too, so there is no
way to make a call without supplying the validator AD-8 puts on every one of them:
*"the validator runs on every call regardless, because one that only runs when the model
misbehaves is one nobody has tested."* It returns ``None`` to reject, and the adapter
turns a rejection into a counted degradation rather than into a retry.

**Constrained, additionally.** ``Decoding`` describes the constraint the runtime applies
while generating -- vLLM's ``guided_json``, ``guided_choice``, ``guided_regex``, or plain
JSON mode. It is an *optional tightening of the parse*, never a replacement for the
validator: a constrained decoder still returns text, and a schema-valid object may still
name an indicator id that does not exist. Constrain **and** check.

**Discardable.** The result is an ``Outcome``, so a caller must handle ``Failed``
separately from a value -- ``mypy --strict`` refuses an inexhaustive match -- and the
deterministic answer stands whatever the model did.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from askai.observability.degradations import Outcome

__all__ = [
    "Budget",
    "CallSite",
    "ChoiceDecoding",
    "Decoding",
    "JsonObjectDecoding",
    "JsonSchemaDecoding",
    "ModelCall",
    "ModelPort",
    "RegexDecoding",
    "Validator",
]


class CallSite(StrEnum):
    """The four places AD-22 permits a model call, and nowhere else.

    The member is carried on the call and reported on the degradation, so a rising
    failure rate has an address -- "the model is unavailable" is not actionable, "the
    model is unavailable at operation classification" is.
    """

    #: Choosing between catalogue candidates the deterministic resolver left tied
    #: (Story 2.6). The closed domain is the candidate list handed to the model.
    CANDIDATE_DISCRIMINATION = "candidate_discrimination"

    #: Which operation the question asks for. The closed domain is the operation enum.
    OPERATION_CLASSIFICATION = "operation_classification"

    #: Whether a question is several questions. The closed domain is a sub-question set.
    MULTI_PART_DETECTION = "multi_part_detection"

    #: Prose over an answer already assembled from approved figures (Epic 8). The guard
    #: accepts or discards it wholesale; the structured answer never depends on it.
    NARRATION = "narration"


@dataclass(frozen=True, slots=True)
class Budget:
    """What one call may spend: output tokens, and wall-clock on each half of the wait.

    A value rather than adapter configuration, because the four sites do not want the
    same budget -- narration is long and can wait, discrimination is a handful of tokens
    and must not. The adapter additionally refuses a call whose prompt plus
    ``max_output_tokens`` cannot fit the runtime's whole window.
    """

    max_output_tokens: int
    connect_seconds: float
    read_seconds: float

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1:
            raise ValueError("a budget of no output tokens is a call with nothing to return")
        if self.connect_seconds <= 0.0 or self.read_seconds <= 0.0:
            raise ValueError(
                "a non-positive timeout is not 'wait forever'; it is a call that fails "
                "before it is made"
            )


@dataclass(frozen=True, slots=True)
class JsonObjectDecoding:
    """Syntactic JSON, nothing more -- OpenAI's ``response_format: json_object``.

    AD-8 ratifies it and immediately limits it: *"``json_object`` guarantees syntactic
    validity, not shape."* Use it where no schema is worth writing; the validator is
    still the thing that decides.
    """


@dataclass(frozen=True, slots=True)
class JsonSchemaDecoding:
    """Decoding constrained to a JSON schema -- vLLM's ``guided_json``.

    ``schema`` is a JSON Schema document as a plain mapping. It tightens the parse so
    far fewer outputs need discarding; it does not make the output true, because a
    schema cannot say whether an id exists in the catalogue.
    """

    schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ChoiceDecoding:
    """Decoding constrained to one of a fixed set of strings -- vLLM's ``guided_choice``.

    The natural fit for operation classification: the closed domain is literally the
    enum's members, so the decoder cannot emit a fifth one.
    """

    choices: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.choices) < 2:
            raise ValueError(
                "a choice constraint with fewer than two options is a constant; ask for "
                "it in the prompt or do not make the call"
            )
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("a choice constraint lists each option once")


@dataclass(frozen=True, slots=True)
class RegexDecoding:
    """Decoding constrained to a pattern -- vLLM's ``guided_regex``."""

    pattern: str

    def __post_init__(self) -> None:
        if not self.pattern.strip():
            raise ValueError("an empty pattern constrains nothing")


type Decoding = JsonObjectDecoding | JsonSchemaDecoding | ChoiceDecoding | RegexDecoding
"""How the runtime is asked to constrain generation. ``None`` at the call site means
free text -- which is only ever narration, where the guard is the whole contract."""


type Validator[T] = Callable[[str], T | None]
"""Text in, a checked value out, or ``None`` for *reject this output*.

Total by contract: it is handed whatever the model produced, including an empty string,
and it answers rather than raising. A validator that raised would push a bare ``except``
into the caller, which is the shape AD-15 forbids outside an adapter boundary.
"""


@dataclass(frozen=True, slots=True)
class ModelCall[T]:
    """One complete request: what to ask, how to constrain it, what it may cost, and
    how its answer is checked before anyone is allowed to believe it.

    Generic in the validated type, so the port hands back the caller's own value -- an
    enum member, a catalogue id, a sub-question tuple -- and never raw model text. That
    is AD-8's *"a total parser converts to a candidate value, which a validator checks
    against a closed domain"* expressed as a signature: there is no way to receive the
    text without having declared what would make it acceptable.
    """

    site: CallSite
    instruction: str
    input_text: str
    validate: Validator[T]
    budget: Budget
    decoding: Decoding | None = None

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError(
                "a model call states its instruction; an unlabelled prompt is one nobody "
                "can review against the closed domain it is meant to select from"
            )


@runtime_checkable
class ModelPort(Protocol):
    """The engine's own model runtime, as every caller outside ``adapters/`` sees it.

    One method. There is no ``stream``, no ``chat``, no ``embed``, no ``health`` --
    a port with more verbs is a port a caller can build a loop out of.
    """

    def complete[T](self, call: ModelCall[T]) -> Outcome[T]:
        """Make *call* once, and return the validated value or a typed failure.

        Total by contract: an implementation raises nothing. Every foreign failure --
        a refused connection, a timeout, a non-200, a body that is not the shape the
        API promises, an output the validator rejected -- comes back as ``Failed``
        carrying at least one ``Degradation``, converted at the adapter boundary where
        AD-15 permits broad handling.

        ``Absent`` is part of ``Outcome`` and is not used here: a model that answered
        with something the validator rejected is a failure, not a well-founded nothing,
        and collapsing the two is exactly the findings-23/128/150 confusion.

        Single-shot: an implementation does not retry. AD-8 rules out *"a retry loop
        that eventually accepts something"*, and a retry inside the adapter is that loop
        with the budget spent twice.
        """
        ...
