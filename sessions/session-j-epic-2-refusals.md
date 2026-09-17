# Session J — Epic 2: the six refusals, and the model tie-break

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

**257 of 320 names are ambiguous.** Refusing well is the primary path, not a consolation one. An
engine that asks *"did you mean Real GDP or Nominal GDP?"* beats one that picks and is wrong six
times in ten.

## Own

`compile/resolve/` (the refusal side) · `corpus/epic-2.yaml` · new `rules/data/` files ·
new message ids in **both** `messages/data/en.yaml` and `ar.yaml` · new test files

## Build on

- **2.1, 2.2, 2.13** — the index, 1,101 name surfaces, the labelled set and a derived floor.
- **2.3, 2.4, 2.5** — the ladder. Read `compile/resolve/` fully first.
- `compile/binding.py` — **`UnboundReason` already exists as closed codes, not prose**, so narrate
  composes the text bilingually. Extend it; do not start a parallel vocabulary.
- `narrate/structured.py` — `AnswerPackage` has a `reason` field, added by 1.15 because a refusal
  has no row to point at and `Element` cannot exist without a `source_ref`. The wire shape is ready.
- `ports/unpublished_catalogue.py` — names and existence only. That is 2.8's entire surface.

## Stories

| Batch | Stories |
|---|---|
| 1 | **2.7 + 2.9 + 2.10 + 2.11** — six refusals; never substitute or invent; correct a premise the data contradicts; ask one closed question |
| 2 | 2.8 — improve a refusal from the unpublished catalogue **without leaking it** |
| 3 | 2.6 — the model tie-break |
| — | ~~2.12~~ — **do not start.** Decision-gated on FR-51; no option-specific criteria exist |

## Six means six

The test is whether a reader can tell them apart:

1. I do not hold an indicator matching that
2. Several match — which did you mean?
3. That exists, but is not published
4. Published, but no data for the period you asked
5. Not a declared benchmark for this indicator
6. Well formed, and the data cannot answer it

Collapsing any two into "I can't answer that" is the failure this story prevents. Each needs its own
message id in both languages, selected by the closed `UnboundReason` code.

Worked examples already in the corpus: `Total Population` is the only one of 21 declared benchmark
sets with **zero** country rows (#5 vs #4). Two of the 28 details with no datapoints are #4. `GDP`
matching 15 details is #2.

## Story 2.6 — the model rung

Reached only when candidates stay tied after deterministic discrimination.

- Served name **`qwen72b`** (weights are Qwen2.5-32B-Instruct — the number is wrong, the name is
  right). `max_model_len` 16384.
- `ModelCall[T]` carries a **required** validator. Use `guided_choice` over the closed candidate
  list **and** validate the response against it.
- **A failure falls back to asking, never guessing.** Worst case of an outage is a clarifying
  question.
- Record `bound_by: model` so the rung is auditable — over-binding must be visible in data.
- Every test passes with **no model reachable** (NFR-6); `adapters/model/fakes.py` has what you need.

## Verify

All five gates, and `uv run python tests/corpus_runner.py` must stay deterministic — it compiles all
86 entries twice and fails on any difference.
