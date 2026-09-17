"""Story 2.6 -- the model tie-break: parsed, validated, and discarded on failure.

Every test here runs with **no model reachable** (NFR-6). The runtime on the target VM
resolves only inside its own Docker network, so a test that needed one would be a test
nobody could run; the fakes in ``adapters/model/fakes.py`` run the caller's *real*
validator over scripted text, which is what makes "the validator rejected it" a thing a
test can watch happen rather than a thing a mock asserts about.

Three assertions are written against the plausible wrong implementation rather than
against the happy path, because the happy path passes either way:

**"There is no retry loop that eventually accepts something."** Asserting that a rejected
output produces a disambiguation passes on an implementation that retried three times and
then gave up. So the assertion is on the *number of calls made*, over a port that records
them.

**"The validator runs on every call regardless."** Asserting that unparseable text is
rejected passes on an implementation that only parses. So the assertion is made with a
**well-formed JSON object naming an id that does not exist** -- the output JSON mode
cannot catch and a constrained decoder is supposed to have made impossible.

**"A failure falls back to asking, never guessing."** Asserting that the result is not a
``Resolved`` passes on an implementation that returned a refusal. So the assertion is that
the outcome is the *same* ``Disambiguation`` object that went in, unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from askai.adapters.model.chat import decoding_fields, request_body
from askai.adapters.model.fakes import ScriptedModel, no_model
from askai.adapters.model.prompts import (
    PROMPT_DIR,
    PromptClause,
    PromptError,
    PromptRule,
    VersionedPrompt,
    digest_of,
    load_prompt,
    tie_break_prompt,
    verify_prompts,
)
from askai.adapters.model.tiebreak import (
    TieBreak,
    break_tie,
    candidate_listing,
    chosen_from,
    maximum_candidates_listed,
    tie_break_budget,
)
from askai.compile.binding import BoundBy
from askai.compile.resolve import Disambiguation, QuestionSignals, Resolved, decide, discriminate
from askai.compile.resolve.decide import Offered
from askai.compile.resolve.discriminate import SignalName
from askai.compile.resolve.generate import subject_of
from askai.config.model import DEFAULT_TOKEN_BUDGET
from askai.domain.degradation import Degradation
from askai.messages.lang import Lang
from askai.observability.degradations import (
    Absent,
    DegradationKind,
    Failed,
    Found,
    Outcome,
    Tally,
    degrade,
)
from askai.ports.model import (
    CallSite,
    ChoiceDecoding,
    JsonObjectDecoding,
    ModelCall,
    ModelPort,
)
from askai.ports.resolution import Candidate, CandidateFacts, MatchedSurface, UnitShape

QUESTION: Final = "what was the contribution to gdp"

#: The two details a reader cannot tell apart, and neither can the deterministic ladder.
REAL: Final = "detail-real-gdp"
NOMINAL: Final = "detail-nominal-gdp"


# ---------------------------------------------------------------------------- fixtures


def _offered(detail_id: str, surface: str, score: float = 1.0) -> Offered:
    return Offered(
        detail_id=detail_id, indicator_id=f"i-{detail_id}", surface=surface, score=score
    )


def _tie(*ids: str) -> Disambiguation:
    """A tie over *ids*, in the shape ``decide`` produces one."""
    return Disambiguation(
        candidates=tuple(_offered(detail_id, f"{detail_id} surface") for detail_id in ids),
        signals_that_spoke=(SignalName.CONTENT_OVERLAP,),
    )


def _two() -> Disambiguation:
    return Disambiguation(
        candidates=(_offered(REAL, "real gdp"), _offered(NOMINAL, "nominal gdp")),
        signals_that_spoke=(SignalName.CONTENT_OVERLAP,),
    )


def _answered(text: str) -> ScriptedModel:
    return ScriptedModel({CallSite.CANDIDATE_DISCRIMINATION: text})


class SequencedModel:
    """A ``ModelPort`` that answers a scripted *sequence* of outcomes, and counts calls.

    ``ScriptedModel`` answers the same way every time, which is exactly right for one
    call and cannot express "the server rejected the first request and took the second".
    This is the smallest thing that can, and it is deliberately unforgiving: a call past
    the end of the script is an assertion failure rather than another copy of the last
    answer, so an implementation that looped would fail here rather than pass quietly.
    """

    def __init__(self, outcomes: Sequence[Outcome[Any]]) -> None:
        self._outcomes = list(outcomes)
        self._calls: list[ModelCall[Any]] = []

    @property
    def calls(self) -> tuple[ModelCall[Any], ...]:
        return tuple(self._calls)

    def complete[T](self, call: ModelCall[T]) -> Outcome[T]:
        self._calls.append(call)
        if len(self._calls) > len(self._outcomes):
            raise AssertionError(
                f"call {len(self._calls)} to the model was made and the script holds "
                f"{len(self._outcomes)}; AD-8 forbids a retry loop"
            )
        outcome = self._outcomes[len(self._calls) - 1]
        if isinstance(outcome, Found):
            # The scripted *text* still goes through the caller's real validator, so a
            # test cannot accidentally assert on a value the validator would have refused.
            validated = call.validate(str(outcome.value))
            if validated is None:
                return Failed(
                    (
                        degrade(
                            DegradationKind.GUARD_DISCARD,
                            "tests/sequenced",
                            f"the validator rejected {outcome.value!r}",
                        ),
                    )
                )
            return Found(validated)
        return outcome


def _refused(detail: str = "the server answered 400: unknown field guided_choice") -> Failed:
    return Failed((degrade(DegradationKind.MODEL_UNAVAILABLE, "tests/sequenced", detail),))


def _discarded(detail: str = "the validator rejected the output") -> Failed:
    return Failed((degrade(DegradationKind.GUARD_DISCARD, "tests/sequenced", detail),))


# ============================================================ the prompt (AD-29)


def test_the_published_prompt_loads_and_carries_its_identity() -> None:
    published = tie_break_prompt()
    assert published.prompt_id == "candidate-tie-break"
    assert published.version == "1"
    assert published.identity == "candidate-tie-break@1"
    assert published.text.strip()


def test_the_prompt_file_on_disk_is_the_one_the_rule_records() -> None:
    """The digest is the whole of "immutable"; a rule recording someone else's hash is
    a rule that proves nothing."""
    published = tie_break_prompt()
    path = PROMPT_DIR / f"{published.prompt_id}.v{published.version}.md"
    assert path.is_file()
    assert digest_of(path.read_text(encoding="utf-8")) == published.prompt_hash


def test_the_prompt_is_versioned_in_its_filename_so_a_second_version_sits_beside_it() -> None:
    """AD-29: *a change is a new version, never an edit.* Enforced by the naming, so
    version 2 cannot be written without leaving version 1 in place."""
    published = tie_break_prompt()
    assert f".v{published.version}." in (
        PROMPT_DIR / f"{published.prompt_id}.v{published.version}.md"
    ).name


def test_prompt_and_version_and_hash_are_recorded_on_the_answer() -> None:
    """AD-16/AD-29: a card questioned months later traces to exactly what the model
    was told."""
    outcome = break_tie(QUESTION, _two(), _answered(REAL))
    assert outcome.prompt.prompt_id == "candidate-tie-break"
    assert outcome.prompt.version == "1"
    assert outcome.prompt.prompt_hash == tie_break_prompt().prompt_hash


def test_the_prompt_is_recorded_even_when_its_output_was_discarded() -> None:
    """A discarded output is still an output this prompt produced. Recording it only on
    success would make the rising discard rate untraceable to the prompt that caused it."""
    outcome = break_tie(QUESTION, _two(), _answered("an indicator i invented"))
    assert outcome.bound_by is None
    assert outcome.prompt.prompt_hash == tie_break_prompt().prompt_hash


def test_a_missing_prompt_fails_loudly_rather_than_falling_back(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="does not exist"):
        load_prompt(PromptRule.TIE_BREAK, tmp_path)


def test_an_altered_prompt_fails_loudly_rather_than_being_sent(tmp_path: Path) -> None:
    """The failure AD-29's digest exists for: the right filename, the wrong words."""
    published = tie_break_prompt()
    tampered = tmp_path / f"{published.prompt_id}.v{published.version}.md"
    tampered.write_text(published.text + "\nAlso, feel free to guess.\n", encoding="utf-8")
    with pytest.raises(PromptError, match="immutable"):
        load_prompt(PromptRule.TIE_BREAK, tmp_path)


