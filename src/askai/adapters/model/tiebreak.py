"""The model rung: one call, over a closed candidate list, discarded on any doubt.

Purity: IO -- it holds a ``ModelPort`` and reads the published prompt.

This is the last rung of AD-25's ladder and it is reached **only** where stage 2 left a
genuine tie. Its input is the ``Disambiguation`` the deterministic ladder already
produced, which means the answer to *"what happens when the model is unavailable"* is
already computed and already correct before the call is made: the reader is asked which
indicator they meant. The model can improve that outcome and can never make it worse.

**Why this lives in ``adapters/model/`` and not in ``compile/resolve/``.** AD-9 says no
module outside ``adapters/`` knows the protocol, and NFR-5 is stronger than that for the
ladder: ``tests/test_resolve.py`` asserts that no module in ``compile/resolve/`` so much
as names ``ports.model``. Stages 1 and 2 do not run *despite* a missing model; there is
nothing in them to take away. So the tie-break is reached from outside the ladder, with
the ladder's own disambiguation and its closed candidate list as the whole of its input.

**The closed domain is the supplied ids, and it is closed twice.** ``guided_choice`` is
sent so the runtime's decoder cannot emit anything else, and the validator checks the
answer against the same tuple. AD-8's floor does not move because a decoder is
constrained: the text can still be truncated at the token budget, the server may not
honour the extension at all, and no grammar knows whether an id exists in this
catalogue. Constrain **and** check.

**Two decodings, one fallback, and no retry.** The first request constrains with
``guided_choice``. If the *server* would not take the request -- a runtime without the
vLLM extension answers 400, and a runtime that is down answers nothing -- exactly one
further request goes out constrained with plain ``response_format: {"type":
"json_object"}``, which every OpenAI-compatible server accepts. If instead the *model
answered* and the validator rejected what it said, nothing further is sent: that is the
``"retry loop that eventually accepts something"`` AD-8 forbids, and asking the reader is
the better answer anyway. The two requests share the rung's declared wall clock rather
than each getting it, so the fallback is in budget by construction.

**AD-22, by shape.** One function, no loop, no plan, no tool choice, no second turn. The
number of requests is a property of this module's source -- a first and a fallback, both
written out -- and not a counter in data that one increment would turn into a loop.

**Over-binding is visible in the data.** A tie broken here reports ``BoundBy.MODEL``, and
a tie *not* broken here reports nothing at all, so the share of answers the model bound
is a number an operator can read off the records rather than a thing to be argued about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from askai.adapters.model.prompts import VersionedPrompt, tie_break_prompt
from askai.compile.binding import BoundBy
from askai.compile.resolve.decide import Disambiguation, Resolution, Resolved
from askai.domain.degradation import Degradation
from askai.observability.degradations import (
    Absent,
    DegradationKind,
    Failed,
    Found,
    Outcome,
    degrade,
)
from askai.observability.record import PromptUse
from askai.ports.model import (
    Budget,
    CallSite,
    ChoiceDecoding,
    Decoding,
    JsonObjectDecoding,
    ModelCall,
    ModelPort,
    Validator,
)
from askai.rules import rules

__all__ = [
    "TieBreak",
    "TieBreakRule",
    "break_tie",
    "candidate_listing",
    "chosen_from",
    "maximum_candidates_listed",
    "tie_break_budget",
]

#: Where a degradation from this module says it happened, in the shape ``chat.py`` uses:
#: the module, then the call site. A rising rate then names *this rung* rather than
#: "the model".
_WHERE: Final = "adapters/model/tiebreak"

#: One request, and at most one decoding fallback. A constant rather than a rule clause,
#: and the rule file says why: a retry count in data is one increment away from being the
#: loop AD-8 and AD-22 forbid. It divides the rung's read budget so that both requests
#: together stay inside the wall clock the rule declares.
_REQUESTS: Final = 2

#: The one key the JSON form of an answer may carry. The prompt asks for a bare id or
#: ``{"detail_id": "..."}``; anything else the parser sees is not an answer.
_ANSWER_KEY: Final = "detail_id"


class TieBreakRule(StrEnum):
    """The rules this rung reads."""

    BUDGET = "R-MODEL-TIE-BREAK-BUDGET"


class BudgetClause(StrEnum):
    """The clauses ``R-MODEL-TIE-BREAK-BUDGET`` carries."""

    MAX_OUTPUT_TOKENS = "max_output_tokens"
    CONNECT_SECONDS = "connect_timeout_seconds"
    READ_SECONDS = "read_timeout_seconds"
    MAXIMUM_CANDIDATES = "maximum_candidates_listed"


class TieBreakError(RuntimeError):
    """A clause this rung needs is missing or is not the type it must be."""


@dataclass(frozen=True, slots=True)
class TieBreak:
    """What the model rung produced, and what it costs to say so.

    The three fields travel together because they are one statement. A resolution with no
    account of who bound it is the over-binding this story exists to make visible; a
    fallback with no degradation is the silent failure AD-15 exists to prevent; and an
    answer that used a prompt without recording which one is the untraceable card AD-29
    exists to prevent.
    """

    #: ``Resolved`` when the model chose a supplied id and the validator accepted it;
    #: otherwise the ``Disambiguation`` that came in, unchanged. There is no third
    #: outcome: this rung never invents a refusal and never narrows the candidate list.
    resolution: Resolution

    #: ``BoundBy.MODEL`` exactly when the model bound it, and ``None`` otherwise.
    bound_by: BoundBy | None

    #: Empty only when the model bound it on the first request. Every other path carries
    #: at least one counted degradation, because every other path asked the reader.
    degradations: tuple[Degradation, ...]

    #: ``prompt_id@version`` and hash, recorded whether or not the answer was believed --
    #: a discarded output is still an output this prompt produced (AD-29).
    prompt: PromptUse

    def __post_init__(self) -> None:
        if (self.bound_by is None) is isinstance(self.resolution, Resolved):
            raise ValueError(
                f"the model rung reports {type(self.resolution).__name__} bound by "
                f"{self.bound_by}; it binds and says so, or it asks and says nothing"
            )
        if self.bound_by is None and not self.degradations:
            raise ValueError(
                "the rung fell back to asking and counted nothing; AD-8 requires the "
                "fallback to carry a counted degradation, or a rising failure rate is "
                "indistinguishable from a quiet corpus"
            )


# ------------------------------------------------------------------------- the rule


def _count(clause: BudgetClause) -> int:
    value = rules().value(TieBreakRule.BUDGET.value, clause.value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TieBreakError(
            f"{TieBreakRule.BUDGET.value} clause `{clause.value}` is {type(value).__name__}, "
            "and the tie-break needs a whole number; the clause is read here and nowhere "
            "else, so the file is what changes"
        )
    if value < 1:
        raise TieBreakError(
            f"{TieBreakRule.BUDGET.value} clause `{clause.value}` is {value}; a budget of "
            "none is a call that fails before it is made"
        )
    return value


def maximum_candidates_listed() -> int:
    """How many candidates may be put to the model in one call.

    The served runtime's window is 16384 tokens for prompt *plus* completion and the
    candidate listing is the only part of this prompt that grows, so the cap is a
    property of the deployment rather than a preference. It is also already enforced a
    rung earlier -- a tie wider than ``maximum_offered`` is refused as too wide to name --
    which makes this the second lock on the same door rather than a new limit.
    """
    return _count(BudgetClause.MAXIMUM_CANDIDATES)


def tie_break_budget() -> Budget:
    """What **one request** of this rung may spend.

    The rule declares the budget for the *rung*; the read allowance is divided by the
    number of requests that can be made, so a first request and its one decoding fallback
    together stay inside the wall clock a reviewer signed off. Dividing rather than
    declaring a per-request figure keeps the reviewable number the one an operator cares
    about: how long a reader can be kept waiting.
    """
    return Budget(
        max_output_tokens=_count(BudgetClause.MAX_OUTPUT_TOKENS),
        connect_seconds=float(_count(BudgetClause.CONNECT_SECONDS)),
        read_seconds=_count(BudgetClause.READ_SECONDS) / _REQUESTS,
    )


# ------------------------------------------------------- the parser and the validator


def chosen_from(candidate_ids: tuple[str, ...]) -> Validator[str]:
    """A total parser and validator over *candidate_ids*, and nothing outside them.

    AD-8's two halves in one function, because they are one guarantee. The parser is
    total: it is handed whatever came back -- an empty string, half a JSON object cut off
    at the token budget, a paragraph of apology -- and answers rather than raising. The
    validator is closed: the parsed id must be one of the ids that were *supplied*, so a
    well-formed object naming an indicator the model invented is rejected exactly as
    firmly as unparseable text. That is the case JSON mode cannot catch and the case this
    exists for.

    Exported so a test can drive it over a corpus of bad outputs without a port, a
    transport or a model.
    """
    permitted = frozenset(candidate_ids)

    def validate(text: str) -> str | None:
        found = _parsed(text)
        if found is None or found not in permitted:
            return None
        return found

    return validate


def _parsed(text: str) -> str | None:
    """The candidate id *text* names, or ``None`` if it names none.

    Two shapes, because two decodings are used and a constrained decoder does not
    guarantee either: ``guided_choice`` yields a bare id, JSON mode yields an object. A
    bare id is not parsed as JSON and an object is not read as an id, so ``{"detail_id":
    "D1"}`` can never be mistaken for a detail whose id is that whole string.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if not stripped.startswith("{"):
        return stripped
    try:
        payload = json.loads(stripped)
    except ValueError:
        # Truncated at the token budget, or never JSON. Either way it is not an answer,
        # and repairing it would be the "partial edit" AD-28 rules out on the other rung.
        return None
    if not isinstance(payload, dict):
        return None
    found = payload.get(_ANSWER_KEY)
    return found.strip() if isinstance(found, str) and found.strip() else None


