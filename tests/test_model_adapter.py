"""The model and embedding adapters -- exercised in full, with no model available.

The constraint this file is written under is the point of it: the confirmed runtime,
``http://vllm:8000/v1``, resolves only inside the target VM's Docker network. Nothing
that runs this suite can reach it. So every assertion here is made against an
``httpx.MockTransport`` driving the *real* client -- the real request body, the real
headers, the real response parsing, the real failure conversion -- or against the fakes
in ``adapters/model/fakes.py``. NFR-6 holds: the suite is green with no model.

Four claims are under test:

1. the wire body is exactly what vLLM is sent, including the served model name verbatim
   and the guided-decoding fields under their vLLM names;
2. **every** failure mode leaves the adapter as a typed ``Degradation`` from the closed
   set, and none of them escapes as an exception;
3. the validator runs on every call whether or not decoding was constrained -- AD-8's
   floor does not move because guided decoding turned out to be available;
4. the embedding source's ``identity`` carries what would make a vector incomparable,
   so ``adapters/index/generation.py`` refuses a mismatched index rather than searching
   it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import httpx
import pytest

from askai.adapters.index.generation import IndexLoadError, _verify_source
from askai.adapters.index.vectors import TrigramVectorSource, unit_vector_for
from askai.adapters.model.chat import (
    ChatModelClient,
    decoding_fields,
    estimated_tokens,
    request_body,
)
from askai.adapters.model.embeddings import (
    EmbeddingUnavailable,
    EmbeddingVectorSource,
    InputForm,
    as_written_unit_vector,
)
from askai.adapters.model.fakes import FakeEmbeddingSource, ScriptedModel, no_model
from askai.config.model import (
    CHAT_BASE_URL_ENV,
    CHAT_MODEL_ENV,
    CHAT_READ_TIMEOUT_ENV,
    CHAT_TOKEN_BUDGET_ENV,
    DEFAULT_TOKEN_BUDGET,
    EMBEDDING_BASE_URL_ENV,
    EMBEDDING_DIMENSIONS_ENV,
    EMBEDDING_MODEL_ENV,
    ChatModelSettings,
    ConfigError,
    EmbeddingSettings,
)
from askai.observability.degradations import (
    Absent,
    DegradationKind,
    Failed,
    Found,
    Outcome,
    classify,
)
from askai.ports.model import (
    Budget,
    CallSite,
    ChoiceDecoding,
    JsonObjectDecoding,
    JsonSchemaDecoding,
    ModelCall,
    ModelPort,
    RegexDecoding,
)
from askai.ports.vectors import VectorSourcePort

# The confirmed deployment, as ``AGENTS.md`` records it. The served name says 72B and
# the weights are Qwen2.5-32B-Instruct; the name is what the server answers to and the
# number in it is wrong. Pinned here so a "correction" fails a test with an explanation.
SERVED_MODEL_NAME: Final = "qwen72b"
BASE_URL: Final = "http://vllm:8000/v1"

A_BUDGET: Final = Budget(max_output_tokens=64, connect_seconds=2.0, read_seconds=5.0)


def a_settings(**overrides: Any) -> ChatModelSettings:
    fields: dict[str, Any] = {"base_url": BASE_URL, "model": SERVED_MODEL_NAME}
    fields.update(overrides)
    return ChatModelSettings(**fields)


def an_embedding_settings(**overrides: Any) -> EmbeddingSettings:
    fields: dict[str, Any] = {
        "base_url": "http://embeddings:8001/v1",
        "model": "bge-m3",
        "dimensions": 4,
    }
    fields.update(overrides)
    return EmbeddingSettings(**fields)


def accept_anything(text: str) -> str | None:
    return text or None


def a_call(
    *,
    site: CallSite = CallSite.OPERATION_CLASSIFICATION,
    instruction: str = "Answer with one word.",
    input_text: str = "what is inflation",
    validate: Callable[[str], str | None] = accept_anything,
    budget: Budget = A_BUDGET,
    decoding: Any = None,
) -> ModelCall[str]:
    return ModelCall(
        site=site,
        instruction=instruction,
        input_text=input_text,
        validate=validate,
        budget=budget,
        decoding=decoding,
    )


def completion(text: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    """A minimal OpenAI-compatible chat completion, as vLLM returns one."""
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "model": SERVED_MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
    }


def serving(
    handler: Callable[[httpx.Request], httpx.Response],
    **settings: Any,
) -> ChatModelClient:
    return ChatModelClient(a_settings(**settings), transport=httpx.MockTransport(handler))


def answering(payload: Any, *, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def only_degradation(outcome: Outcome[Any]) -> tuple[DegradationKind, str]:
    """The kind and detail of a failure, asserting there is exactly one."""
    assert isinstance(outcome, Failed), f"expected a failure, got {outcome!r}"
    assert len(outcome.degradations) == 1
    return classify(outcome.degradations[0].kind), outcome.degradations[0].detail


# ------------------------------------------------------------------------- settings


def test_the_chat_settings_have_no_default_endpoint() -> None:
    """A default base url is how a process starts, answers, and is wrong."""
    with pytest.raises(ConfigError) as excinfo:
        ChatModelSettings.from_env({CHAT_MODEL_ENV: SERVED_MODEL_NAME})
    assert CHAT_BASE_URL_ENV in str(excinfo.value)


def test_the_chat_settings_have_no_default_model_name() -> None:
    with pytest.raises(ConfigError) as excinfo:
        ChatModelSettings.from_env({CHAT_BASE_URL_ENV: BASE_URL})
    assert CHAT_MODEL_ENV in str(excinfo.value)


def test_the_chat_settings_read_an_injected_environment_and_never_the_process() -> None:
    """``from_env`` is injectable, so no test mutates shared state to be reproducible."""
    settings = ChatModelSettings.from_env(
        {
            CHAT_BASE_URL_ENV: BASE_URL,
            CHAT_MODEL_ENV: SERVED_MODEL_NAME,
            CHAT_READ_TIMEOUT_ENV: "30",
            CHAT_TOKEN_BUDGET_ENV: "16384",
        }
    )
    assert settings.model == SERVED_MODEL_NAME
    assert settings.read_timeout_seconds == 30.0
    assert settings.token_budget == 16384


def test_the_default_token_budget_is_the_measured_window() -> None:
    """``max_model_len`` on the confirmed server: prompt and completion together."""
    assert DEFAULT_TOKEN_BUDGET == 16384
    assert a_settings().token_budget == 16384


def test_an_absent_api_key_is_not_an_empty_one() -> None:
    settings = ChatModelSettings.from_env(
        {CHAT_BASE_URL_ENV: BASE_URL, CHAT_MODEL_ENV: SERVED_MODEL_NAME}
    )
    assert settings.api_key is None


@pytest.mark.parametrize("bad", ["nonsense", "0", "-4"])
def test_an_unusable_timeout_fails_at_startup(bad: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        ChatModelSettings.from_env(
            {
                CHAT_BASE_URL_ENV: BASE_URL,
                CHAT_MODEL_ENV: SERVED_MODEL_NAME,
                CHAT_READ_TIMEOUT_ENV: bad,
            }
        )
    assert CHAT_READ_TIMEOUT_ENV in str(excinfo.value)


def test_the_completions_url_is_built_from_the_base_url() -> None:
    assert a_settings().completions_url == "http://vllm:8000/v1/chat/completions"
    assert a_settings(base_url=BASE_URL + "/").completions_url == (
        "http://vllm:8000/v1/chat/completions"
    )


def test_the_embedding_width_has_no_default_because_it_is_written_into_the_index() -> None:
    with pytest.raises(ConfigError) as excinfo:
        EmbeddingSettings.from_env(
            {
                EMBEDDING_BASE_URL_ENV: "http://embeddings:8001/v1",
                EMBEDDING_MODEL_ENV: "bge-m3",
            }
        )
    assert EMBEDDING_DIMENSIONS_ENV in str(excinfo.value)


def test_the_embedding_settings_are_a_separate_endpoint_from_the_chat_one() -> None:
    """Two runtimes on the VM, so two settings; one base url would fuse them."""
    embedding = EmbeddingSettings.from_env(
        {
            EMBEDDING_BASE_URL_ENV: "http://embeddings:8001/v1",
            EMBEDDING_MODEL_ENV: "bge-m3",
            EMBEDDING_DIMENSIONS_ENV: "1024",
        }
    )
    assert embedding.embeddings_url == "http://embeddings:8001/v1/embeddings"
    assert embedding.dimensions == 1024


# ------------------------------------------------------------------- the wire shape


def test_the_served_model_name_is_sent_verbatim() -> None:
    """The name says 72B and the weights are 32B. vLLM matches the name it serves, so
    the wrong-looking name is the correct one and "fixing" it breaks every call."""
    body = request_body(a_call(), SERVED_MODEL_NAME)
    assert body["model"] == "qwen72b"


def test_the_body_is_one_system_turn_and_one_user_turn_and_nothing_else() -> None:
    """AD-22: single-shot. No conversation to continue and no tools to call."""
    body = request_body(a_call(instruction="classify", input_text="q"), SERVED_MODEL_NAME)
    assert body["messages"] == [
        {"role": "system", "content": "classify"},
        {"role": "user", "content": "q"},
    ]
    assert body["stream"] is False
    assert "tools" not in body and "tool_choice" not in body and "functions" not in body


def test_the_body_is_deterministic_and_budgeted() -> None:
    """AD-9 and AD-17: temperature 0, a fixed seed, and the caller's output cap."""
    body = request_body(a_call(), SERVED_MODEL_NAME)
    assert body["temperature"] == 0.0
    assert isinstance(body["seed"], int)
    assert body["max_tokens"] == A_BUDGET.max_output_tokens
    assert body["n"] == 1