def test_a_prompt_altered_by_one_character_is_caught(tmp_path: Path) -> None:
    published = tie_break_prompt()
    tampered = tmp_path / f"{published.prompt_id}.v{published.version}.md"
    tampered.write_text(published.text.replace("exactly one", "any"), encoding="utf-8")
    with pytest.raises(PromptError):
        load_prompt(PromptRule.TIE_BREAK, tmp_path)


def test_an_empty_prompt_file_is_refused(tmp_path: Path) -> None:
    """An empty instruction is a call with no closed domain stated. It fails as a bad
    digest first, which is the same refusal for a better reason."""
    published = tie_break_prompt()
    (tmp_path / f"{published.prompt_id}.v{published.version}.md").write_text("", encoding="utf-8")
    with pytest.raises(PromptError):
        load_prompt(PromptRule.TIE_BREAK, tmp_path)


def test_an_empty_prompt_cannot_be_constructed_even_past_the_digest() -> None:
    with pytest.raises(PromptError, match="empty"):
        VersionedPrompt(prompt_id="p", version="1", prompt_hash="abc", text="   \n")


def test_verify_prompts_loads_every_declared_prompt() -> None:
    """The startup check. Every member of the closed set resolves to a real file."""
    verified = verify_prompts()
    assert len(verified) == len(list(PromptRule))
    assert {prompt.identity for prompt in verified} == {"candidate-tie-break@1"}


