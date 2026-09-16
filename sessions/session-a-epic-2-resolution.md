# Session A — Epic 2: resolution and refusal

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state. This brief
carries only what is specific to you.

You own the most important remaining work in the project. Until the resolution ladder exists, the
engine answers only questions that name an indicator exactly — and **257 of 320 names are
ambiguous**. Every other epic assumes the question bound to the right indicator first.

## You own

`src/askai/compile/resolve/` · `src/askai/adapters/index/` · `corpus/epic-2.yaml` ·
new files under `src/askai/rules/data/` · new test files

Do not touch `assemble/`, `execute/`, `refresh/`, `adapters/readmodel/`, `adapters/store/`, or
another session's tests.

## Already done — read before writing

- **2.1** `adapters/index/` — the generation file, atomic swap, exact brute-force search, and
  `unit_vector_for()`, the single text-to-vector path used by both build and query.
- **2.2** `names.py`, `namesearch.py`, `lexical.py` — 1,101 indexed surfaces, FTS5 plus vector,
  scored per surface with the max across surfaces. **Nothing calls any of it when answering.**
- **2.13** `labelled/names/` (186 pairs) and `adapters/index/evaluation.py` — the measurement
  harness, run as `uv run python -m askai.adapters.index`.
- **1.11** `compile/binder.py` — the only `QuerySpec` construction in the tree. You extend its
  ladder; you do not replace it. `ports/catalogue.py` cannot return a value, which is what makes
  "the spec is bound before any data is read" structural.

## The measurement that shapes your work

Story 2.13 measured trigram retrieval against 186 labelled pairs:

```
exact 96.0% @1   typo 94.4%   partial 100%   ambiguous 100%
synonym    50.0% @1 / 90.0% @10
paraphrase 21.4% @1 / 47.6% @10        ← recall@10 is a hard ceiling on everything downstream
Arabic 75.0% @1 beats English 69.8%
```

And the finding that decides your design: for the 22 questions where a **wrong** candidate outranked
the right one, that wrong candidate's median score was **0.831** against a derived floor of
**0.838**, with a p95 identical to the relevant p95.

**By score alone, a wrong top answer is indistinguishable from a right one.** No threshold separates
them. Story 2.4's deterministic discriminator is therefore demonstrated necessary, not assumed — and
an embedding model will make this *worse*, because `Real GDP` and `Nominal GDP` are genuinely
similar and differ by the one word that changes the answer.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **2.3 + 2.4 + 2.5** | Candidate generation, deterministic discrimination, decide-bind-or-refuse. One ladder; splitting invents a fake seam. **Start here.** |
| **2** | 2.7 + 2.9 + 2.10 + 2.11 | Six distinct refusals, never substitute, correct a premise, ask one closed question. One refusal module, one message namespace. |
| **3** | 2.6 | The model tie-break. Constrained decoding **and** the validator — `ports/model.py` makes the validator a required field, so you cannot construct a call without one. |
| **4** | 2.8 | Improve a refusal from the unpublished catalogue without leaking it. `ports/unpublished_catalogue.py` exposes names and existence only. |
| — | ~~2.12~~ | **Do not start.** Decision-gated on FR-51; no option-specific criteria exist. |

## Design constraints specific to you

- **Epic 1's resolution is exact normalised-name lookup.** You are adding rungs beneath it, not
  replacing it. Exact match must stay at 96% — it is the cheapest and most reliable rung.
- **Scope filtering happens before scoring** (AD-14), not after. `generation.py` exports `in_scope`.
- **No relevance floor is declared**, deliberately. `rules/data/names-floor.yaml` records one derived
  against trigrams and marked `sufficient: false`, and `floors.resolution_floor(source)` refuses to
  return it for a different vector source. If an embedding model is serving, re-derive before using.
- **Refusing well is the product.** With this much ambiguity, a specific closed question beats a
  confident wrong answer. Six distinct refusals means six — a reader must be able to tell "I do not
  hold that" from "several things match" from "it exists but is not published".
- The model is the **last** rung and never sees a figure. It picks from a closed candidate list,
  its answer is validated against that list, and a failure falls back to asking.

## Verify

The five gates, plus your own measurement:

```
uv run python -m askai.adapters.index      # recall against the 186 labelled pairs
uv run python tests/corpus_runner.py       # 55 entries, compiled twice, must stay deterministic
```

**Report recall before and after every batch.** Your work is the only work in this project with a
number attached to whether it succeeded — use it.
