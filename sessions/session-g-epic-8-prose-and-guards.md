# Session G — Epic 8: generated prose, and the four guards

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state.

This is the epic that lets the engine speak in sentences rather than templates. It is also the
epic where a mistake produces a confident, fluent, wrong answer — so the guards are not overhead,
they are the reason the prose is allowed to exist at all.

## Start with the guards. They need no model.

**Stories 8.2–8.5 are pure and model-free**, and you should build them before anything that calls
a model. Each takes composed prose and an already-composed `Answer` and returns a verdict:

| Story | The guard |
|---|---|
| 8.2 | Every number in the prose is in the answer |
| 8.3 | Every entity in the prose is in the spec |
| 8.4 | No relational or causal claim without a matching element |
| 8.5 | Prose may **narrow** the answer; it may never widen it |

8.2 and 8.3 are set membership and are durable — real model output will not change them. 8.4 and
8.5 need judgement about what a claim *is*; build them against prose you write by hand, and expect
to tune them once real output exists. Say in your report which cases you guessed at.

**A discard is a counted `Degradation`, never a silent drop**, and the answer falls back to the
structured form — which is what ships today and what NFR-8 requires permanently.

## Then the model

`http://vllm:8000/v1/chat/completions`, served name **`qwen72b`**, actually Qwen2.5-32B-Instruct.
**`max_model_len` is 16384 — prompt plus completion together.** The narration prompt carries a
composed answer; measure it against the real tokenizer on the VM, because
`adapters/model/chat.py`'s estimate is a pessimistic chars/2 and not a tokenizer.

Everything you need is built and fake-tested:
- `ports/model.py` — `ModelCall[T]` carries a **required** validator, so AD-8's "the validator runs
  on every call" is a signature rather than a convention. You cannot construct a call without one.
- `adapters/model/chat.py` — guided decoding (`guided_json`, `guided_choice`, `response_format`)
  **and** the validator. Both, not either: a constrained decoder still returns text.
- `adapters/model/fakes.py` — `ScriptedModel`, `no_model()`. **Every test must pass with no model
  reachable** (NFR-6). Nothing outside the VM's Docker network can reach vLLM.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **8.2 + 8.3 + 8.4 + 8.5** | The four guards, one pipeline, one test file. No model. Start here. |
| **2** | 8.1 | Narrate from the composed answer **and only from it**. The first real model call. |
| **3** | 8.6 + 8.7 | State when the answer is narrower than the question; proportionality testable on structure. |
| **4** | 8.8 + 8.9 | Two lenses over one bound answer, and what each must and must not drop. |

`rules/data/answer-roles.yaml` already carries the lens mapping from Story 1.14, with `scope` in
**both** lenses deliberately — removing it is the one edit to refuse.

## The constraint that defines this epic

**The model reorganises. It never adds.** It receives an already-composed answer and writes prose
from that and nothing else. Every number, entity and period must already have been decided by
`compile/`, `execute/` and `assemble/` before the model sees anything.

A scan already fails the build on a model-client import anywhere on the answer path outside its
adapter. Reach the model through `ModelPort` or you will not build.

## Ownership

`src/askai/narrate/` · new files under `src/askai/rules/data/` · new message ids in **both**
`messages/data/en.yaml` and `ar.yaml` · `corpus/epic-8.yaml` · new test files.

Do NOT edit `pyproject.toml`, `uv.lock`, any existing test file, or anything under
`src/askai/domain/`, `compile/`, `execute/`, `assemble/`, `adapters/`, `_bmad-output/` or `docs/`.

Note: another session may be wiring operation dispatch in `narrate/`. Check `git log` before you
start and coordinate on `narrate/structured.py` specifically.