# -------------------------------------------------------------------------- the call


def candidate_listing(question: str, tied: Disambiguation) -> str:
    """The user half of the call: the question, and the closed list to choose from.

    The ids are given with the *surface that actually matched*, because that is the text
    the reader's words reached and the only thing that distinguishes two details whose
    indicator names are identical. Tab-separated and one per line rather than prose: the
    model is choosing from a list, and every token spent on framing is a token the
    16384-token window does not have for the list.
    """
    lines = [f"Question: {question}", "", "Candidates:"]
    lines += [f"{offered.detail_id}\t{offered.surface}" for offered in tied.candidates]
    return "\n".join(lines)


def break_tie(
    question: str,
    tied: Disambiguation,
    model: ModelPort,
    *,
    prompt: VersionedPrompt | None = None,
) -> TieBreak:
    """Ask the model which of *tied*'s candidates the reader meant -- or ask the reader.

    Total: this returns, it does not raise, for every failure of the runtime. The single
    exception is a missing or altered prompt, which is raised out of
    :func:`~askai.adapters.model.prompts.load_prompt` before any call is made, because a
    prompt nobody reviewed is a fact about this deployment rather than about the runtime
    (AD-29). A composition root that calls ``verify_prompts`` at startup never reaches
    that case at answer time.

    *prompt* is injectable so a test can drive a deliberately different instruction
    through the real path; production passes nothing and gets the published one.
    """
    published = tie_break_prompt() if prompt is None else prompt
    ids = tuple(offered.detail_id for offered in tied.candidates)

    unaskable = _unaskable(ids)
    if unaskable is not None:
        return _asked(tied, published, (unaskable,))

    first = model.complete(_call(published, question, tied, ids, ChoiceDecoding(ids)))
    chosen = _chosen(first)
    if chosen is not None:
        return _bound(tied, published, chosen, ())

    refused = _failures(first)
    if not _server_refused_the_request(refused):
        # The model answered and the validator rejected it. Nothing further is sent: a
        # second request with a looser constraint is the retry loop that eventually
        # accepts something (AD-8).
        return _asked(tied, published, refused)

    # Exactly one fallback, for a server that will not take the guided-decoding
    # extension. Plain JSON mode is the OpenAI-standard field, so a runtime that rejected
    # the first request has no protocol reason to reject this one -- and the validator
    # runs on it identically, because a well-formed object can still name an invented id.
    second = model.complete(_call(published, question, tied, ids, JsonObjectDecoding()))
    chosen = _chosen(second)
    if chosen is not None:
        return _bound(tied, published, chosen, refused)
    return _asked(tied, published, (*refused, *_failures(second)))