def test_verify_prompts_refuses_a_directory_that_holds_none(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        verify_prompts(tmp_path)


def test_the_prompt_clauses_are_read_from_the_rule_rather_than_from_code() -> None:
    """AD-11/AD-29: which version is active is configuration, so a rollback is a data
    edit rather than a deploy."""
    assert {clause.value for clause in PromptClause} == {"prompt_id", "version", "sha256"}


def test_the_prompt_forbids_naming_an_indicator_of_its_own() -> None:
    """The instruction is reviewable text, and this is the sentence being reviewed."""
    text = tie_break_prompt().text.lower()
    assert "never return an id that is not on the list" in text
    assert "exactly one candidate" in text


# ============================================================ the budget (AD-9)


def test_one_call_is_budgeted_and_abandonable() -> None:
    budget = tie_break_budget()
    assert budget.max_output_tokens > 0
    assert budget.connect_seconds > 0.0
    assert budget.read_seconds > 0.0


def test_the_two_requests_together_stay_inside_the_declared_wall_clock() -> None:
    """*"A single in-budget fallback."* Each request gets a share, so a runtime that is
    simply down cannot cost twice the time a reviewer signed off."""
    from askai.rules import rules

    declared = rules().value("R-MODEL-TIE-BREAK-BUDGET", "read_timeout_seconds")
    assert isinstance(declared, int)
    assert tie_break_budget().read_seconds * 2 == pytest.approx(float(declared))


def test_the_budget_leaves_no_room_for_an_explanation() -> None:
    """The answer is one catalogue id. A model that starts explaining is truncated, the
    validator rejects it, and the reader is asked -- which is the intended outcome."""
    assert tie_break_budget().max_output_tokens < 100


def test_the_whole_call_fits_the_served_runtimes_window() -> None:
    """``max_model_len`` is 16384 for prompt **plus** completion. The candidate listing is
    the only part of this prompt that grows, and it is capped."""
    widest = _tie(*[f"detail-{index}" for index in range(maximum_candidates_listed())])
    model = ScriptedModel(
        {CallSite.CANDIDATE_DISCRIMINATION: "detail-0"}, token_budget=DEFAULT_TOKEN_BUDGET
    )
    outcome = break_tie(QUESTION, widest, model)
    assert isinstance(outcome.resolution, Resolved)


def test_a_tie_wider_than_the_rule_allows_is_never_put_to_the_model() -> None:
    """The window is shared between prompt and completion, so the listing is capped
    before a round trip rather than after a truncation."""
    too_many = _tie(*[f"detail-{index}" for index in range(maximum_candidates_listed() + 1)])
    model = _answered("detail-0")
    outcome = break_tie(QUESTION, too_many, model)
    assert outcome.resolution is too_many
    assert model.calls == ()
    assert Tally.of(outcome.degradations).count(DegradationKind.GUARD_DISCARD) == 1


def test_a_single_candidate_is_not_a_tie_and_is_not_asked_about() -> None:
    model = _answered(REAL)
    outcome = break_tie(QUESTION, _tie(REAL), model)
    assert outcome.bound_by is None
    assert model.calls == ()


def test_a_repeated_candidate_id_is_refused_rather_than_constrained_on() -> None:
    """``guided_choice`` refuses a repeated option, and a list that would raise must
    never reach the port."""
    repeated = Disambiguation(
        candidates=(_offered(REAL, "real gdp"), _offered(REAL, "real gdp, again")),
        signals_that_spoke=(),
    )
    model = _answered(REAL)
    outcome = break_tie(QUESTION, repeated, model)
    assert outcome.bound_by is None
    assert model.calls == ()


# ============================================================ the call (AD-9, AD-22)


def test_the_call_goes_out_at_the_declared_call_site() -> None:
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    assert model.calls[0].site is CallSite.CANDIDATE_DISCRIMINATION


def test_the_decoder_is_constrained_to_the_supplied_ids_and_nothing_else() -> None:
    """``guided_choice`` over the closed candidate list -- the same list the validator
    checks against, so the constraint and the check cannot drift."""
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    decoding = model.calls[0].decoding
    assert isinstance(decoding, ChoiceDecoding)
    assert decoding.choices == (REAL, NOMINAL)


def test_the_constraint_reaches_the_wire_as_guided_choice() -> None:
    """Asserted through the real body builder, so the wire name is pinned rather than
    assumed."""
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    body = request_body(model.calls[0], "qwen72b")
    assert body["guided_choice"] == [REAL, NOMINAL]
    assert body["model"] == "qwen72b"


def test_json_mode_is_the_openai_field_and_the_fallback_sends_it() -> None:
    """``response_format: {"type": "json_object"}``, which every OpenAI-compatible server
    takes, is what the one fallback uses when the vLLM extension is refused."""
    assert decoding_fields(JsonObjectDecoding()) == {"response_format": {"type": "json_object"}}
    model = SequencedModel([_refused(), Found(REAL)])
    break_tie(QUESTION, _two(), model)
    assert isinstance(model.calls[1].decoding, JsonObjectDecoding)


def test_the_candidate_listing_names_every_candidate_and_no_other() -> None:
    listing = candidate_listing(QUESTION, _two())
    assert QUESTION in listing
    assert REAL in listing and NOMINAL in listing
    assert "real gdp" in listing and "nominal gdp" in listing


def test_exactly_one_request_is_made_when_the_model_answers() -> None:
    """AD-22: no component loops. One request, one answer, no second turn."""
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    assert len(model.calls) == 1


def test_the_two_messages_carry_no_tools_and_no_conversation() -> None:
    """AD-22 by shape: there is nothing in the body to build a loop out of."""
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    body = request_body(model.calls[0], "qwen72b")
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert "tools" not in body
    assert body["stream"] is False


# ============================================================ the validator (AD-8)


def test_the_model_binds_the_candidate_it_chose() -> None:
    outcome = break_tie(QUESTION, _two(), _answered(NOMINAL))
    assert isinstance(outcome.resolution, Resolved)
    assert outcome.resolution.detail_id == NOMINAL
    assert outcome.resolution.indicator_id == f"i-{NOMINAL}"
    assert outcome.degradations == ()


def test_a_json_object_naming_a_supplied_id_is_accepted() -> None:
    outcome = break_tie(QUESTION, _two(), _answered(json.dumps({"detail_id": REAL})))
    assert isinstance(outcome.resolution, Resolved)
    assert outcome.resolution.detail_id == REAL


def test_a_well_formed_object_naming_an_invented_id_is_rejected() -> None:
    """The case JSON mode cannot catch, and the reason the validator runs regardless."""
    invented = json.dumps({"detail_id": "detail-the-model-made-up"})
    outcome = break_tie(QUESTION, _two(), _answered(invented))
    assert outcome.resolution is not None
    assert not isinstance(outcome.resolution, Resolved)


def test_output_truncated_at_the_token_budget_is_rejected_rather_than_repaired() -> None:
    """A constrained decoder still returns text over a channel that truncates."""
    outcome = break_tie(QUESTION, _two(), _answered('{"detail_id": "detail-real-g'))
    assert not isinstance(outcome.resolution, Resolved)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "I think you mean Real GDP.",
        "detail-real-gdp, detail-nominal-gdp",
        "DETAIL-REAL-GDP",
        '{"detail": "detail-real-gdp"}',
        '{"detail_id": 7}',
        '["detail-real-gdp"]',
        "null",
    ],
)
def test_the_parser_is_total_and_the_domain_is_closed(text: str) -> None:
    """Handed anything at all, the validator answers rather than raising, and it only
    ever answers with an id that was supplied."""
    validate = chosen_from((REAL, NOMINAL))
    assert validate(text) is None


