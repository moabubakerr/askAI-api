# Parallel session briefs

One Claude Code session per epic, each owning one package. The fences are the point: two sessions
editing one file is the only failure mode that reliably costs time.

Start each in its own terminal:

```bash
cd c:\projects\askAI\askai-api
claude
```

Then: **"Read `AGENTS.md` and `sessions/<your-brief>.md`, then begin."**

`AGENTS.md` carries the house rules, the VM facts, the deployment order and the build state. Each
brief carries only what is specific to that session. Read both.

## Suggested order

**Q** and **P** first — they are correctness and are what stops this being demonstrable. **N** next,
because until its gate exists nothing measures whether a change helped. Then **R** (the number that
decides the serving posture), **L** finished, **S** once its decision is made, **O** last.

Q, P, N and R touch different packages and can run in parallel; check the fences below.

## State — 2026-09-17

**Deployed and answering on the target VM.** `POST /api/ask` returns a real figure with a resolving
`source_ref`, freshness not stale, one audit record per request. The preflight passes on that
filesystem, so WAL works and the atomic-refresh design holds where it will actually run.

2,304 tests passing, 4 failing, 1 skipped. Epics 1–5, 9 and 10 substantially built.

**The four failures are all Epic 9's `external`/Combined path** and are blocked on one decision, not
four bugs: `EXTERNAL_ONLY` composes no approved package, and `respond/response.py` requires at least
one. Both invariants are deliberate and they collide. Either relax the `Response` invariant when the
admission excluded `APPROVED`, or compose an approved-side refusal saying the layer was not
consulted — the second needs a new id in both message files. **Nobody should pick this up without
making that call first.**

**Read the reachability note below before starting anything.** Three defects found on 2026-09-17
were all the same shape — finished code that no composition root calls — and all three passed the
suite for days.

## The briefs

| Session | Brief | Epic | State |
|---|---|---|---|
| **A** | `session-a-epic-2-resolution.md` | 2 — the ladder | **Done.** 2.3/2.4/2.5 landed. |
| **B** | `session-b-epic-3-series-and-change.md` | 3 — series, change | **Done.** |
| **C** | `session-c-epic-4-countries.md` | 4 — comparison, ranks | **Done.** |
| **D** | `session-d-epic-5-groups-and-metadata.md` | 5 — groups, metadata | **Done.** |
| **E** | `session-e-review-and-epic-1.md` | 1 — finish and review | **Run this.** 20+ stories shipped without review. |
| **F** | `session-f-epic-6-analyst-and-articles.md` | 6 — analyst, articles | **Blocked**, and mostly deferred — run **K** instead. |
| **K** | `session-k-analyst-table.md` | 6 — the table only | **Run this.** Stops 1,031 analyses being discarded, in ~30 minutes, without Epic 6's 14 stories. |
| **G** | `session-g-epic-8-prose-and-guards.md` | 8 — prose, guards | Ready. The four guards need no model. |
| **H** | `session-h-epic-9-closed-world.md` | 9 — closed world, external | Ready. 9.1/9.3/9.5 are pure type work. |
| **I** | `session-i-epic-10-governance.md` | 10 — governance | Ready, and newly unblocked: the rules are agreed. |
| **J** | `session-j-epic-2-refusals.md` | 2 — refusals, tie-break | **Done.** Landed in `9cd8a3d`. |
| **L** | `session-l-execute-beyond-value.md` | 3/4/5 — reachability | **In progress**, committed mid-flight at `3c945e6`. Series works; comparison, counts and lists still refuse. Read `review-findings-session-l.md` before continuing. |
| **M** | `session-m-wire-the-ladder.md` | 2 — reachability | **Done.** `b33a831`. Ladder live on the VM. |
| **N** | `session-n-deploy-and-verify.md` | — | **Run this.** Its main deliverable is the gate that measures whether questions are answered — nothing in this repo does. |
| **O** | `session-o-answer-from-articles.md` | 6 — articles only | After M. Answers from the 67 articles. **No relevance floor — decided deliberately**, see the brief. |
| **P** | `session-p-what-the-reader-is-told.md` | 2 — narration | **Run this.** Detail ids are reaching readers in four composers, and the commonest clarification offers three identical names. |
| **Q** | `session-q-answers-that-should-be-refusals.md` | 1/3/9 — correctness | **Highest severity.** Six questions that must refuse now answer, including a target invented for an indicator that publishes none. |
| **R** | `session-r-measure-retrieval.md` | 2 — quality | After M. Builds the labelled set the AD-30 harness needs, measures recall@1, then derives the margin from it. |
| **S** | `session-s-epic-9-external-contract.md` | 9 — contract | Blocked on one decision, stated in the brief. Now reader-visible: every Combined request renders a second "could not be reached" package. |

