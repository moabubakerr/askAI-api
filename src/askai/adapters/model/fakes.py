"""In-process stand-ins for the two model runtimes, so nothing needs a network.

Purity: IO by package, none in fact -- neither class here opens a socket.

NFR-6 asks that the whole answer path be unit-testable, and the target VM makes that
more than a preference: ``vllm`` resolves only inside its own Docker network, so no
developer machine and no CI runner can reach it. Every story that touches the model
therefore develops against one of these and the suite is green with no model available.

They live under ``src/`` rather than in ``tests/`` on purpose. A fake in the test tree
is a fake one story can use; a fake beside the adapter it stands in for is the one
every story uses, kept honest by sitting next to the real implementation and by
satisfying the same protocol under ``mypy --strict``.

Neither is a mock. ``ScriptedModel`` runs the caller's real validator over the scripted
text and refuses an over-budget call, so a test that passes against it has exercised
AD-8's parse-and-validate floor rather than skipped it. ``FakeEmbeddingSource`` produces
deterministic vectors from a digest, so an index built against it is searchable in the
next process (AD-17) and reproduces exactly.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

from askai.observability.degradations import (
    DegradationKind,
    Failed,
    Found,
    Outcome,
    degrade,
)
from askai.ports.model import CallSite, ModelCall

__all__ = ["FakeEmbeddingSource", "ScriptedModel", "no_model"]

_WHERE: Final = "adapters/model/fakes"

#: Mirrors ``chat.estimated_tokens``. Duplicated rather than imported so the fake does
#: not drag ``httpx`` into a test that wanted no client at all; the constant is the one
#: thing that has to agree, and it is asserted to in ``tests/test_model_adapter.py``.
_CHARS_PER_TOKEN: Final = 2.0


class ScriptedModel:
    """A ``ModelPort`` that answers from a script, or refuses to answer at all.

    ``replies`` maps a call site to the raw text the runtime would have produced, which
    is then handed to the caller's own validator -- so a test can script a *bad* answer
    and watch it be discarded, which is the behaviour that actually matters. A site with
    no scripted reply fails as unavailable, so a call nobody expected is loud.

    ``calls`` records what was asked, for a test that needs to assert the prompt was
    budgeted or the constraint was set. It is instance state, never module state: two
    tests holding two fakes cannot see each other's calls, which is the same reason
    AD-15 forbids an ambient collector.
    """

    def __init__(
        self,
        replies: Mapping[CallSite, str] | None = None,
        *,
        unavailable: str | None = None,
        token_budget: int = 16384,
    ) -> None:
        self._replies = dict(replies or {})
        self._unavailable = unavailable
        self._token_budget = token_budget
        self._calls: list[ModelCall[Any]] = []

    @property
    def calls(self) -> tuple[ModelCall[Any], ...]:
        """Every call made, in order."""
        return tuple(self._calls)

    def complete[T](self, call: ModelCall[T]) -> Outcome[T]:
        self._calls.append(call)
        if self._unavailable is not None:
            return self._failed(call, DegradationKind.MODEL_UNAVAILABLE, self._unavailable)

        prompt = math.ceil(len(call.instruction) / _CHARS_PER_TOKEN) + math.ceil(
            len(call.input_text) / _CHARS_PER_TOKEN
        )
        if prompt + call.budget.max_output_tokens > self._token_budget:
            return self._failed(
                call,
                DegradationKind.MODEL_UNAVAILABLE,
                f"an estimated {prompt} prompt tokens plus {call.budget.max_output_tokens} "
                f"reserved exceed the {self._token_budget} window",
            )

        text = self._replies.get(call.site)
        if text is None:
            return self._failed(
                call,
                DegradationKind.MODEL_UNAVAILABLE,
                f"nothing is scripted for {call.site.value}; a call the test did not "
                "expect is a call the test should see",
            )

        validated = call.validate(text)
        if validated is None:
            return self._failed(
                call,
                DegradationKind.GUARD_DISCARD,
                f"the validator rejected the scripted output for {call.site.value}: "
                f"{text[:200]!r}",
            )
        return Found(validated)

    def _failed[T](self, call: ModelCall[T], kind: DegradationKind, detail: str) -> Failed:
        return Failed((degrade(kind, f"{_WHERE}:{call.site.value}", detail),))


def no_model(reason: str = "no model runtime is reachable from this process") -> ScriptedModel:
    """The default for a test that asserts the engine works without a model at all."""
    return ScriptedModel(unavailable=reason)


class FakeEmbeddingSource:
    """A ``VectorSourcePort`` whose vectors are a digest, not a model.

    Deterministic across processes -- ``blake2b``, never ``hash()``, which is seeded per
    process and would make an index unsearchable after a restart. Vectors are dense and
    spread over the whole width, so they behave like embeddings under cosine rather than
    like the sparse counts a trigram source produces: a test of a *threshold* gets
    plausible numbers instead of zeros.

    Its ``identity`` names itself. An index built against this fake and then queried
    against a real embedding source is refused at load by
    ``adapters/index/generation.py`` -- which is the point: a fixture must never be
    mistakable for the thing it stands in for.
    """

    def __init__(self, dimensions: int = 8, *, label: str = "fake") -> None:
        if dimensions < 1:
            raise ValueError("a vector of no dimensions cannot hold a feature")
        self._dimensions = dimensions
        self._label = label

    @property
    def identity(self) -> str:
        return f"fake-embeddings/{self._label}/d{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        """A dense, deterministic vector for *normalised_text*; zeros for the empty string."""
        if not normalised_text:
            return (0.0,) * self._dimensions
        return tuple(self._component(normalised_text, column) for column in range(self._dimensions))

    def _component(self, text: str, column: int) -> float:
        digest = hashlib.blake2b(
            f"{column}\x1f{text}".encode(), digest_size=4, person=b"askai-fk"
        ).digest()
        # Centred on zero so two unrelated texts are not forced to a positive cosine by
        # every component sharing a sign.
        return int.from_bytes(digest, "big") / 0x7FFFFFFF - 1.0

    def embed_all(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """The batch shape ``EmbeddingVectorSource`` offers the build, so both fit."""
        return tuple(self.vectorise(text) for text in texts)