@pytest.mark.parametrize("text", [REAL, f"  {REAL}  ", '{"detail_id": "detail-real-gdp"}'])
def test_the_validator_accepts_the_two_shapes_the_prompt_asks_for(text: str) -> None:
    assert chosen_from((REAL, NOMINAL))(text) == REAL


def test_the_validator_is_required_by_the_type_so_it_cannot_be_skipped() -> None:
    """AD-8's floor is a field on ``ModelCall``, not a convention at the call site."""
    model = _answered(REAL)
    break_tie(QUESTION, _two(), model)
    assert model.calls[0].validate("detail-not-offered") is None
    assert model.calls[0].validate(REAL) == REAL


# ============================================================ the fallback (AD-8)


def test_a_rejected_output_falls_back_to_asking_rather_than_guessing() -> None:
    tied = _two()
    outcome = break_tie(QUESTION, tied, _answered("something else entirely"))
    assert outcome.resolution is tied
    assert outcome.bound_by is None


def test_a_rejected_output_is_never_retried_into_an_acceptance() -> None:
    """*"There is no retry loop that eventually accepts something."* Asserted on the
    number of calls: an implementation that retried would reach the second script entry
    and bind."""
    model = SequencedModel([_discarded(), Found(REAL)])
    outcome = break_tie(QUESTION, _two(), model)
    assert len(model.calls) == 1
    assert outcome.bound_by is None


