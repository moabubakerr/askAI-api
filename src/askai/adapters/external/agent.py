"""The external agent client: submit a job, poll it, take prose, or abandon it.

Purity: IO.

This is the only module in the tree that knows the agent platform's protocol -- that a
call is a **job** rather than a request, that a job is submitted to ``/jobs`` and polled at
``/jobs/{id}``, what the status field is called, which of its values mean finished and
which mean failed, and where the prose sits in the body. AD-9: *"no module outside
``adapters/`` knows either protocol."* Everything upstream holds an ``ExternalAgentPort``
and receives an ``ExternalResult``.

**It knows the protocol and not the library.** The HTTP mechanics arrive as an injected
``Exchange`` -- one request in, one reply out -- and no HTTP client is imported here.
That is a stronger reading of AD-9 than importing one would be: the *protocol* is the job
lifecycle, and it lives here; the *transport* is a dependency, and a module that names one
is a module coupled to it. It is also what lets the whole of this file -- the body
construction, the poll loop, the budget arithmetic, the failure conversion -- be exercised
against a scripted exchange, with no network, no platform and nothing reachable (NFR-6).
And there is nothing reachable: **no external endpoint exists for this system**, so this
is written against the shape AD-9 specifies rather than against a server anyone has called.

**Nothing escapes as an exception.** ``ask`` is total, for the same reason
``ChatModelClient.complete`` is and one stronger: NFR-10 says a slow or dead third party
*cannot degrade, delay or block the approved answer*, and an exception crossing this
boundary would do exactly that -- it would unwind through whatever was waiting for it. A
refused connection, a name that does not resolve, a 500, a body that is not a job, a job
that fails on the platform, a job that never finishes -- each becomes an
``ExternalResult`` with one of the four outcomes and at least one ``Degradation``. That is
why ``ruff``'s ``BLE001`` is lifted under ``adapters/**`` and nowhere else.

**The budget is spent forwards and never renewed.** Every exchange is issued against the
time remaining out of ``budget.total_seconds``, measured from the moment ``ask`` was
entered -- not against a fresh per-request timeout, which is how a poll loop of ten
"short" requests quietly becomes a two-minute wait. When the remaining time runs out the
loop stops, and it stops whether or not the platform ever answers.

**Abandonment, and the orphan it leaves.** Spine open question 2 asks whether the platform
supports cancellation or only client-side abandonment. This client does both, in that
order: it attempts a ``DELETE`` on the job -- best effort, on a sliver of the budget, never
allowed to extend the wait -- and then abandons regardless. The result names the job in
``orphaned_job`` whether or not the cancellation was accepted, because a cancellation this
client could not confirm is indistinguishable from one that did not happen. An orphaned job
is the accepted cost of NFR-10; it is accepted because it is written down.

**No retry.** AD-22. A submit that fails is a call that failed. Polling is not a retry --
it is the platform's own protocol for one call -- and the poll count is bounded by the
budget rather than by an attempt limit, so a fast platform is polled twice and a slow one
is abandoned rather than hammered.

**An open question this module does not close.** Story 9.6 specifies the external agent as
*"job submit-and-poll"*, and AD-22 says *"no component may loop"*;
``tests/test_foreclosure.py`` enforces the second by refusing any sleep under ``src/``, on
the grounds that *"a poll interval is a latency floor on every request"*. Both are right
about different things. The platform's protocol is asynchronous and there is no shape in
which one call is one round trip, so the loop is the third party's design rather than this
engine's ambition -- it plans nothing, chooses nothing and decides nothing about what to do
next, which is what AD-22's sentence is about. It is nonetheless a loop with a wait in it,
and the wait is a latency floor exactly as the foreclosure says. **This is raised as a
spine question, not resolved here.** What this module does instead of deciding is make the
wait a *collaborator*: ``wait`` is injected with no default, so nothing under ``src/``
names a sleep, the loop's timing is visible at the construction site, and a test proves the
budget without burning wall-clock. Whether the poll may exist at all is a spine call.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from askai.config.model import ExternalAgentSettings
from askai.domain.degradation import Degradation
from askai.observability.degradations import DegradationKind, degrade
from askai.ports.external_agent import (
    ExternalOutcome,
    ExternalRequest,
    ExternalResult,
)

__all__ = [
    "Exchange",
    "ExchangeTimeout",
    "ExternalAgentClient",
    "HttpReply",
    "HttpRequest",
    "job_body",
]

#: Where a degradation from this module says it happened.
_WHERE: Final = "adapters/external/agent"

#: The status the platform reports for a finished job. Read as a closed set here and
#: nowhere else: anything outside the two sets below is treated as "not finished yet" and
#: the budget decides, which is the safe direction -- an unknown status must never be read
#: as a completed answer.
_DONE: Final = "succeeded"
_FAILED: Final = frozenset({"failed", "cancelled", "canceled", "error"})

#: The first HTTP status that is not a success. Spelled here because this module knows the
#: protocol and there is no client library present to name it.
_BAD_REQUEST: Final = 400

#: The share of the whole budget a best-effort cancellation may spend. Small on purpose:
#: the cancellation is a courtesy to the platform, and a courtesy that delayed the reader's
#: answer would be the tail wagging NFR-10.
_CANCEL_SHARE: Final = 0.1

#: The floor on any single exchange's timeout. Below this a request cannot complete a TLS
#: handshake, so issuing one spends what is left of the budget to learn nothing.
_MIN_REQUEST_SECONDS: Final = 0.05


class ExchangeTimeout(Exception):
    """The transport gave up waiting. Raised by an ``Exchange``, never by this module.

    A distinct exception because the two failures need distinct outcomes: a timeout is a
    slow dependency and anything else is a broken one, and an operator reading a week of
    records has to be able to tell which conversation to start.
    """


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One exchange the job protocol needs, as a value the transport carries out."""

    method: str
    url: str
    timeout_seconds: float
    body: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HttpReply:
    """What came back: a status and a body, unparsed.

    Text rather than parsed JSON, deliberately. Parsing is knowledge of the protocol and
    the protocol lives here; a transport that handed back a decoded object would be one
    that had to decide what to do with a login page, which is this module's decision.
    """

    status: int
    text: str = ""


