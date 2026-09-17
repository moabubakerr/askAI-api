"""The model tie-break, as the answer path reaches it: one rung, one request's worth.

Purity: edge.

Story 2.6 built the rung in ``adapters/model/tiebreak.py`` and the binder consults it
through a function (``compile.binder.TieBreaker``). This is the piece between them, and
it exists because of two facts that do not fit in either end.

**``compile/`` may not name the rung.** ``lint-imports`` forbids ``compile -> adapters``,
and ``tests/test_epic9_closed_world.py`` forbids every composing package from importing
``askai.ports.model`` or ``askai.adapters.model`` at all -- NFR-5 asserted structurally
rather than promised. So the ``ModelPort`` is bound here, at the edge, and the binder
receives a callable that has already forgotten a model was involved.

**The binder has no record to write on.** A ``TieBreak`` carries three things: the
resolution, the degradations, and the ``prompt_id@version`` and hash of the prompt that
produced it (AD-29). The binder reads the first, because it binds a field with it; the
other two belong on the answer record, which is built here in ``api/``. So this rung
keeps what it used, on the instance, and ``ask.py`` reads it off after compiling.

**Per request, never per process.** One of these is built for one question and is
discarded with it. Two concurrent readers hold two rungs and cannot see each other's
calls -- the same reason AD-15 forbids an ambient collector and the same shape
``ScriptedModel`` uses for the calls it records.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from askai.adapters.model.tiebreak import TieBreak, break_tie
from askai.compile.resolve import Disambiguation
from askai.domain.degradation import Degradation
from askai.observability.record import PromptUse
from askai.ports.model import ModelPort

__all__ = ["TieBreakRung"]


@dataclass(slots=True)
class TieBreakRung:
    """One request's model rung: call it with a tie, then read what it cost.

    Callable rather than a method by name, so what the binder is handed is a function of
    the question and the tie and nothing else -- it cannot reach the port, the prompt or
    the degradations through it.
    """

    model: ModelPort

    #: Every tie put to the model this request, in order. Instance state on a value that
    #: lives for one question; nothing at module scope collects anything (AD-15).
    used: list[TieBreak] = field(default_factory=list)

    def __call__(self, question: str, tied: Disambiguation) -> TieBreak:
        broken = break_tie(question, tied, self.model)
        self.used.append(broken)
        return broken

    @property
    def degradations(self) -> tuple[Degradation, ...]:
        """What the rung counted -- an outage, a discarded answer, a tie too wide to put.

        On the record rather than on the package, because a tie-break that fell back
        changed nothing a reader sees: they are asked the question the deterministic
        ladder had already composed. What it changed is how the answer was reached, and
        that is what a record is for (AD-16).
        """
        return tuple(
            degradation for broken in self.used for degradation in broken.degradations
        )

    @property
    def prompts(self) -> tuple[PromptUse, ...]:
        """The prompts this answer used, recorded whether or not they were believed.

        AD-29's traceability: a discarded output is still an output this prompt produced,
        so the ``PromptUse`` is taken off every call and not only off the ones that bound
        something.
        """
        return tuple(broken.prompt for broken in self.used)
