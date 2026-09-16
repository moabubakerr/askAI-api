"""A neural vector source over an OpenAI-compatible ``/v1/embeddings`` endpoint.

Purity: IO.

Story 2.1 ships the character-trigram source (``adapters/index/vectors.py``) as the
working implementation and requires the choice to stay reversible: *"the embedding
runtime sits behind a port so that changing the model is a rebuild rather than a
migration."* This is the other implementation of that same ``VectorSourcePort``, shaped
to match ``TrigramVectorSource`` field for field so the two are interchangeable at every
call site: ``identity``, ``dimensions``, ``vectorise``.

**``identity`` is the safety net, so it carries everything that changes a vector.** The
model name, the width, and which form of the text the model was shown.
``adapters/index/generation.py`` writes this string into the index file and refuses to
load a generation whose identity is not the source's own -- because a cosine taken
across two vector spaces is a confident number with no meaning, and it is the one
failure that would look entirely healthy. Swapping trigrams for a model, or one model
for another, is therefore a loud rebuild instead of a silent garbage search.

**Failure raises here, and does not elsewhere.** ``ChatModelClient`` converts every
foreign failure into a ``Degradation`` because the answer path must survive losing the
model. ``VectorSourcePort`` has no channel for one -- it returns a vector -- and the
right behaviour on the build path is the opposite anyway: an index half-built from an
embedder that dropped out mid-run is an index that answers plausibly and wrongly. So a
failure raises ``EmbeddingUnavailable``, the build stops, and the previous generation
keeps serving (AD-13's swap is by reference; a build that never finishes never swaps).
The exception carries the typed ``Degradation`` so a caller that wants to count it can,
without re-deriving the kind from a message.

**The normalisation tension is measurable here, not resolved here.** See ``InputForm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Self

import httpx

from askai.adapters.index.vectors import unit_length
from askai.config.model import EmbeddingSettings
from askai.domain.degradation import Degradation
from askai.observability.degradations import DegradationKind, degrade

__all__ = [
    "EmbeddingUnavailable",
    "EmbeddingVectorSource",
    "InputForm",
    "as_written_unit_vector",
]

#: The family recorded in every index this source builds, alongside the model and width.
_FAMILY: Final = "openai-embeddings"

_WHERE: Final = "adapters/model/embeddings"


class InputForm(StrEnum):
    """Which form of the text the model is shown -- recorded in ``identity``.

    ``VectorSourcePort`` promises **already-normalised** text, because AD-26 puts the
    engine's single fold upstream and finding 121 is what a second fold costs. For
    hashed character trigrams that is exactly right: the fold is what lets an Arabic
    surface and an Arabic query share trigrams at all.

    For a *neural* embedder it is not obviously right. ``normalise()`` strips diacritics
    and tatweel, folds the hamza forms and ``ى``/``ة``, casefolds, and collapses
    punctuation -- and a multilingual sentence embedder was trained on text that still
    had all of that. The fold may be removing signal the model knows how to use.

    This port is **not** changed to find out. Instead the form is a recorded property of
    the source, so the two can be built and measured side by side and the winner is a
    number rather than an argument:

    * ``FOLDED`` is the port's contract and the default. The index build and the query
      both reach the vector through ``unit_vector_for``, which folds once, so the two
      paths cannot come apart.
    * ``AS_WRITTEN`` is the comparison arm. It is reached through
      ``as_written_unit_vector`` -- a function outside the port, used by a measurement
      harness and by a build that deliberately chooses it -- never by the answer path
      reaching through ``VectorSourcePort``.

    Because the form is in ``identity``, the two arms produce index files that refuse
    each other. An index built ``AS_WRITTEN`` and queried ``FOLDED`` does not return
    worse results; it does not load. That is what makes running the experiment safe.
    """

    #: The text as ``askai.domain.normalise.normalise`` left it. The port's contract.
    FOLDED = "folded"

    #: The text as the published layer spells it -- diacritics, hamza forms and case
    #: intact. Measurement only, and it must be the same on the build and query sides.
    AS_WRITTEN = "as-written"


class EmbeddingUnavailable(RuntimeError):
    """The embedding runtime could not be reached, or did not answer with vectors.

    Raised rather than returned, because the port it is raised out of returns a vector
    and a zero vector would be indistinguishable from an empty string -- which the port
    defines as *unmatchable*, not *failed*. Better a build that stops than an index that
    quietly contains a few thousand zeros.
    """

    def __init__(self, degradation: Degradation) -> None:
        super().__init__(degradation.detail)
        self.degradation = degradation


def _fail(detail: str) -> EmbeddingUnavailable:
    return EmbeddingUnavailable(degrade(DegradationKind.ADAPTER_UNAVAILABLE, _WHERE, detail))


@dataclass(eq=False, slots=True)
class EmbeddingVectorSource:
    """``VectorSourcePort`` over a hosted embedding model.

    Satisfies the port structurally rather than by inheritance, for the reason
    ``TrigramVectorSource`` does: a protocol with data members brings its own ``...``
    bodies when subclassed. The conformance is checked by ``mypy`` at every call site
    that takes the port, and asserted directly in ``tests/test_model_adapter.py``.

    *transport* is the testability story, as in ``chat.py``: an ``httpx.MockTransport``
    exercises the real request body, the real response parsing and the real width check
    with no network and no model, so NFR-6 holds for this module too.
    """

    settings: EmbeddingSettings
    input_form: InputForm = InputForm.FOLDED
    transport: httpx.BaseTransport | None = None
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            transport=self.transport,
            timeout=httpx.Timeout(
                connect=self.settings.connect_timeout_seconds,
                read=self.settings.read_timeout_seconds,
                write=self.settings.read_timeout_seconds,
                pool=self.settings.connect_timeout_seconds,
            ),
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.settings.api_key is not None:
            headers["authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ the port

    @property
    def identity(self) -> str:
        """Everything about this source that changes a vector, in one comparable string.

        The model name, the width, and the input form. Change any of the three and every
        index built by the old one is refused at load rather than searched.
        """
        return (
            f"{_FAMILY}/{self.settings.model}"
            f"/d{self.settings.dimensions}/{self.input_form.value}"
        )

    @property
    def dimensions(self) -> int:
        return self.settings.dimensions

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        """The vector for *normalised_text*, exactly ``dimensions`` long.

        The port's contract, honoured literally: whatever string arrives is what the
        model is shown. The empty string -- what collapsed punctuation leaves behind --
        returns the zero vector without a round trip, because the port defines that as
        unmatchable rather than as an error, and because an embedding service asked for
        the empty string is as likely to 400 as to answer.

        Not unit length: the index scales once, at build, so build and query cannot
        disagree about what an all-zero vector means.
        """
        if not normalised_text:
            return (0.0,) * self.settings.dimensions
        return self.embed_all((normalised_text,))[0]

    # ------------------------------------------------------------- the batch primitive

    def embed_all(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Vectors for *texts*, in order, in as few requests as the runtime allows.

        The build embeds over a thousand surfaces; one request per surface would make a
        refresh a thousands-deep serial round trip. The port is per-text because a query
        is one text, so the batch lives here, on the adapter, where the build can reach
        it without the port growing a second verb.

        **Chunked at ``settings.max_batch``.** Runtimes disagree about how many inputs one
        request may carry -- Text Embeddings Inference refuses above 32 by default, vLLM
        and the hosted APIs allow far more -- so sending all of them at once builds an
        index against a permissive runtime and fails against a strict one. Chunking here
        means the caller never has to know which it is talking to.

        Every returned vector is width-checked against the configured ``dimensions``.
        A service quietly serving a different model is exactly the failure ``identity``
        exists to catch, and catching it at the request rather than at the next index
        load is cheaper.
        """
        if not texts:
            return ()
        size = self.settings.max_batch
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), size):
            chunk = list(texts[start : start + size])
            payload = self._post({"model": self.settings.model, "input": chunk})
            vectors.extend(self._vectors_of(payload, len(chunk)))
        return tuple(vectors)

    def _post(self, body: dict[str, Any]) -> object:
        url = self.settings.embeddings_url
        try:
            response = self._client.post(url, json=body)
        except Exception as error:  # the boundary AD-15 permits this at
            raise _fail(
                f"the request to {url} did not complete: {type(error).__name__}: {error}"
            ) from error
        if response.status_code != httpx.codes.OK:
            raise _fail(
                f"{url} answered {response.status_code}; body begins {response.text[:200]!r}"
            )
        try:
            return response.json()
        except Exception as error:  # the boundary AD-15 permits this at
            raise _fail(
                f"{url} answered 200 with a body that is not JSON; it begins "
                f"{response.text[:200]!r}"
            ) from error

    def _vectors_of(self, payload: object, expected: int) -> tuple[tuple[float, ...], ...]:
        if not isinstance(payload, dict):
            raise _fail(f"{self.settings.embeddings_url} answered {type(payload).__name__}")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise _fail(
                f"{self.settings.embeddings_url} returned "
                f"{len(data) if isinstance(data, list) else 'no'} embeddings for "
                f"{expected} inputs; a partial batch cannot be matched back to its texts"
            )
        ordered = self._in_request_order(data, expected)
        return tuple(self._checked(entry) for entry in ordered)

    def _in_request_order(self, data: list[Any], expected: int) -> list[Any]:
        """The entries sorted by their declared ``index``, or left alone if unlabelled.

        The API promises an ``index`` per entry and does not promise request order.
        Sorting by it rather than trusting position is the difference between a
        mislabelled vector -- an indicator whose name vector belongs to another
        indicator, unfindable by any later check -- and a correct one.
        """
        positions: list[int] = []
        for entry in data:
            if not isinstance(entry, dict) or not isinstance(entry.get("index"), int):
                return data
            positions.append(int(entry["index"]))
        if sorted(positions) != list(range(expected)):
            raise _fail(
                f"{self.settings.embeddings_url} labelled its embeddings {sorted(positions)}, "
                f"which is not the {expected} inputs it was sent"
            )
        return [entry for _, entry in sorted(zip(positions, data, strict=True), key=_by_position)]

    def _checked(self, entry: object) -> tuple[float, ...]:
        if not isinstance(entry, dict):
            raise _fail("an embedding entry is not an object")
        values = entry.get("embedding")
        if not isinstance(values, list):
            raise _fail("an embedding entry carries no embedding array")
        if len(values) != self.settings.dimensions:
            raise _fail(
                f"{self.settings.model} returned a {len(values)}-dimension vector where "
                f"{self.settings.dimensions} is configured; the width is written into "
                "every index this source builds, so it is checked before it is stored"
            )
        try:
            return tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise _fail(f"an embedding holds a value that is not a number: {error}") from error


