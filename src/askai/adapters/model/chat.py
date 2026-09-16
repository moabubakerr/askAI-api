"""The OpenAI-compatible chat client: one request, one validation, one typed outcome.

Purity: IO.

This is the only module in the tree that knows the chat protocol -- the URL shape, the
message envelope, the guided-decoding field names, the JSON the server answers with.
AD-9: *"no module outside ``adapters/`` knows either protocol."* Everything upstream
holds a ``ModelPort`` and receives its own validated value.

**Nothing escapes as an exception.** ``complete`` is total. A refused connection, a DNS
name that does not resolve (which is the normal case off the VM -- ``vllm`` is published
only inside its Docker network), a read timeout, a 404 from a wrong base url, a 400 from
a model name the server does not serve, a body that is not the shape the API promises,
or output the validator rejected -- each becomes a ``Failed`` carrying a
``Degradation``. That is why ``ruff``'s ``BLE001`` is lifted under ``adapters/**`` and
nowhere else: converting a foreign failure into a typed value is the job of this
boundary, and doing it anywhere else is the ``except Exception`` density AD-15 exists to
end.

**Constrained decoding and the validator, both.** vLLM supports ``guided_json``,
``guided_choice`` and ``guided_regex`` as extra body fields, and this client sends them.
AD-8 set the parser-plus-validator floor when constrained decoding was assumed
unavailable; it is available, and the floor does not move. A constrained decoder still
returns *text*, over a channel that can truncate at the token budget, from a server that
may not honour the constraint at all -- and no grammar can say whether an indicator id
exists in the catalogue. So the constraint narrows what has to be discarded, and
``ModelCall.validate`` still decides, on every call, whether anything is believed.

**No retry, no streaming, no second turn.** AD-22. One request goes out; if it does not
come back usable the caller degrades. A retry here would spend the budget twice and
would be the *"retry loop that eventually accepts something"* AD-8 names.

**Determinism.** ``temperature`` is 0 and ``seed`` is fixed, per AD-9 and AD-17. Neither
is a caller's choice: a sampled model call site would make the same question answer
differently on two runs, and the corpus gate could not distinguish a regression from
noise.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final, Self

import httpx

from askai.config.model import ChatModelSettings
from askai.observability.degradations import (
    DegradationKind,
    Failed,
    Found,
    Outcome,
    degrade,
)
from askai.ports.model import (
    ChoiceDecoding,
    Decoding,
    JsonObjectDecoding,
    JsonSchemaDecoding,
    ModelCall,
    RegexDecoding,
)

__all__ = ["ChatModelClient", "decoding_fields", "estimated_tokens", "request_body"]

#: AD-9's *"``temperature: 0`` and a fixed seed"*, as constants rather than parameters.
_TEMPERATURE: Final = 0.0
_SEED: Final = 20260916

#: Where a degradation from this module says it happened. The call site is appended, so
#: a rising rate names which of AD-22's four is failing rather than "the model".
_WHERE: Final = "adapters/model/chat"

#: A deliberately pessimistic characters-per-token figure, used only to refuse a request
#: that cannot fit the window *before* spending a round trip on it. English averages
#: nearer four characters per token and Arabic nearer two under a BPE vocabulary trained
#: mostly on English, so two is the safe end for a bilingual corpus: it over-estimates
#: the prompt, and over-estimating means refusing early rather than being truncated
#: mid-JSON by the server. It is an estimate and is never used to trim text.
_CHARS_PER_TOKEN: Final = 2.0

#: Envelope overhead the estimate cannot see: the chat template's role markers and the
#: grammar preamble a guided decode adds. A flat allowance, not a model of anything.
_ENVELOPE_TOKENS: Final = 64


def estimated_tokens(text: str) -> int:
    """A pessimistic token count for *text*. Used to refuse, never to truncate."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def decoding_fields(decoding: Decoding | None) -> Mapping[str, Any]:
    """The extra body fields that express *decoding* to vLLM.

    Separate from ``request_body`` and exported so a test can pin the wire names one at
    a time. ``guided_*`` are vLLM extensions passed through the OpenAI-compatible body;
    ``response_format`` is the OpenAI field. Both are sent for a schema, because a
    server that ignores the extension still gets told the output must be an object.
    """
    match decoding:
        case None:
            return {}
        case JsonObjectDecoding():
            return {"response_format": {"type": "json_object"}}
        case JsonSchemaDecoding(schema=schema):
            return {
                "guided_json": dict(schema),
                "response_format": {"type": "json_object"},
            }
        case ChoiceDecoding(choices=choices):
            return {"guided_choice": list(choices)}
        case RegexDecoding(pattern=pattern):
            return {"guided_regex": pattern}


def request_body(call: ModelCall[Any], model: str) -> dict[str, Any]:
    """The exact JSON sent to ``/v1/chat/completions`` for *call*.

    A plain function over values, so ``tests/test_model_adapter.py`` can assert the wire
    shape -- including that ``model`` is sent verbatim -- without a transport, a client,
    or a server.

    Two messages and no more: the instruction as ``system``, the input as ``user``.
    There is no assistant turn to continue and no ``tools`` key, so the shapes AD-22
    forbids are absent from the body rather than merely unused.
    """
    body: dict[str, Any] = {
        # Sent exactly as configured. On the confirmed deployment that is `qwen72b`
        # while the weights are Qwen2.5-32B-Instruct: **the number in the served name is
        # wrong, and it is still the name the server answers to.** vLLM rejects a
        # mismatch, so "fixing" this to qwen32b breaks every call in the estate.
        "model": model,
        "messages": [
            {"role": "system", "content": call.instruction},
            {"role": "user", "content": call.input_text},
        ],
        "max_tokens": call.budget.max_output_tokens,
        "temperature": _TEMPERATURE,
        "seed": _SEED,
        "n": 1,
        "stream": False,
    }
    body.update(decoding_fields(call.decoding))
    return body


