"""``ExternalAgentPort`` -- submit a job, poll it, take prose, on its own budget.

Purity: declarations only.

AD-9 gives the external agent **its own port**, separate from ``ModelPort``, and the
separation is not tidiness. The two runtimes differ in every way that matters to a
caller: the engine's own model is a synchronous completion inside the estate, answering
in one round trip against a window it shares with the prompt; the external agent is a
third-party *platform* reached by submitting a job and polling for it, answering in
**prose** the engine may not parse into figures. A single port would have to admit both
shapes, and the first caller to hold it would be free to treat the third party's text as
though it had been validated against a closed domain.

**Its own budget, and the budget is on the request.** ``ExternalBudget`` travels with the
call rather than living in the adapter's settings, for one reason: NFR-10 requires the
*caller* to abandon the wait client-side, and a caller that cannot see the deadline
cannot enforce one. One value, read by the adapter for its transport timeouts and its
poll loop, and read by the caller for the moment it stops waiting -- so the two can never
disagree about when the call is over.

**Nothing here can delay the approved answer.** The port is a single total function. It
does not raise, it does not retry past its deadline, and it has no method a caller could
block on indefinitely. Every failure -- a refused connection, a job that never leaves the
queue, a platform that answers 200 with a login page, a budget that ran out -- comes back
as an ``ExternalResult`` carrying a typed outcome and at least one ``Degradation``. The
approved answer is composed on its own path and is never waiting on this one.

**Abandonment is a recorded cost, not a silence.** Spine open question 2 asks whether the
platform supports cancellation or only client-side abandonment. The port answers it the
honest way: the result carries ``orphaned_job``, the id of a job the engine stopped
waiting for and could not confirm cancelled. An orphaned job is an accepted cost of
NFR-10 -- the alternative is waiting, which is the thing NFR-10 forbids -- but it is an
*examined* one, because every abandonment names the job it left running.

**Elapsed time is returned, always.** ``[ASSUMPTION A4]`` puts Combined latency at roughly
twice single-agent and NFR-3 depends on it. An assumption nobody measures is a belief, so
the port makes the measurement a field of every result rather than something a caller
might remember to time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from askai.domain.degradation import Degradation

__all__ = [
    "DEFAULT_EXTERNAL_BUDGET",
    "ExternalAgentPort",
    "ExternalBudget",
    "ExternalOutcome",
    "ExternalRequest",
    "ExternalResult",
]


class ExternalOutcome(StrEnum):
    """What the external call did. Closed, and exactly the four Story 9.9 records.

    Four members rather than a boolean, because the operational responses differ and a
    record that could not tell them apart would be unable to answer the only question
    worth asking of a run of them: *is the third party down, or is it slow, or are we
    abandoning it too early?* A rising ``ABANDONED`` share is a budget that is too tight;
    a rising ``UNAVAILABLE`` share is a platform that is down; they are not the same
    ticket and they do not go to the same team.
    """

    #: The platform returned prose within the budget. The only outcome that carries text.
    ANSWERED = "success"

    #: A transport-level timeout: the connection or a single poll exceeded its slice.
    TIMED_OUT = "timeout"

    #: The platform could not be reached, refused the job, or answered something that is
    #: not a job at all. Distinct from a timeout: one is a dead dependency, the other is
    #: a slow one, and telling them apart is the whole value of a closed set here.
    UNAVAILABLE = "unavailable"

    #: The whole budget expired with a job still in flight, and the engine stopped
    #: waiting. The job may still be running on the platform; ``orphaned_job`` names it.
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ExternalBudget:
    """What one external call may spend, in wall-clock seconds.

    ``total_seconds`` is the one that matters and the others are subdivisions of it: the
    caller abandons at ``total_seconds`` whatever the adapter is doing, so a per-request
    timeout larger than the total would be a promise the caller does not keep.
    """

    total_seconds: float
    connect_seconds: float
    read_seconds: float
    poll_interval_seconds: float

    def __post_init__(self) -> None:
        for name, value in (
            ("total_seconds", self.total_seconds),
            ("connect_seconds", self.connect_seconds),
            ("read_seconds", self.read_seconds),
            ("poll_interval_seconds", self.poll_interval_seconds),
        ):
            if value <= 0.0:
                raise ValueError(
                    f"{name} is {value}; a non-positive budget is not 'wait forever', it "
                    "is a call that fails before it is made"
                )
        if self.connect_seconds > self.total_seconds or self.read_seconds > self.total_seconds:
            raise ValueError(
                f"a slice of the budget ({self.connect_seconds}s connect, "
                f"{self.read_seconds}s read) exceeds the whole of it "
                f"({self.total_seconds}s); the caller abandons at the total, so a longer "
                "slice is a timeout that can never be reached"
            )


#: The budget an engine uses when a deployment states none. Deliberately short. NFR-10
#: says a slow third party may not delay the approved answer, and the approved answer is
#: composed from a local file in milliseconds -- so the external half is given enough
#: room to be useful and no more. It is an operational dial, not a reader-affecting
#: constant: changing it changes how long the engine waits, never what it says.
DEFAULT_EXTERNAL_BUDGET = ExternalBudget(
    total_seconds=20.0,
    connect_seconds=2.0,
    read_seconds=10.0,
    poll_interval_seconds=0.5,
)


@dataclass(frozen=True, slots=True)
class ExternalRequest:
    """Everything the engine sends outward, and it is two strings and a budget.

    **NFR-4a: what goes out is explicit, minimal, and never approved data.** The type
    carries no figure, no row id, no ``QuerySpec``, no element and no package -- so there
    is no field an approved value could travel in, and "we do not send the published
    layer to a third party" is a statement about the shape rather than a rule a call site
    has to keep remembering. What is left is the reader's own question, which they wrote,
    and a deterministic context line the caller composes from the request alone.

    ``context`` is deterministic on purpose (AD-17): the same request composes the same
    line on every run, so the recorded outbound payload can be reproduced months later
    and compared against what the record says was sent.
    """

    question: str
    context: str
    budget: ExternalBudget = DEFAULT_EXTERNAL_BUDGET

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("an external call carries the reader's question; an empty one asks "
                             "the third party nothing")
        if not self.context.strip():
            raise ValueError(
                "an external call carries its context line; a call whose context was "
                "blank could not be reproduced from the record that stored it"
            )


@dataclass(frozen=True, slots=True)
class ExternalResult:
    """What the external call produced: an outcome, prose or nothing, and the cost.

    Four invariants are enforced here rather than trusted, because each of them is a way
    the external half could quietly become something it is not:

    * **``ANSWERED`` carries prose.** FR-89's *"never produces an empty card"* starts
      here: a success with nothing in it would reach the reader as a heading over a void.
    * **Nothing but ``ANSWERED`` carries prose.** A timeout holding half a sentence is a
      partial third-party claim presented as a complete one.
    * **Every failure carries a degradation.** AD-15 again: a failure with no kind, no
      address and no detail is an absence wearing a different name.
    * **``ABANDONED`` names its orphaned job.** The accepted cost is accepted *because*
      it is recorded; an abandonment that named nothing would be the unexamined one.
    """

    outcome: ExternalOutcome
    request: ExternalRequest
    prose: str = ""
    job_id: str | None = None
    #: Wall-clock seconds the whole call took, measured by the adapter. Recorded on every
    #: answer so ``[ASSUMPTION A4]``'s ~2x Combined latency can be tested (NFR-3).
    elapsed_seconds: float = 0.0
    #: The id of a job the engine stopped waiting for and could not confirm cancelled.
    orphaned_job: str | None = None
    degradations: tuple[Degradation, ...] = ()

    def __post_init__(self) -> None:
        answered = self.outcome is ExternalOutcome.ANSWERED
        if answered and not self.prose.strip():
            raise ValueError(
                "an external answer with no prose is an empty card; FR-89 degrades to the "
                "approved answer with the gap stated rather than to a heading over nothing"
            )
        if not answered and self.prose:
            raise ValueError(
                f"a {self.outcome.value} result carrying prose; partial third-party text "
                "presented as a complete answer is worse than the gap stated plainly"
            )
        if not answered and not self.degradations:
            raise ValueError(
                "an external call that did not answer carries at least one degradation; "
                "without one it is an absence wearing a failure's name (AD-15)"
            )
        if self.outcome is ExternalOutcome.ABANDONED and not self.orphaned_job:
            raise ValueError(
                "an abandoned call names the job it left running; an orphaned job is an "
                "accepted cost of NFR-10 only while it is a recorded one"
            )
        if self.elapsed_seconds < 0.0:
            raise ValueError("elapsed time is measured forwards")

    @property
    def answered(self) -> bool:
        """Whether the third party produced text the reader can be shown."""
        return self.outcome is ExternalOutcome.ANSWERED


@runtime_checkable
class ExternalAgentPort(Protocol):
    """The third-party agent platform, as every caller outside ``adapters/`` sees it.

    One method, and it is total. There is no ``submit``, no ``poll`` and no ``cancel`` on
    this protocol: exposing the job lifecycle would let a caller hold a job id across a
    request, wait on it a second time, or build the loop AD-22 forbids. Submit-and-poll
    is the *protocol*, which AD-9 keeps inside ``adapters/``; the port is one question
    and one answer.
    """

    def ask(self, request: ExternalRequest) -> ExternalResult:
        """Ask the external agent *request*, within its own budget. Never raises.

        Total by contract. An implementation converts every foreign failure at the
        adapter boundary -- where AD-15 permits broad handling -- into an
        ``ExternalResult`` whose outcome is one of the four and whose degradations say
        what happened and where.

        Bounded by contract. An implementation returns within
        ``request.budget.total_seconds`` of being called, plus the cost of one poll it
        was already inside. A caller that needs a harder guarantee than that -- and
        NFR-10 says the answer path does -- abandons on its own clock as well, which is
        what the budget being on the request makes possible.
        """
        ...
