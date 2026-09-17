# Session G — Epic 8: generated prose, and the four guards

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

## Build the guards first — they need no model

| Story | Guard |
|---|---|
| 8.2 | Every number in the prose is in the answer |
| 8.3 | Every entity in the prose is in the spec |
| 8.4 | No relational or causal claim without a matching element |
| 8.5 | Prose may **narrow** the answer, never widen it |

8.2 and 8.3 are set membership and are durable. 8.4 and 8.5 need judgement about what a *claim*
is — build them against prose you write by hand and **say in your report which cases you guessed
at**, because real model output will differ.

A discard is a counted `Degradation`, never a silent drop, and the answer falls back to the
structured form — which is what ships today and what NFR-8 requires permanently.

## Then the model

`http://vllm:8000/v1/chat/completions`. Served name **`qwen72b`**; the weights are
Qwen2.5-32B-Instruct. **The number in the name is wrong and the name is right** — vLLM rejects a
mismatch. `max_model_len` **16384, prompt plus completion together**; measure the narration prompt
against the real tokenizer on the VM, because `chat.py`'s estimate is a pessimistic chars/2.

- `ports/model.py` — `ModelCall[T]` carries a **required** validator. You cannot construct a call
  without one.
- `adapters/model/chat.py` — guided decoding **and** the validator. Both: a constrained decoder
  still returns text.
- `adapters/model/fakes.py` — every test must pass with **no model reachable** (NFR-6). Nothing
  outside the VM's Docker network can reach vLLM.

## Stories

| Batch | Stories |
|---|---|
| 1 | **8.2 + 8.3 + 8.4 + 8.5** — one pipeline, one test file, no model |
| 2 | 8.1 — narrate from the composed answer and only from it |
| 3 | 8.6 + 8.7 — state when the answer is narrower than the question; proportionality on structure |
| 4 | 8.8 + 8.9 — two lenses, and what each must and must not drop |

`rules/data/answer-roles.yaml` already holds the lens mapping (Story 1.14), with `scope` in **both**
lenses deliberately — removing it is the one edit to refuse.

## The constraint that defines this epic

**The model reorganises; it never adds.** Every number, entity and period is decided by `compile/`,
`execute/` and `assemble/` before the model sees anything. A scan already fails the build on a
model-client import on the answer path outside its adapter.

## Own

`narrate/` · new `rules/data/` files · new message ids in **both** `messages/data/en.yaml` and
`ar.yaml` · `corpus/epic-8.yaml` · new test files.

`narrate/dispatch.py` and `structured.py` are live — check `git log` and coordinate before editing.