def _chosen(outcome: Outcome[str]) -> str | None:
    """The id the model chose and the validator accepted, or ``None`` if there is none."""
    match outcome:
        case Found(value=detail_id):
            return detail_id
        case Absent() | Failed():
            return None


def _failures(outcome: Outcome[str]) -> tuple[Degradation, ...]:
    """What *outcome* failed with, as counted degradations.

    ``Absent`` is documented by the port as unused on this rung. A port implementation
    that returned one anyway must not be read as a well-founded nothing -- that is the
    findings-23/128/150 confusion -- so it is converted into the failure it is.
    """
    match outcome:
        case Failed(degradations=degradations):
            return degradations
        case Absent(reason=reason):
            return (_unavailable(reason),)
        case Found():
            return ()


def _call(
    published: VersionedPrompt,
    question: str,
    tied: Disambiguation,
    ids: tuple[str, ...],
    decoding: Decoding,
) -> ModelCall[str]:
    """One complete request. Both attempts differ in exactly one field, and this is it."""
    return ModelCall(
        site=CallSite.CANDIDATE_DISCRIMINATION,
        instruction=published.text,
        input_text=candidate_listing(question, tied),
        validate=chosen_from(ids),
        budget=tie_break_budget(),
        decoding=decoding,
    )


def _unaskable(ids: tuple[str, ...]) -> Degradation | None:
    """Why this tie may not be put to a model at all, or ``None`` if it may.

    Checked before the call rather than after it, so a listing that cannot fit the window
    costs nothing and so ``ChoiceDecoding`` -- which refuses fewer than two options and
    refuses a repeated one -- is never constructed from a list that would raise. A
    ``Disambiguation`` from ``decide`` satisfies all three by construction; this is the
    guard for the day it is built somewhere else.
    """
    limit = maximum_candidates_listed()
    if len(ids) > limit:
        return _discarded(
            f"{len(ids)} candidates were tied and at most {limit} may be listed; the "
            "runtime's window is shared between prompt and completion, so the call was "
            "not made"
        )
    if len(ids) < _REQUESTS:
        return _discarded(
            f"{len(ids)} candidate(s) is not a tie; a closed choice needs at least two "
            "options, and one option is a constant rather than a question"
        )
    if len(set(ids)) != len(ids):
        return _discarded(
            "the tied candidates repeat a detail id; a closed choice lists each option "
            "once, and a repeated one is a list the decoder cannot be constrained to"
        )
    return None


