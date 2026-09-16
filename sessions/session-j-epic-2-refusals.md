# Session J — Epic 2: the six refusals, and the model tie-break

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state.

With **257 of 320 names ambiguous**, refusing well is not a consolation path — it is the primary
one. An engine that asks *"did you mean Real GDP or Nominal GDP?"* is worth more than one that
picks confidently and is wrong six times in ten.

## You own

`src/askai/compile/resolve/` (the refusal side) · `corpus/epic-2.yaml` · new files under
`src/askai/rules/data/` · new message ids in **both** `messages/data/en.yaml` and `ar.yaml` ·
new test files

## What exists

- **2.1, 2.2, 2.13** — the semantic index, 1,101 indexed name surfaces with FTS5 plus vectors, and
  the labelled set with a derived floor.
- **2.3, 2.4, 2.5** — the resolution ladder: generate candidates, discriminate deterministically,
  decide. Read `compile/resolve/` fully before writing.
- `compile/binding.py` — **`UnboundReason` already exists as closed codes, not prose**, chosen so
  narrate can compose the text bilingually. Extend that vocabulary; do not start a parallel one.
- `narrate/structured.py` — `AnswerPackage` carries a `reason` field, added by Story 1.15 precisely
  because a refusal has no row to point at and `Element` cannot exist without a `source_ref`. The
  wire shape for refusals is already there and waiting.
- `ports/unpublished_catalogue.py` — names and existence only. That is 2.8's entire surface.

## Stories

| Batch | Stories | Notes |
|---|---|---|
| **1** | **2.7 + 2.9 + 2.10 + 2.11** | Six distinct refusals; never substitute, never invent; correct a premise the data contradicts; ask one specific closed question. One refusal module, one message namespace. |
| **2** | 2.8 | Improve a refusal from the unpublished catalogue **without leaking it** — "that exists but is not published" is more useful than "I do not hold that", and neither may reveal a value. |
| **3** | 2.6 | The model tie-break. |
| — | ~~2.12~~ | **Do not start.** Decision-gated on FR-51: three options, 65 of 189 indicators affected, and no option-specific acceptance criteria exist. Nothing to implement. |

## Six means six

The story says six *distinct* refusals, and the test of it is whether a reader can tell them apart:

1. I do not hold an indicator matching that
2. Several things match — which did you mean?
3. That exists, but it is not published
4. That indicator is published, but has no data for the period you asked
5. That is not a declared benchmark for this indicator
6. The question is well formed and the data cannot answer it

Collapsing any two into "I can't answer that" is the failure this story exists to prevent. Each
needs its own message id in both languages, and the closed `UnboundReason` code is what selects it.

Worked examples already grounded in the corpus: `Total Population` is the only one of the 21
declared benchmark sets with **zero** country rows — that is #5 versus #4. Two of the 28 details
with no datapoints at all are #4. `GDP` matching 15 details is #2.

## Story 2.6 — the model rung

Only reached when candidates remain genuinely tied after deterministic discrimination.

- Served name **`qwen72b`** (actually Qwen2.5-32B-Instruct — the number is wrong and the name is
  right). `max_model_len` 16384.
- `ports/model.py`'s `ModelCall[T]` carries a **required** validator. Use `guided_choice` with the
  closed candidate list **and** validate the response against that list — both, because a
  constrained decoder still returns text.
- **A failure falls back to asking**, never to guessing. The worst case of a model outage is a
  clarifying question.
- Record it as `bound_by: model` so the rung is auditable — if it starts binding too much, that
  must be visible in the data rather than a suspicion.
- Every test passes with **no model reachable** (NFR-6). `adapters/model/fakes.py` has what you need.

## Ownership

Do NOT edit `pyproject.toml`, `uv.lock`, any existing test file, or anything under
`src/askai/domain/`, `execute/`, `assemble/`, `adapters/`, `refresh/`, `_bmad-output/` or `docs/`.
All five gates must pass, and `uv run python tests/corpus_runner.py` must stay deterministic — it
compiles all 86 entries twice and fails on any difference.