class ChatModelClient:
    """``ModelPort`` over an OpenAI-compatible chat runtime.

    Not a frozen dataclass: it owns an ``httpx.Client`` whose connection pool is
    deliberately reused across calls, and a value type that owned a socket would be a
    value type that has to be closed.

    *transport* is the whole of the testability story. Passing an
    ``httpx.MockTransport`` exercises this class's real body construction, real header
    building, real response parsing and real failure conversion with no network and no
    model -- which is how NFR-6 stays true for the code that would otherwise be the one
    part of the engine only a live server could check. Production passes nothing and
    gets httpx's default transport against ``settings.base_url``.
    """

    def __init__(
        self,
        settings: ChatModelSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.read_timeout_seconds,
                pool=settings.connect_timeout_seconds,
            ),
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._settings.api_key is not None:
            headers["authorization"] = f"Bearer {self._settings.api_key}"
        return headers

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the connection pool. Safe to call twice."""
        self._client.close()

    # ------------------------------------------------------------------ the one call

    def complete[T](self, call: ModelCall[T]) -> Outcome[T]:
        """``ModelPort.complete``. Total: this returns, it does not raise."""
        over_budget = self._budget_refusal(call)
        if over_budget is not None:
            return over_budget

        try:
            response = self._client.post(
                self._settings.completions_url,
                json=request_body(call, self._settings.model),
                timeout=httpx.Timeout(
                    connect=call.budget.connect_seconds,
                    read=call.budget.read_seconds,
                    write=call.budget.read_seconds,
                    pool=call.budget.connect_seconds,
                ),
            )
        except Exception as error:  # the boundary AD-15 permits this at
            return self._unavailable(
                call,
                f"the request to {self._settings.completions_url} did not complete: "
                f"{type(error).__name__}: {error}",
            )

        if response.status_code != httpx.codes.OK:
            return self._unavailable(
                call,
                f"{self._settings.completions_url} answered {response.status_code}; "
                f"body begins {response.text[:200]!r}",
            )

        content = self._content_of(response)
        if content is None:
            return self._unavailable(
                call,
                f"{self._settings.completions_url} answered 200 with a body that is not "
                f"a chat completion; it begins {response.text[:200]!r}",
            )
        text, finish_reason = content

        # AD-8: the validator runs on *every* call, constrained decode or not.
        validated = self._validated(call, text)
        if validated is None:
            return Failed(
                (
                    degrade(
                        DegradationKind.GUARD_DISCARD,
                        f"{_WHERE}:{call.site.value}",
                        f"the validator rejected {len(text)} characters of output "
                        f"(finish_reason {finish_reason!r}, decoding "
                        f"{type(call.decoding).__name__ if call.decoding else 'free'}); "
                        f"output begins {text[:200]!r}",
                    ),
                )
            )
        return Found(validated)

    # ------------------------------------------------------------------ the pieces

    def _budget_refusal[T](self, call: ModelCall[T]) -> Failed | None:
        """Refuse, without a round trip, a call that cannot fit the runtime's window.

        The window is shared between prompt and completion, so a prompt that leaves no
        room for ``max_output_tokens`` does not fail cleanly at the server: it comes
        back truncated, which looks like a model that answered badly rather than a
        request that was never answerable. Checked here so the failure names the real
        cause.
        """
        prompt = (
            estimated_tokens(call.instruction) + estimated_tokens(call.input_text)
        ) + _ENVELOPE_TOKENS
        wanted = prompt + call.budget.max_output_tokens
        if wanted <= self._settings.token_budget:
            return None
        return self._unavailable(
            call,
            f"the prompt is an estimated {prompt} tokens and {call.budget.max_output_tokens} "
            f"were reserved for the completion, together {wanted} against a window of "
            f"{self._settings.token_budget}; the request was not sent",
        )

    def _validated[T](self, call: ModelCall[T], text: str) -> T | None:
        """Run the caller's validator, treating a raising validator as a rejection.

        The port asks a validator to be total. This does not trust it to be: a validator
        that raised would otherwise turn ``complete`` into a raising function, and the
        one guarantee every caller of this port has is that it does not raise.
        """
        try:
            return call.validate(text)
        except Exception:  # the boundary AD-15 permits this at
            return None

    def _content_of(self, response: httpx.Response) -> tuple[str, str] | None:
        """The assistant text and finish reason, or ``None`` if this is not that shape.

        Defensive to the point of pedantry because the failure it guards is specific: a
        proxy, a login page or a different service on the same port all answer 200 with
        JSON-ish bodies, and an adapter that indexed blindly would raise out of a method
        the caller was promised would not.
        """
        try:
            payload = response.json()
        except Exception:  # the boundary AD-15 permits this at
            return None
        if not isinstance(payload, dict):
            return None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if not isinstance(message, dict):
            return None
        text = message.get("content")
        if not isinstance(text, str):
            return None
        reason = first.get("finish_reason")
        return text, reason if isinstance(reason, str) else "unknown"

    def _unavailable[T](self, call: ModelCall[T], detail: str) -> Failed:
        return Failed(
            (
                degrade(
                    DegradationKind.MODEL_UNAVAILABLE,
                    f"{_WHERE}:{call.site.value}",
                    detail,
                ),
            )
        )