def _bound(
    tied: Disambiguation,
    published: VersionedPrompt,
    detail_id: str,
    degradations: tuple[Degradation, ...],
) -> TieBreak:
    """The model chose, the validator accepted, and the choice is recorded as the model's.

    The ``Resolved`` is built from the ``Offered`` that carries the id rather than from
    the id alone, so the surface and the score the reader would have been shown are the
    surface and score the audit record carries. Nothing is re-derived here.
    """
    offered = next(entry for entry in tied.candidates if entry.detail_id == detail_id)
    return TieBreak(
        resolution=Resolved(
            detail_id=offered.detail_id,
            indicator_id=offered.indicator_id,
            score=offered.score,
            matched_surface=offered.surface,
            decided_by=tied.signals_that_spoke,
        ),
        bound_by=BoundBy.MODEL,
        degradations=degradations,
        prompt=published.use,
    )


def _asked(
    tied: Disambiguation, published: VersionedPrompt, degradations: tuple[Degradation, ...]
) -> TieBreak:
    """The declared fallback: the disambiguation the ladder already produced, unchanged.

    Unchanged is the load-bearing word. This rung does not narrow the list, reorder it, or
    convert it into a refusal on the strength of a failed call -- the reader is asked
    exactly the question they would have been asked had no model been configured at all.
    """
    return TieBreak(
        resolution=tied, bound_by=None, degradations=degradations, prompt=published.use
    )


def _server_refused_the_request(degradations: tuple[Degradation, ...]) -> bool:
    """Did the runtime decline the request, as opposed to the validator declining its output?

    The distinction decides whether the one fallback is made, so it is read off the closed
    taxonomy rather than off the text of a message: ``MODEL_UNAVAILABLE`` is *the request
    did not produce usable output at all* -- a 400 from a server without the guided
    decoding extension, a refused connection, a timeout -- and ``GUARD_DISCARD`` is *the
    model answered and was not believed*. Only the first is worth asking differently.
    """
    return any(
        degradation.kind == DegradationKind.MODEL_UNAVAILABLE.value
        for degradation in degradations
    )


def _unavailable(detail: str) -> Degradation:
    return degrade(
        DegradationKind.MODEL_UNAVAILABLE,
        f"{_WHERE}:{CallSite.CANDIDATE_DISCRIMINATION.value}",
        detail,
    )


def _discarded(detail: str) -> Degradation:
    return degrade(
        DegradationKind.GUARD_DISCARD,
        f"{_WHERE}:{CallSite.CANDIDATE_DISCRIMINATION.value}",
        detail,
    )