def test_a_free_call_carries_no_decoding_fields() -> None:
    assert decoding_fields(None) == {}


def test_json_mode_is_sent_as_response_format() -> None:
    assert decoding_fields(JsonObjectDecoding()) == {"response_format": {"type": "json_object"}}


def test_a_schema_is_sent_as_guided_json_and_as_json_mode() -> None:
    """Both, so a runtime that ignores the vLLM extension is still told it is JSON."""
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    fields = decoding_fields(JsonSchemaDecoding(schema=schema))
    assert fields["guided_json"] == schema
    assert fields["response_format"] == {"type": "json_object"}


def test_a_closed_domain_is_sent_as_guided_choice() -> None:
    fields = decoding_fields(ChoiceDecoding(choices=("latest", "compare", "trend")))
    assert fields["guided_choice"] == ["latest", "compare", "trend"]


def test_a_pattern_is_sent_as_guided_regex() -> None:
    assert decoding_fields(RegexDecoding(pattern=r"D-[A-Z]+")) == {"guided_regex": r"D-[A-Z]+"}


def test_the_request_goes_to_the_configured_completions_url_with_the_api_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion("ok"))

    with serving(handler, api_key="s3cret") as client:
        assert isinstance(client.complete(a_call()), Found)

    assert str(seen[0].url) == "http://vllm:8000/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer s3cret"
    assert json.loads(seen[0].content)["model"] == SERVED_MODEL_NAME