def _by_position(pair: tuple[int, Any]) -> int:
    return pair[0]


def as_written_unit_vector(raw: str, source: EmbeddingVectorSource) -> tuple[float, ...]:
    """The unit vector for *raw* text with **no fold applied** -- the comparison arm.

    Deliberately outside ``VectorSourcePort`` and typed to the concrete adapter, so it
    cannot be reached by anything holding the port. The answer path calls
    ``unit_vector_for``; only a measurement harness, or a build that has chosen
    ``InputForm.AS_WRITTEN`` and recorded that choice in the index identity, calls this.

    It exists because the question *"does AD-26's fold help or hurt a neural embedder?"*
    is empirical, and the alternative to measuring it is guessing in a port docstring.
    Refuses to run against a ``FOLDED`` source: a source that says ``folded`` in its
    identity and was fed unfolded text would write a truthful-looking identity over an
    index built the other way, which is the one lie ``identity`` must never tell.
    """
    if source.input_form is not InputForm.AS_WRITTEN:
        raise ValueError(
            f"{source.identity!r} records its input form as {source.input_form.value}; "
            "embedding unfolded text through it would make the identity written into "
            "the index file untrue, and the index would then load against a query path "
            "that folds. Build the source with InputForm.AS_WRITTEN for this arm."
        )
    return unit_length(source.vectorise(raw))