type Exchange = Callable[[HttpRequest], HttpReply]
"""One request out, one reply back. The whole of what this adapter needs of a network.

An implementation raises ``ExchangeTimeout`` when it gave up waiting and may raise
anything at all otherwise -- this module converts both, at the boundary AD-15 permits it.
"""


def job_body(request: ExternalRequest) -> dict[str, Any]:
    """The exact JSON submitted for *request*. Two strings, and nothing else.

    A plain function over values so a test can assert the outbound payload without a
    transport, a client or a platform -- which is the only way NFR-4a's *"what the engine
    sends is explicit and minimal"* can be checked rather than asserted. There is no
    ``rows``, no ``context_documents`` and no ``figures`` key: the approved layer has no
    field to travel in, here or on ``ExternalRequest``.
    """
    return {"question": request.question, "context": request.context}


@dataclass(frozen=True, slots=True)
class ExternalAgentClient:
    """``ExternalAgentPort`` over a submit-and-poll agent platform.

    A frozen value rather than a connection owner, because it owns no connection: the
    transport is the injected ``exchange`` and whatever pool it keeps is its own business.
    That is the practical benefit of not importing a client here -- there is nothing to
    close, so there is no lifetime to get wrong.
    """

    settings: ExternalAgentSettings
    exchange: Exchange
    #: How the poll loop waits between polls. **Required, with no default**, and the
    #: default is absent on purpose: a waiter bound here would put the pause inside the
    #: adapter where nobody reviewing the answer path would see it, and would name a sleep
    #: under ``src/`` -- which Story 1.18's foreclosure refuses, for the reason argued in
    #: the module docstring. A test supplies one that records the durations it was asked
    #: for instead of spending them.
    wait: Callable[[float], None]
    clock: Callable[[], float] = field(default=time.monotonic)

    # ------------------------------------------------------------------- the one call

    def ask(self, request: ExternalRequest) -> ExternalResult:
        """``ExternalAgentPort.ask``. Total, and bounded by the request's own budget."""
        started = self.clock()
        budget = request.budget

        submitted = self._submit(request, started)
        if isinstance(submitted, ExternalResult):
            return submitted
        job_id = submitted

        while True:
            remaining = budget.total_seconds - (self.clock() - started)
            if remaining <= _MIN_REQUEST_SECONDS:
                return self._abandon(request, job_id, started)
            polled = self._poll(request, job_id, started, remaining)
            if polled is not None:
                return polled
            self.wait(min(budget.poll_interval_seconds, max(remaining, 0.0)))

    # ------------------------------------------------------------------- the pieces

    def _submit(self, request: ExternalRequest, started: float) -> str | ExternalResult:
        """The job id, or the failed result that says why there is not one."""
        try:
            reply = self.exchange(
                HttpRequest(
                    method="POST",
                    url=self.settings.submit_url,
                    timeout_seconds=request.budget.read_seconds,
                    body=job_body(request),
                )
            )
        except ExchangeTimeout as error:
            return self._failure(
                request,
                ExternalOutcome.TIMED_OUT,
                started,
                f"submitting a job to {self.settings.submit_url} timed out: {error}",
            )
        except Exception as error:  # the boundary AD-15 permits this at
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"the job submission to {self.settings.submit_url} did not complete: "
                f"{type(error).__name__}: {error}",
            )

        if reply.status >= _BAD_REQUEST:
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"{self.settings.submit_url} answered {reply.status}; body begins "
                f"{reply.text[:200]!r}",
            )
        payload = _payload(reply)
        job_id = None if payload is None else payload.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"{self.settings.submit_url} answered {reply.status} with a body that "
                f"names no job; it begins {reply.text[:200]!r}",
            )
        return job_id

    def _poll(
        self, request: ExternalRequest, job_id: str, started: float, remaining: float
    ) -> ExternalResult | None:
        """One poll. A finished result, or ``None`` meaning *ask again if there is time*.

        A transport failure while polling is **not** fatal on its own: the job exists and
        the budget has not run out, so one unlucky poll returns ``None`` and the loop
        decides. It is the budget that ends this call, never a single bad round trip --
        which is what keeps the abandonment deadline the only deadline.
        """
        try:
            reply = self.exchange(
                HttpRequest(
                    method="GET",
                    url=self.settings.poll_url(job_id),
                    timeout_seconds=max(
                        min(request.budget.read_seconds, remaining), _MIN_REQUEST_SECONDS
                    ),
                )
            )
        except Exception:  # the boundary AD-15 permits this at
            return None

        if reply.status >= _BAD_REQUEST:
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"polling job {job_id} answered {reply.status}; body begins "
                f"{reply.text[:200]!r}",
                job_id=job_id,
            )
        payload = _payload(reply)
        if payload is None:
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"polling job {job_id} answered {reply.status} with a body that is not a "
                f"job status; it begins {reply.text[:200]!r}",
                job_id=job_id,
            )

        raw_status = payload.get("status")
        status = raw_status if isinstance(raw_status, str) else ""
        if status in _FAILED:
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"job {job_id} finished as {status!r} rather than answering",
                job_id=job_id,
            )
        if status != _DONE:
            return None

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            # A platform that reports success and returns nothing is the empty card
            # FR-89 forbids, caught at the only place it can be caught.
            return self._failure(
                request,
                ExternalOutcome.UNAVAILABLE,
                started,
                f"job {job_id} reported {_DONE} and carried no prose; an empty card is "
                "never shown, so the gap is stated instead",
                job_id=job_id,
            )
        return ExternalResult(
            outcome=ExternalOutcome.ANSWERED,
            request=request,
            prose=answer,
            job_id=job_id,
            elapsed_seconds=self._elapsed(started),
        )

    def _abandon(self, request: ExternalRequest, job_id: str, started: float) -> ExternalResult:
        """Stop waiting, ask the platform to stop too, and record the orphan either way."""
        cancelled = self._try_cancel(request, job_id)
        return ExternalResult(
            outcome=ExternalOutcome.ABANDONED,
            request=request,
            job_id=job_id,
            elapsed_seconds=self._elapsed(started),
            orphaned_job=job_id,
            degradations=(
                degrade(
                    DegradationKind.EXTERNAL_AGENT_UNAVAILABLE,
                    _WHERE,
                    f"the {request.budget.total_seconds}s budget expired with job "
                    f"{job_id} still in flight; the wait was abandoned client-side and "
                    f"the cancellation request was "
                    f"{'accepted' if cancelled else 'not confirmed'}. An orphaned job is "
                    "an accepted cost of never delaying the approved answer (NFR-10)",
                ),
            ),
        )

    def _try_cancel(self, request: ExternalRequest, job_id: str) -> bool:
        """Best effort, on a sliver of the budget, and never allowed to extend the wait."""
        try:
            reply = self.exchange(
                HttpRequest(
                    method="DELETE",
                    url=self.settings.poll_url(job_id),
                    timeout_seconds=max(
                        request.budget.total_seconds * _CANCEL_SHARE, _MIN_REQUEST_SECONDS
                    ),
                )
            )
        except Exception:  # the boundary AD-15 permits this at
            return False
        return reply.status < _BAD_REQUEST

    def _elapsed(self, started: float) -> float:
        return max(0.0, float(self.clock()) - float(started))

    def _failure(
        self,
        request: ExternalRequest,
        outcome: ExternalOutcome,
        started: float,
        detail: str,
        *,
        job_id: str | None = None,
    ) -> ExternalResult:
        return ExternalResult(
            outcome=outcome,
            request=request,
            job_id=job_id,
            elapsed_seconds=self._elapsed(started),
            degradations=(_degradation(detail),),
        )


def _payload(reply: HttpReply) -> dict[str, Any] | None:
    """The JSON object the platform answered with, or ``None`` if it is not one.

    Defensive to the point of pedantry because the failure it guards is specific: a proxy,
    a login page or a different service on the same port all answer with JSON-ish bodies,
    and an adapter that indexed blindly would raise out of a method promised not to.
    """
    try:
        payload = json.loads(reply.text)
    except Exception:  # the boundary AD-15 permits this at
        return None
    return payload if isinstance(payload, dict) else None


def _degradation(detail: str) -> Degradation:
    return degrade(DegradationKind.EXTERNAL_AGENT_UNAVAILABLE, _WHERE, detail)