def test_no_authorization_header_is_sent_when_no_key_is_configured() -> None:
    """vLLM on the VM is unauthenticated; an empty Bearer is not the same as none."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion("ok"))

    with serving(handler) as client:
        client.complete(a_call())
    assert "authorization" not in seen[0].headers


# --------------------------------------------------- every failure is a typed value


def test_a_valid_answer_comes_back_as_the_callers_own_value() -> None:
    with serving(answering(completion("latest"))) as client:
        outcome = client.complete(a_call(validate=lambda text: text.strip() or None))
    assert outcome == Found("latest")


def test_a_refused_connection_becomes_model_unavailable() -> None:
    """The normal case off the VM: ``vllm`` does not resolve outside its network."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name or service not known", request=request)

    with serving(handler) as client:
        kind, detail = only_degradation(client.complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE
    assert "ConnectError" in detail


def test_a_read_timeout_becomes_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("took too long", request=request)

    with serving(handler) as client:
        kind, _ = only_degradation(client.complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE


@pytest.mark.parametrize("status", [400, 404, 422, 500, 503])
def test_any_non_200_becomes_model_unavailable_and_names_the_status(status: int) -> None:
    with serving(answering({"error": "no"}, status=status)) as client:
        kind, detail = only_degradation(client.complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE
    assert str(status) in detail


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 7}}]},
        {"choices": "not a list"},
        [1, 2, 3],
    ],
    ids=["empty", "no-choices", "no-content", "content-not-text", "choices-not-list", "not-object"],
)
def test_a_body_that_is_not_a_chat_completion_becomes_model_unavailable(payload: Any) -> None:
    """A proxy, a login page or another service on the same port all answer 200."""
    with serving(answering(payload)) as client:
        kind, _ = only_degradation(client.complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE


def test_a_body_that_is_not_json_becomes_model_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    with serving(handler) as client:
        kind, _ = only_degradation(client.complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE


def test_output_the_validator_rejects_is_discarded_and_counted() -> None:
    """AD-28: the default is discard, and every discard is counted."""
    with serving(answering(completion("{not json"))) as client:
        kind, detail = only_degradation(client.complete(a_call(validate=lambda _: None)))
    assert kind is DegradationKind.GUARD_DISCARD
    assert "{not json" in detail


def test_a_validator_that_raises_is_a_rejection_not_an_escape() -> None:
    """The port asks a validator to be total; the adapter does not trust it to be."""

    def explodes(_: str) -> str | None:
        raise ValueError("a validator nobody tested")

    with serving(answering(completion("anything"))) as client:
        kind, _ = only_degradation(client.complete(a_call(validate=explodes)))
    assert kind is DegradationKind.GUARD_DISCARD


def test_every_kind_the_chat_adapter_produces_is_in_the_closed_set() -> None:
    """Nothing here invents a kind; ``classify`` would raise if it did."""
    assert classify(DegradationKind.MODEL_UNAVAILABLE.value) is DegradationKind.MODEL_UNAVAILABLE
    assert classify(DegradationKind.GUARD_DISCARD.value) is DegradationKind.GUARD_DISCARD


def test_a_failure_is_never_an_absence() -> None:
    """findings-23/128/150: a broken component must not render as 'nothing found'."""
    with serving(answering({}, status=500)) as client:
        outcome = client.complete(a_call())
    assert isinstance(outcome, Failed)
    assert not isinstance(outcome, Absent)


def test_the_degradation_names_which_of_the_four_call_sites_failed() -> None:
    """'The model is unavailable' is not actionable; naming the site is."""
    with serving(answering({}, status=500)) as client:
        outcome = client.complete(a_call(site=CallSite.NARRATION))
    assert isinstance(outcome, Failed)
    assert outcome.degradations[0].where.endswith(CallSite.NARRATION.value)


# ----------------------------------------------------------------------- the budget


def test_a_prompt_that_cannot_fit_the_window_is_refused_without_a_round_trip() -> None:
    """The window is prompt *plus* completion. A request that cannot fit comes back
    truncated from the server, which looks like a bad answer rather than a bad request."""
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(200, json=completion("ok"))

    with serving(handler, token_budget=1000) as client:
        outcome = client.complete(a_call(input_text="x" * 40_000))
    kind, detail = only_degradation(outcome)
    assert kind is DegradationKind.MODEL_UNAVAILABLE
    assert "was not sent" in detail
    assert attempts == [], "an over-budget call must not reach the network"


def test_the_token_estimate_is_pessimistic_rather_than_optimistic() -> None:
    """Over-estimating refuses early; under-estimating is truncated mid-JSON."""
    assert estimated_tokens("") == 0
    assert estimated_tokens("x" * 100) >= 50


def test_the_adapter_makes_exactly_one_request_and_never_retries() -> None:
    """AD-8 rules out a retry loop that eventually accepts something."""
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503, json={"error": "busy"})

    with serving(handler) as client:
        client.complete(a_call())
    assert len(attempts) == 1


# ---------------------------------------------------------------------- the port shape


def test_the_client_satisfies_the_port() -> None:
    client = serving(answering(completion("ok")))
    port: ModelPort = client
    assert isinstance(port, ModelPort)
    client.close()


def test_the_fake_satisfies_the_port() -> None:
    fake: ModelPort = ScriptedModel()
    assert isinstance(fake, ModelPort)


def test_a_call_without_an_instruction_is_not_constructible() -> None:
    with pytest.raises(ValueError, match="instruction"):
        a_call(instruction="  ")


def test_a_budget_of_no_tokens_is_not_constructible() -> None:
    with pytest.raises(ValueError):
        Budget(max_output_tokens=0, connect_seconds=1.0, read_seconds=1.0)


def test_a_choice_constraint_needs_more_than_one_option() -> None:
    with pytest.raises(ValueError):
        ChoiceDecoding(choices=("only",))


def test_the_call_sites_are_the_four_ad_22_names() -> None:
    """A fifth model call site is a spine change, not a call-site decision."""
    assert {site.value for site in CallSite} == {
        "candidate_discrimination",
        "operation_classification",
        "multi_part_detection",
        "narration",
    }


# ---------------------------------------------------------------------- the fakes


def test_the_scripted_model_answers_from_its_script_through_the_real_validator() -> None:
    fake = ScriptedModel({CallSite.OPERATION_CLASSIFICATION: "latest"})
    assert fake.complete(a_call(validate=lambda text: text.upper())) == Found("LATEST")


def test_the_scripted_model_lets_a_bad_answer_be_discarded() -> None:
    """The behaviour that matters: a test can script output the validator refuses."""
    fake = ScriptedModel({CallSite.NARRATION: "invented figure"})
    kind, _ = only_degradation(
        fake.complete(a_call(site=CallSite.NARRATION, validate=lambda _: None))
    )
    assert kind is DegradationKind.GUARD_DISCARD


def test_an_unscripted_call_site_is_loud() -> None:
    kind, detail = only_degradation(ScriptedModel().complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE
    assert "nothing is scripted" in detail


def test_no_model_is_the_nfr_6_default() -> None:
    """The suite passes with no model available, and says so when asked for one."""
    kind, _ = only_degradation(no_model().complete(a_call()))
    assert kind is DegradationKind.MODEL_UNAVAILABLE


def test_the_scripted_model_records_what_it_was_asked() -> None:
    fake = ScriptedModel({CallSite.NARRATION: "prose"})
    fake.complete(a_call(site=CallSite.NARRATION))
    assert len(fake.calls) == 1
    assert fake.calls[0].site is CallSite.NARRATION


def test_two_scripted_models_do_not_share_state() -> None:
    """Instance state, never module state -- the ambient collector AD-15 forbids."""
    first, second = ScriptedModel(), ScriptedModel()
    first.complete(a_call())
    assert second.calls == ()


def test_the_scripted_model_enforces_the_same_window_as_the_real_one() -> None:
    kind, _ = only_degradation(
        ScriptedModel({CallSite.NARRATION: "ok"}, token_budget=100).complete(
            a_call(site=CallSite.NARRATION, input_text="x" * 10_000)
        )
    )
    assert kind is DegradationKind.MODEL_UNAVAILABLE


def test_the_fake_embedding_source_satisfies_the_vector_port() -> None:
    source: VectorSourcePort = FakeEmbeddingSource(dimensions=6)
    assert isinstance(source, VectorSourcePort)
    assert len(source.vectorise("inflation")) == 6


def test_the_fake_embedding_source_is_deterministic() -> None:
    """AD-17: an index built on Monday is searchable on Tuesday, in another process."""
    assert FakeEmbeddingSource(4).vectorise("x") == FakeEmbeddingSource(4).vectorise("x")


def test_the_fake_embedding_source_cannot_be_mistaken_for_a_real_one() -> None:
    assert FakeEmbeddingSource(4).identity.startswith("fake-")


def test_the_empty_string_is_the_zero_vector_not_an_error() -> None:
    assert FakeEmbeddingSource(4).vectorise("") == (0.0, 0.0, 0.0, 0.0)


# ------------------------------------------------------------- the embedding adapter


def embedding_serving(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    input_form: InputForm = InputForm.FOLDED,
    **overrides: Any,
) -> EmbeddingVectorSource:
    return EmbeddingVectorSource(
        settings=an_embedding_settings(**overrides),
        input_form=input_form,
        transport=httpx.MockTransport(handler),
    )


def embeddings_payload(*vectors: tuple[float, ...]) -> dict[str, Any]:
    return {
        "object": "list",
        "model": "bge-m3",
        "data": [
            {"object": "embedding", "index": position, "embedding": list(vector)}
            for position, vector in enumerate(vectors)
        ],
    }


def test_the_embedding_source_satisfies_the_vector_port() -> None:
    source: VectorSourcePort = embedding_serving(
        answering(embeddings_payload((1.0, 0.0, 0.0, 0.0)))
    )
    assert isinstance(source, VectorSourcePort)
    assert source.vectorise("inflation") == (1.0, 0.0, 0.0, 0.0)


def test_the_embedding_request_names_the_model_and_the_inputs() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=embeddings_payload((1.0, 0.0, 0.0, 0.0)))

    with embedding_serving(handler) as source:
        source.vectorise("inflation")
    assert str(seen[0].url) == "http://embeddings:8001/v1/embeddings"
    assert json.loads(seen[0].content) == {"model": "bge-m3", "input": ["inflation"]}


def test_the_embedding_identity_names_the_model_and_the_width() -> None:
    """``adapters/index/generation.py`` writes this into the file and compares it at
    load, so a vector source swap is a loud rebuild rather than a silent bad search."""
    source = embedding_serving(answering(embeddings_payload()), model="bge-m3", dimensions=4)
    assert "bge-m3" in source.identity
    assert "d4" in source.identity


def test_an_index_built_by_another_source_is_refused_at_load() -> None:
    """The safety net itself, exercised against the real verification function."""
    source = embedding_serving(answering(embeddings_payload()))
    with pytest.raises(IndexLoadError, match="rebuild, not a migration"):
        _verify_source(
            Path("index.sqlite3"),
            TrigramVectorSource().identity,
            source.dimensions,
            source,
        )


def test_a_width_the_model_did_not_return_is_refused_before_it_is_stored() -> None:
    """A service quietly serving a different model is what ``identity`` exists to catch;
    catching it at the request is cheaper than at the next index load."""
    source = embedding_serving(answering(embeddings_payload((1.0, 2.0))), dimensions=4)
    with pytest.raises(EmbeddingUnavailable, match="2-dimension"):
        source.vectorise("inflation")


@pytest.mark.parametrize(
    ("payload", "status"),
    [({"data": []}, 200), ({"nope": 1}, 200), ({"error": "no"}, 500), ("plain", 200)],
    ids=["no-vectors", "wrong-shape", "server-error", "not-an-object"],
)
def test_an_embedding_failure_is_typed_and_carries_its_degradation(
    payload: Any, status: int
) -> None:
    """It raises rather than returning -- the port returns a vector and a zero vector
    would read as 'unmatchable' -- but the kind is still from the closed set."""
    source = embedding_serving(answering(payload, status=status))
    with pytest.raises(EmbeddingUnavailable) as excinfo:
        source.vectorise("inflation")
    assert classify(excinfo.value.degradation.kind) is DegradationKind.ADAPTER_UNAVAILABLE


def test_an_unreachable_embedding_endpoint_raises_the_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name or service not known", request=request)

    source = EmbeddingVectorSource(
        settings=an_embedding_settings(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(EmbeddingUnavailable):
        source.vectorise("inflation")


def test_the_empty_string_needs_no_round_trip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the empty string must not be sent to the model")

    source = embedding_serving(handler)
    assert source.vectorise("") == (0.0, 0.0, 0.0, 0.0)


def test_a_batch_is_one_request_and_comes_back_in_request_order() -> None:
    """Out-of-order entries are re-sorted by their declared index: a mislabelled vector
    is an indicator wearing another indicator's name, and nothing downstream could tell."""
    scrambled = {
        "data": [
            {"index": 1, "embedding": [0.0, 1.0, 0.0, 0.0]},
            {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
        ]
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=scrambled)

    with embedding_serving(handler) as source:
        vectors = source.embed_all(("first", "second"))
    assert len(requests) == 1
    assert vectors == ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0))


def test_a_short_batch_is_refused_rather_than_matched_by_position() -> None:
    source = embedding_serving(answering(embeddings_payload((1.0, 0.0, 0.0, 0.0))))
    with pytest.raises(EmbeddingUnavailable, match="partial batch"):
        source.embed_all(("first", "second"))


def test_an_empty_batch_needs_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an empty batch must not be sent")

    assert embedding_serving(handler).embed_all(()) == ()


# ------------------------------------------ the normalisation-versus-embedding tension


def test_the_default_input_form_is_the_ports_contract() -> None:
    """AD-26 puts the single fold upstream; the default honours it without argument."""
    source = embedding_serving(answering(embeddings_payload()))
    assert source.input_form is InputForm.FOLDED
    assert InputForm.FOLDED.value in source.identity


def test_the_two_input_forms_produce_identities_that_refuse_each_other() -> None:
    """What makes running the experiment safe: an index built one way and queried the
    other does not return worse results, it does not load."""
    folded = embedding_serving(answering(embeddings_payload()))
    as_written = embedding_serving(
        answering(embeddings_payload()), input_form=InputForm.AS_WRITTEN
    )
    assert folded.identity != as_written.identity


def test_the_unfolded_arm_refuses_to_run_through_a_folded_source() -> None:
    """Otherwise the identity written into the index file would be a lie."""
    folded = embedding_serving(answering(embeddings_payload((1.0, 0.0, 0.0, 0.0))))
    with pytest.raises(ValueError, match="input form"):
        as_written_unit_vector("الأسعار", folded)


def test_both_arms_are_measurable_against_the_same_text() -> None:
    """The port is not changed to answer the question; both paths are made runnable so
    the answer is a number. The folded path is what the answer path uses; the as-written
    path shows the model the diacritics and hamza forms ``normalise()`` removes."""
    sent: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(list(json.loads(request.content)["input"]))
        return httpx.Response(200, json=embeddings_payload((1.0, 0.0, 0.0, 0.0)))

    raw = "الأسْعار"
    folded_source = embedding_serving(handler)
    unit_vector_for(raw, folded_source)

    as_written_source = embedding_serving(handler, input_form=InputForm.AS_WRITTEN)
    as_written_unit_vector(raw, as_written_source)

    assert sent[1] == [raw], "the comparison arm shows the model the published spelling"
    assert sent[0] != sent[1], "the port's arm shows it the folded form"