def test_a_server_that_refuses_the_extension_gets_exactly_one_more_request() -> None:
    """*"A single in-budget fallback when the server rejects it."* One, and then done."""
    model = SequencedModel([_refused(), Found(NOMINAL)])
    outcome = break_tie(QUESTION, _two(), model)
    assert len(model.calls) == 2
    assert isinstance(outcome.resolution, Resolved)
    assert outcome.resolution.detail_id == NOMINAL


def test_the_validator_runs_on_the_fallback_call_too() -> None:
    """*"The validator runs on every call regardless."* JSON mode guarantees syntax,
    never truth."""
    model = SequencedModel([_refused(), Found('{"detail_id": "detail-invented"}')])
    outcome = break_tie(QUESTION, _two(), model)
    assert outcome.bound_by is None


def test_the_fallback_is_not_made_twice() -> None:
    model = SequencedModel([_refused(), _refused()])
    outcome = break_tie(QUESTION, _two(), model)
    assert len(model.calls) == 2
    assert outcome.bound_by is None


def test_a_degradation_from_the_first_request_survives_a_successful_fallback() -> None:
    """The fallback worked and something still went wrong; hiding it would make a server
    quietly refusing the extension invisible until it refused everything."""
    model = SequencedModel([_refused(), Found(REAL)])
    outcome = break_tie(QUESTION, _two(), model)
    assert isinstance(outcome.resolution, Resolved)
    assert Tally.of(outcome.degradations).count(DegradationKind.MODEL_UNAVAILABLE) == 1


