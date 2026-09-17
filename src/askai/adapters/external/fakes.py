"""In-process stand-ins for the external agent, so nothing needs a third party.

Purity: IO by package, none in fact -- nothing here opens a socket.

**No external endpoint exists.** Not "is unreachable from a developer machine", as the
chat runtime is: there is no agent platform deployed for this system at all, and the
protocol in ``agent.py`` is written against the shape AD-9 specifies rather than against
a server anyone has called. So every story that touches the external agent develops
against one of these, and the whole suite is green with nothing reachable -- which is
NFR-6, and here it is not a preference but the only option.

They live under ``src/`` rather than in ``tests/`` for ``adapters/model/fakes.py``'s
reason: a fake beside the adapter it stands in for is the one every story uses, kept
honest by sitting next to the real implementation and satisfying the same protocol under
``mypy --strict``.

It is not a mock. ``ScriptedExternalAgent`` enforces the *budget* -- it compares its
declared latency against the request's own budget and returns ``ABANDONED`` with an
orphaned job id when it would have overrun -- so a test that passes against it has
exercised the abandonment path rather than skipped it.

**And it does not sleep.** Nothing under ``src/`` does; Story 1.18's foreclosure refuses
it, and it would be the wrong fixture anyway. A fake that *records* the durations it was
asked to wait is strictly better for testing a budget than one that spends them: the
assertion becomes "it asked to wait 20 seconds" rather than "the suite took 20 seconds",
which is the same fact without the cost. The waiter is injectable for the one test that
genuinely needs a caller to be blocked -- proving the approved answer is composed while
this call is outstanding (NFR-10) -- and that test supplies its own blocking waiter from
``tests/``, where wall-clock is a deliberate choice rather than a hidden one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from askai.observability.degradations import DegradationKind, degrade
from askai.ports.external_agent import (
    ExternalOutcome,
    ExternalRequest,
    ExternalResult,
)

__all__ = ["ScriptedExternalAgent", "no_external_agent"]

_WHERE: Final = "adapters/external/fakes"

#: The job id a fake reports. Fixed rather than random: a scripted abandonment must
#: record *an* orphan, and a deterministic one is assertable (AD-17).
_FAKE_JOB: Final = "fake-job-1"


class ScriptedExternalAgent:
    """An ``ExternalAgentPort`` that answers from a script, or fails as instructed.

    ``prose`` is what the platform would have produced. ``latency_seconds`` is what it
    would have taken: compared against the request's budget on every call, so scripting a
    slow platform produces a genuine ``ABANDONED`` result with an orphaned job rather
    than a special-cased one. ``unavailable`` short-circuits both, for the ordinary case
    of a dependency that is simply not there.

    ``wait`` is how the scripted latency is *taken*. The default records the duration and
    returns at once, so a twenty-second budget is tested in microseconds; a test that
    needs the caller genuinely blocked passes its own waiter.

    ``requests`` records what was asked, so a test can assert that what went out was the
    reader's question and a context line and *nothing else* (NFR-4a). ``waits`` records
    what it was asked to wait. Both are instance state, never module state: two tests
    holding two fakes cannot see each other's calls.
    """

    def __init__(
        self,
        prose: str = "",
        *,
        unavailable: str | None = None,
        latency_seconds: float = 0.0,
        outcome: ExternalOutcome | None = None,
        wait: Callable[[float], None] | None = None,
    ) -> None:
        self._prose = prose
        self._unavailable = unavailable
        self._latency = latency_seconds
        self._outcome = outcome
        self._wait = wait
        self._requests: list[ExternalRequest] = []
        self._waits: list[float] = []

    @property
    def requests(self) -> tuple[ExternalRequest, ...]:
        """Every request made, in order, exactly as it went out."""
        return tuple(self._requests)

    @property
    def waits(self) -> tuple[float, ...]:
        """Every duration this fake was asked to spend, in order."""
        return tuple(self._waits)

    def ask(self, request: ExternalRequest) -> ExternalResult:
        self._requests.append(request)
        if self._latency > 0.0:
            self._waits.append(self._latency)
            if self._wait is not None:
                self._wait(self._latency)

        if self._unavailable is not None:
            return self._failed(
                request, ExternalOutcome.UNAVAILABLE, self._unavailable, job_id=None
            )
        if self._outcome is not None and self._outcome is not ExternalOutcome.ANSWERED:
            return self._failed(
                request,
                self._outcome,
                f"the scripted platform returned {self._outcome.value}",
                job_id=_FAKE_JOB,
            )
        if self._latency > request.budget.total_seconds:
            return self._failed(
                request,
                ExternalOutcome.ABANDONED,
                f"the scripted platform takes {self._latency}s against a "
                f"{request.budget.total_seconds}s budget; the wait was abandoned "
                "client-side and the job was left running",
                job_id=_FAKE_JOB,
            )
        if not self._prose.strip():
            return self._failed(
                request,
                ExternalOutcome.UNAVAILABLE,
                "nothing is scripted for this agent; a call the test did not expect is a "
                "call the test should see",
                job_id=_FAKE_JOB,
            )
        return ExternalResult(
            outcome=ExternalOutcome.ANSWERED,
            request=request,
            prose=self._prose,
            job_id=_FAKE_JOB,
            elapsed_seconds=self._latency,
        )

    def _failed(
        self,
        request: ExternalRequest,
        outcome: ExternalOutcome,
        detail: str,
        *,
        job_id: str | None,
    ) -> ExternalResult:
        return ExternalResult(
            outcome=outcome,
            request=request,
            job_id=job_id,
            elapsed_seconds=min(self._latency, request.budget.total_seconds),
            orphaned_job=job_id if outcome is ExternalOutcome.ABANDONED else None,
            degradations=(
                degrade(DegradationKind.EXTERNAL_AGENT_UNAVAILABLE, _WHERE, detail),
            ),
        )


def no_external_agent(
    reason: str = "no external agent platform is deployed for this system",
) -> ScriptedExternalAgent:
    """The default for a test -- and for a deployment -- with no third party wired.

    It is a *fake that fails*, not the absence of a port, so the answer path exercises the
    unavailable branch on every request rather than skipping it on a ``None`` check. The
    gap is then stated in the answer, which is what FR-89 asks for.
    """
    return ScriptedExternalAgent(unavailable=reason)