Epic 7 (conversation, 8 stories) has no brief **on purpose**. It multiplies the test surface of
every other path for little standalone value, and it is the epic most likely to destabilise what
already works. Write one only if someone decides they want it.

## Read this before starting a session

**Epics 3, 4 and 5 are built but were unreachable.** Every composer — series, change, comparison,
ranks, definitions, groups, the executive overview — was written and tested against directly
constructed `QuerySpec`s. Nothing classified the operation from the question, so every question
compiled to `operation: value` and fell through to the figure. No story owned operation
classification; AD-22 names it as a model call-site and the story was never written.

**Half of that is fixed.** `0255de5` binds the operation from the question and dispatches on it. The
other half is not: `api/ask.py` calls `execute_value` and nothing else, and `execute/` holds one
shape. So the operation now binds correctly and the composers are still unreachable. **Session L.**

**The same pattern, twice more.** `engine_for` never passes a `CandidatePort`, so AD-25's ladder and
the Story 2.6 tie-break rung never execute anywhere (**Session M**); and until `7ef6973` the
snapshot offered the home country as a filterable name, so naming your own country refused the
question. None of the three were visible from a developer machine and all three passed the suite.

If you are picking up a brief and a composer seems unreachable, check `git log` first — and then
check whether anything in a composition root actually calls it.

## The fences

- **Nobody edits `pyproject.toml` or `uv.lock`.** A session needing a dependency stops and asks.
- **Nobody edits another session's package**, and **nobody edits an existing test file.** One new
  test file per story, named for it.
- **`src/askai/messages/data/en.yaml` and `ar.yaml` are genuinely shared.** Adding a message id
  means editing both, and two sessions doing that at once will conflict. Batch your additions at
  the end of a story. Both files must carry identical ids or startup fails.
- **`src/askai/rules/data/`** — one **new** file per concern, never edit an existing one.
- **`corpus/epic-N.yaml`** — your epic's file only.

## Committing

Commit each story as it lands, **explicit paths only** — never `git add -A` while another session
is writing. Pull first. All five gates green before any commit:

```
uv run lint-imports
uv run mypy --strict src/askai tests
uv run ruff check .
uv run pytest
uv run python tests/corpus_runner.py
```

A gate failing in a file you do not own belongs to another session. Do not fix it. Say so.

## Generate your epic context first

Cheap, and it stops every agent you spawn re-deriving the same background:

> Read `_bmad-output/planning-artifacts/epics.md` for Epic N and the relevant parts of `docs/`, and
> write `_bmad-output/implementation-artifacts/epic-N-context.md` — goal, stories, requirements,
> technical decisions, cross-story dependencies. 800–1500 tokens. Follow `epic-1-context.md`.

Then hand that file to every agent instead of the raw planning documents.

## Decisions waiting on a human — escalate, never guess

- **The analyst table.** ~~Blocks all 14 stories of Epic 6.~~ **Decided:** resolved in favour of the
  read model — see Session K, which is a ~30-minute change. Stories 1.6 and 1.8 contradict each
  other; 1,031 analyses are ingested and stored nowhere; a test pins both the count and the absence
  (`tests/test_ingest.py:165`). Still a DDL change and a `SCHEMA_VERSION` bump, so **every existing
  estate — including the VM — fails at startup until re-provisioned.** That is Story 1.6 working as
  designed. Articles no longer wait on this: Session O is independent of it.
- **`agreed_by`.** All 187 non-rejected rules are agreed as of 2026-09-16; nobody is named. Blocks
  Story 10.2.
- **Story 2.12.** Decision-gated on FR-51 — three options, 65 of 189 indicators, no option-specific
  criteria. Do not start it.
- **Retrieval quality is unmeasured.** BGE-M3 is serving on the VM and the harness is one command
  (`scripts/measure_embeddings.py`), but nobody has run it. Paraphrased questions currently bind at
  a measured **21% recall@1** on trigrams. Everything built above retrieval inherits that ceiling.