def test_an_outage_falls_back_to_asking_with_a_counted_degradation() -> None:
    tied = _two()
    outcome = break_tie(QUESTION, tied, no_model())
    assert outcome.resolution is tied
    assert outcome.bound_by is None
    assert Tally.of(outcome.degradations).total >= 1


def test_a_port_that_answers_absent_is_read_as_a_failure_not_as_a_nothing() -> None:
    """AD-15: the findings-23/128/150 confusion, foreclosed on this rung too."""
    absent = Absent(reason="the runtime had nothing to say")
    model = SequencedModel([absent, absent])
    outcome = break_tie(QUESTION, _two(), model)
    assert outcome.bound_by is None
    # Two, because an unusable answer is a request the runtime did not take, which is the
    # one condition the single decoding fallback exists for.
    assert Tally.of(outcome.degradations).count(DegradationKind.MODEL_UNAVAILABLE) == 2


def test_the_worst_case_of_an_outage_is_the_question_the_ladder_already_asked() -> None:
    """The declared fallback is not a refusal and is not a shorter list: it is the very
    disambiguation the deterministic ladder produced, unchanged."""
    tied = _two()
    outcome = break_tie(QUESTION, tied, no_model())
    assert outcome.resolution == tied
    assert getattr(outcome.resolution, "candidates", ()) == tied.candidates


def test_every_fallback_carries_at_least_one_counted_degradation() -> None:
    """Enforced by the type, so a path added later cannot fall back silently."""
    with pytest.raises(ValueError, match="counted nothing"):
        TieBreak(
            resolution=_two(),
            bound_by=None,
            degradations=(),
            prompt=tie_break_prompt().use,
        )


def test_a_binding_without_an_authority_cannot_be_recorded() -> None:
    with pytest.raises(ValueError, match="binds and says so"):
        TieBreak(
            resolution=Resolved(
                detail_id=REAL,
                indicator_id="i",
                score=1.0,
                matched_surface="real gdp",
                decided_by=(),
            ),
            bound_by=None,
            degradations=(_unavailable(),),
            prompt=tie_break_prompt().use,
        )


def _unavailable() -> Degradation:
    return degrade(DegradationKind.MODEL_UNAVAILABLE, "tests", "for the invariant above")


# ============================================================ auditability (FR-14)


def test_a_tie_broken_by_the_model_is_recorded_as_bound_by_the_model() -> None:
    """Over-binding must be visible in the data, not argued about."""
    outcome = break_tie(QUESTION, _two(), _answered(REAL))
    assert outcome.bound_by is BoundBy.MODEL


def test_a_tie_not_broken_by_the_model_records_no_authority_at_all() -> None:
    outcome = break_tie(QUESTION, _two(), no_model())
    assert outcome.bound_by is None


def test_the_bound_detail_carries_the_surface_the_reader_would_have_been_offered() -> None:
    """Nothing is re-derived here: the audit record shows the same surface and score the
    disambiguation would have shown."""
    tied = _two()
    outcome = break_tie(QUESTION, tied, _answered(NOMINAL))
    assert isinstance(outcome.resolution, Resolved)
    assert outcome.resolution.matched_surface == "nominal gdp"
    assert outcome.resolution.score == tied.candidates[1].score


# ============================================================ determinism (NFR-1)


