# Session M — wire AD-25's ladder into a running deployment

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**The ladder is built and unreachable.** Session A landed stages 1 and 2 and Session J landed the
model tie-break rung. None of it executes on any deployment, including the VM. Nothing is broken in
`adapters/index/`; the composition root never joins it up.

## The finding, measured on the deployed VM at `7ef6973`

`adapters/readmodel/startup.py:96` builds the `Engine` and never passes `candidates`.
`api/engine.py:98` defaults it to `None`. `compile/binder.py:_resolve()` returns `None` on its first
line. **Only exact normalised-name lookup ever runs.**

| Piece | State |
| --- | --- |
| `IndexCandidates` — a complete `CandidatePort` | exists, `adapters/index/resolution.py:57` |
| `IndexCandidates.over(generation)` | exists |
| `adapters/index/swap.py` | exists |
| A production index builder | **missing** — `python -m askai.adapters.index` is the AD-30 quality harness; it builds a generation in a temp workspace and deletes it |
| `askai.refresh` building or swapping a generation | **missing** |
| `engine_for(...)` passing `candidates=` | **missing** |
| `model=chat_model()` | wired, but the rung only fires on a `Disambiguation` the ladder produced, so it never runs either |

Symptoms, all one cause. Exact published names bind (`Inflation`, `Real GDP`), which is what makes
this survive a smoke test:

| Question | Got | Should be |
| --- | --- | --- |
| "How fast are prices rising?" | `no-such-indicator` | answer |
| "What is GDP?" | `no-such-indicator` | clarification |
| "How many tourists visited Qatar last year?" | `no-such-indicator` | answer |
| "Global Cybersecurity Index rank" | `no-such-indicator` | clarification |
| "Number of Jobs in the Sector" | clarification listing **three UUIDs** | options a reader can choose between |

**Any corpus entry whose question is not an exact published name cannot pass on any deployment
today.** Treat apparent per-question defects as this one gap until proven otherwise.

## The work

1. **A production index build, with an operator entry point** in the style of
   `python -m askai.adapters.store provision` and `python -m askai.refresh`. Decide where
   generations live — a volume beside the databases is the obvious answer; `docker-compose.yml`
   already mounts `askai-databases:/var/lib/askai`. `ASKAI_EMBEDDING_*` and the `tei` service are
   already declared and are what the build step consumes.
2. **Swap on refresh.** `adapters/index/swap.py` exists and `askai/refresh/` never calls it. A
   refresh that loads new details without rebuilding the index leaves the ladder resolving against
   names the read model no longer holds.
3. **Wire it.** `engine_for` takes the generation and passes
   `candidates=IndexCandidates.over(generation)`.
4. **Fail loudly when there is no generation.** Serving with `candidates=None` is today's *silent*
   behaviour and is why this reached a VM unnoticed. Copy the argument at `api/app.py:123` — a
   deployment that cannot produce the reviewed prompt does not start and answer. A deployment that
   cannot resolve a paraphrase should not quietly answer "no such indicator" to most of its readers.
   Whether an explicitly index-less deployment stays legal is a real decision: make it, state it,
   and put it behind a named setting rather than a `None`.

## The UUID leak belongs here

`compile/binder.py:232` builds the particulars for an exactly-typed shared name as
`", ".join(found)` — detail **ids**. With no ladder, `narrate/structured.py:671` finds no
`Disambiguation.candidates` carrying surfaces and falls back to them, so ids reach the reader.

**Substituting published names does not fix it.** Measured against the real export, the three tied
details are identical once normalised:

```
342a4e73…  en='Number of Jobs in the Sector'
dc8a5197…  en='Number of Jobs in the sector'
f623f0e1…  en='Number of Jobs in the Sector'
```

20 export names are shared by more than one detail; `sector contribution to gdp` by **eight**; the
codebase puts it at 257 of 320. Without the ladder's distinguishing facts there is nothing to put in
`clarify.which_indicator`'s `{options}`. So this is fixed *by* wiring the ladder — and if you need
an interim sentence, it is a new id in **both** `messages/data/en.yaml` and `ar.yaml`, batched at
the end, with the Arabic reviewed by a native speaker before it ships.

Keep the ids in the particulars — the record and the corpus want them. It is only the reader-facing
sentence that must not carry them.

## How you know you are done

Retrieval quality is **unmeasured** and the README has said so since 2026-09-16: paraphrases bind at
a measured 21% recall@1 on trigrams, and everything above retrieval inherits that ceiling. BGE-M3 is
serving on the VM. Run `scripts/measure_embeddings.py` and
`uv run python tests/corpus_runner.py`, and report both numbers. A wired ladder that resolves badly
is a different problem from an unwired one, and you are the first session able to tell them apart.

## Own

`adapters/index/` · `adapters/readmodel/startup.py` · `api/engine.py` · `askai/refresh/` ·
`askai/asgi.py` · `tests/test_ladder_wiring.py` (new, all your tests)

Not `pyproject.toml`, `uv.lock`, any existing test file, `execute/` (Session L), `assemble/`,
`compile/binder.py` beyond line 232, or `docker-compose.yml` without saying so in your report —
adding a build step changes the deployment order recorded in `AGENTS.md`, and that record is shared.

All five gates must pass; see `AGENTS.md`.
