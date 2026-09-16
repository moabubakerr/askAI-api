"""Where the model runtimes live -- the chat endpoint and the embedding endpoint.

Purity: configuration; validated at startup, the only in-project reader of the environment.

AD-9 puts the engine's own model calls against a *direct on-prem runtime* behind one
port. Which runtime, under which served name, with which budget, is a deployment fact,
so it is read here and nowhere else -- an ``os.environ`` lookup in an adapter is the
ambient configuration the spine forbids and the reason a test would depend on the
machine it runs on. ``tests/test_schema.py`` scans for that and fails the build.

**Two endpoints, not one.** The chat runtime and the embedding runtime are separate
settings objects because they are separate processes on the target VM: vLLM already
holds ~130 GB of the H200 for chat, and an embedding model runs beside it (or on CPU).
Conflating them into one base url would make "point the embedder somewhere else" a
change to the chat path.

**There is no default base url and no default model name.** A default would let a
process start, answer, and be wrong -- pointed at a runtime nobody meant, serving a
model nobody reviewed. The identity settings are required and a missing one fails at
startup with a message that names the variable. Timeouts and the token budget *do*
carry declared defaults: they are operational dials, they cannot silently address the
wrong server, and the defaults here are the measured properties of the confirmed
deployment (see the VM section of ``AGENTS.md``). They remain overridable per
deployment. None of them is a reader-affecting constant, so none belongs in ``rules/``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from askai.config.database import ConfigError

__all__ = [
    "CHAT_API_KEY_ENV",
    "CHAT_BASE_URL_ENV",
    "CHAT_CONNECT_TIMEOUT_ENV",
    "CHAT_MODEL_ENV",
    "CHAT_READ_TIMEOUT_ENV",
    "CHAT_TOKEN_BUDGET_ENV",
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "DEFAULT_TOKEN_BUDGET",
    "EMBEDDING_API_KEY_ENV",
    "EMBEDDING_BASE_URL_ENV",
    "EMBEDDING_CONNECT_TIMEOUT_ENV",
    "EMBEDDING_DIMENSIONS_ENV",
    "EMBEDDING_MODEL_ENV",
    "EMBEDDING_READ_TIMEOUT_ENV",
    "ChatModelSettings",
    "ConfigError",
    "EmbeddingSettings",
]

# ------------------------------------------------------------------ the chat runtime

#: The root of the OpenAI-compatible API, *without* a trailing path segment: the
#: adapter appends ``/chat/completions``. On the target VM this is
#: ``http://vllm:8000/v1``, a name that resolves only inside that Docker network.
CHAT_BASE_URL_ENV: Final = "ASKAI_MODEL_BASE_URL"

#: The name the server answers to, sent verbatim in every request body.
#:
#: On the confirmed deployment that name is ``qwen72b`` while the weights are
#: ``Qwen/Qwen2.5-32B-Instruct``. **The number in the served name is wrong, and it is
#: still the name.** vLLM rejects a request whose ``model`` does not match what it
#: serves, so "correcting" this to ``qwen32b`` breaks every call. It is a setting rather
#: than a constant precisely so nobody has to decide whether to fix it in code.
CHAT_MODEL_ENV: Final = "ASKAI_MODEL_NAME"

#: Optional. vLLM on the VM is unauthenticated; a hosted OpenAI-compatible endpoint is
#: not. Absent means no ``Authorization`` header is sent, which is different from
#: sending an empty one.
CHAT_API_KEY_ENV: Final = "ASKAI_MODEL_API_KEY"

CHAT_CONNECT_TIMEOUT_ENV: Final = "ASKAI_MODEL_CONNECT_TIMEOUT"
CHAT_READ_TIMEOUT_ENV: Final = "ASKAI_MODEL_READ_TIMEOUT"

#: The whole context window, prompt *plus* completion. Measured ``max_model_len`` on the
#: confirmed server is 16384; a deployment with a different window sets this.
CHAT_TOKEN_BUDGET_ENV: Final = "ASKAI_MODEL_TOKEN_BUDGET"

# --------------------------------------------------------------- the embedding runtime

EMBEDDING_BASE_URL_ENV: Final = "ASKAI_EMBEDDING_BASE_URL"
EMBEDDING_MODEL_ENV: Final = "ASKAI_EMBEDDING_MODEL"
EMBEDDING_API_KEY_ENV: Final = "ASKAI_EMBEDDING_API_KEY"
EMBEDDING_CONNECT_TIMEOUT_ENV: Final = "ASKAI_EMBEDDING_CONNECT_TIMEOUT"
EMBEDDING_READ_TIMEOUT_ENV: Final = "ASKAI_EMBEDDING_READ_TIMEOUT"

#: Required, and not discovered by probing. The width goes into the vector source's
#: ``identity``, which ``adapters/index/generation.py`` writes into the index file and
#: compares at load. Discovering it at runtime would mean an index whose declared width
#: depended on whether the embedding service happened to answer during the build.
EMBEDDING_DIMENSIONS_ENV: Final = "ASKAI_EMBEDDING_DIMENSIONS"

# ------------------------------------------------------------------------- the defaults

#: Seconds to establish the connection. Short: inside the estate a connect that takes
#: longer than this is a runtime that is down, not one that is busy (NFR-4).
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 2.0

#: Seconds to wait for the response body. AD-9 calls every model call budgeted and
#: abandonable; this is the abandon point, and the degradation it produces is the
#: answer degrading to prose-free rather than the request hanging.
DEFAULT_READ_TIMEOUT_SECONDS: Final = 20.0

#: ``max_model_len`` on the confirmed deployment: prompt plus completion, together.
DEFAULT_TOKEN_BUDGET: Final = 16384


def _required(environ: Mapping[str, str], name: str, purpose: str) -> str:
    raw = environ.get(name, "").strip()
    if not raw:
        raise ConfigError(
            f"{name} is not set; it names {purpose}. There is no default -- a process "
            "that guessed a model endpoint would start, answer, and be wrong."
        )
    return raw


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    raw = environ.get(name, "").strip()
    return raw or None


def _positive_float(environ: Mapping[str, str], name: str, fallback: float) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} is {raw!r}, which is not a number of seconds") from None
    if value <= 0.0:
        raise ConfigError(
            f"{name} is {value}; a non-positive timeout is not 'wait forever', it is a "
            "call that fails before it is made"
        )
    return value


def _positive_int(environ: Mapping[str, str], name: str, fallback: int | None) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        if fallback is None:
            raise ConfigError(
                f"{name} is not set and has no default; it is recorded in the index "
                "identity, so a guessed value would be written into an index file."
            )
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} is {raw!r}, which is not a whole number") from None
    if value < 1:
        raise ConfigError(f"{name} is {value}; it counts tokens or dimensions, so it is at least 1")
    return value


def _endpoint(base_url: str, path: str) -> str:
    """*path* under *base_url*, with exactly one separator between them."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    """Everything the chat adapter needs, resolved and checked once.

    Frozen: a setting that could be rebound mid-process is a setting two requests can
    disagree about, and the model name in particular is written into the record of what
    answered.
    """

    base_url: str
    model: str
    api_key: str | None = None
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    token_budget: int = DEFAULT_TOKEN_BUDGET

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ConfigError("a chat runtime needs a base url")
        if not self.model.strip():
            raise ConfigError(
                "a chat runtime needs the served model name; the server matches it "
                "exactly and rejects anything else"
            )
        if self.connect_timeout_seconds <= 0.0 or self.read_timeout_seconds <= 0.0:
            raise ConfigError("both timeouts are positive numbers of seconds")
        if self.token_budget < 1:
            raise ConfigError("the token budget counts tokens, so it is at least 1")

    @property
    def completions_url(self) -> str:
        """The one endpoint this adapter calls. No streaming path, no completions-legacy."""
        return _endpoint(self.base_url, "chat/completions")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ChatModelSettings:
        """Read the chat settings, or fail loudly naming the variable.

        *environ* is injectable so a test can state the environment it means rather than
        mutating the process's -- which is shared state between tests and the reason
        "it passes alone but not in the suite" happens.
        """
        env = os.environ if environ is None else environ
        return cls(
            base_url=_required(
                env, CHAT_BASE_URL_ENV, "the OpenAI-compatible chat runtime's /v1 root"
            ),
            model=_required(
                env, CHAT_MODEL_ENV, "the model name the runtime serves, sent verbatim"
            ),
            api_key=_optional(env, CHAT_API_KEY_ENV),
            connect_timeout_seconds=_positive_float(
                env, CHAT_CONNECT_TIMEOUT_ENV, DEFAULT_CONNECT_TIMEOUT_SECONDS
            ),
            read_timeout_seconds=_positive_float(
                env, CHAT_READ_TIMEOUT_ENV, DEFAULT_READ_TIMEOUT_SECONDS
            ),
            token_budget=_positive_int(env, CHAT_TOKEN_BUDGET_ENV, DEFAULT_TOKEN_BUDGET),
        )


@dataclass(frozen=True, slots=True)
class EmbeddingSettings:
    """Everything the embedding adapter needs, resolved and checked once.

    ``dimensions`` has no default. It is not a dial: it is half of the identity written
    into every index generation, and a wrong one is either a loud refusal at load or --
    if it happened to match -- a silent mismatch between two vector spaces.
    """

    base_url: str
    model: str
    dimensions: int
    api_key: str | None = None
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ConfigError("an embedding runtime needs a base url")
        if not self.model.strip():
            raise ConfigError("an embedding runtime needs the served model name")
        if self.dimensions < 1:
            raise ConfigError(
                f"an embedding width of {self.dimensions} cannot hold a feature; the "
                "width is recorded in the index and compared at load"
            )
        if self.connect_timeout_seconds <= 0.0 or self.read_timeout_seconds <= 0.0:
            raise ConfigError("both timeouts are positive numbers of seconds")

    @property
    def embeddings_url(self) -> str:
        return _endpoint(self.base_url, "embeddings")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EmbeddingSettings:
        """Read the embedding settings, or fail loudly naming the variable."""
        env = os.environ if environ is None else environ
        return cls(
            base_url=_required(
                env, EMBEDDING_BASE_URL_ENV, "the OpenAI-compatible embedding runtime's /v1 root"
            ),
            model=_required(env, EMBEDDING_MODEL_ENV, "the embedding model the runtime serves"),
            dimensions=_positive_int(env, EMBEDDING_DIMENSIONS_ENV, None),
            api_key=_optional(env, EMBEDDING_API_KEY_ENV),
            connect_timeout_seconds=_positive_float(
                env, EMBEDDING_CONNECT_TIMEOUT_ENV, DEFAULT_CONNECT_TIMEOUT_SECONDS
            ),
            read_timeout_seconds=_positive_float(
                env, EMBEDDING_READ_TIMEOUT_ENV, DEFAULT_READ_TIMEOUT_SECONDS
            ),
        )