def test_the_same_tie_and_the_same_answer_resolve_the_same_way_twice() -> None:
    """The corpus runner compiles every entry twice and fails on any difference."""
    first = break_tie(QUESTION, _two(), _answered(REAL))
    second = break_tie(QUESTION, _two(), _answered(REAL))
    assert first == second


def test_the_listing_put_to_the_model_is_byte_identical_across_runs() -> None:
    assert candidate_listing(QUESTION, _two()) == candidate_listing(QUESTION, _two())


def test_the_request_body_is_identical_across_runs() -> None:
    """``temperature`` 0 and a fixed seed are the adapter's; the body around them must
    not move either, or the corpus gate could not tell a regression from noise."""
    first, second = _answered(REAL), _answered(REAL)
    break_tie(QUESTION, _two(), first)
    break_tie(QUESTION, _two(), second)
    assert request_body(first.calls[0], "qwen72b") == request_body(second.calls[0], "qwen72b")


# ============================================================ the rung's place (AD-25)


def test_the_rung_takes_what_stage_three_produced_and_nothing_else() -> None:
    """It is reached only where stage 2 left a genuine tie: its input is the ladder's own
    ``Disambiguation``, so there is no way to call it on a question that resolved."""
    tied = decide(discriminate(_candidates(), QuestionSignals(subject=subject_of(QUESTION))))
    assert isinstance(tied, Disambiguation)
    outcome = break_tie(QUESTION, tied, _answered(tied.candidates[0].detail_id))
    assert isinstance(outcome.resolution, Resolved)
    assert outcome.resolution.detail_id == tied.candidates[0].detail_id


def test_a_resolved_question_never_reaches_this_rung() -> None:
    """Stage 3 binds it, and a ``Resolved`` is not something ``break_tie`` can be handed:
    ``mypy --strict`` refuses the call, and this asserts the ladder produces one."""
    alone = (_candidate("only", surfaces=("gross domestic product",)),)
    assert isinstance(
        decide(discriminate(alone, QuestionSignals(subject=subject_of(QUESTION)))), Resolved
    )


def test_nothing_in_the_resolution_ladder_reaches_this_module() -> None:
    """NFR-5, from the other side: stages 1 and 2 run with no model, and the reason is
    that there is nothing in them to take away."""
    ladder = Path(str(__import__("askai.compile.resolve", fromlist=["x"]).__path__[0]))
    for module in sorted(ladder.glob("*.py")):
        text = module.read_text(encoding="utf-8")
        assert "tiebreak" not in text, f"{module.name} reaches the model rung"


def _candidates() -> tuple[Candidate, ...]:
    """Two candidates nothing in the question can tell apart -- a genuine tie."""
    return (
        _candidate("real", surfaces=("gross domestic product real",)),
        _candidate("nominal", surfaces=("gross domestic product nominal",)),
    )


def _candidate(detail_id: str, *, surfaces: Sequence[str]) -> Candidate:
    return Candidate(
        detail_id=detail_id,
        indicator_id=f"i-{detail_id}",
        score=1.0,
        matched=MatchedSurface(kind="detail_name", lang=Lang.EN, text=surfaces[0]),
        facts=CandidateFacts(unit_shape=UnitShape.UNKNOWN),
        surfaces=tuple(surfaces),
    )


# ============================================================ NFR-6


def test_the_whole_rung_is_exercised_with_no_model_reachable() -> None:
    """Every test in this file runs against a fake. This one states it."""
    for model in (_answered(REAL), no_model(), SequencedModel([_refused(), _refused()])):
        outcome = break_tie(QUESTION, _two(), model)
        assert isinstance(outcome, TieBreak)


def test_the_port_is_the_only_thing_this_rung_knows_about_the_runtime() -> None:
    """AD-9: no module outside ``adapters/model/`` knows the protocol -- and inside it,
    the rung still reaches the runtime through the port rather than through a client."""
    assert isinstance(_answered(REAL), ModelPort)
    assert isinstance(SequencedModel([]), ModelPort)
