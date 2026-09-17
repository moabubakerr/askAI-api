# Session U — let the 1,031 analyst notes reach a reader

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**This finishes Session K, it is not Epic 6.** K landed the table and the fetch; Story 2 of its
brief — *"attach the commentary to an answer"* — did not land. Articles remain entirely out of
scope and belong to Session O.

## The state, measured 2026-09-17

Session K's work is complete and **unreachable**, the same shape as the ladder before `b33a831`:

| Piece | State |
| --- | --- |
| `analysis` table, schema 2 | exists, **1,031 rows loaded on the VM** (`changed analysis: 0 -> 1031`) |
| `ports/commentary.py` — `CommentaryPort`, `Commentary`, `CommentaryUnavailable` | exists |
| `adapters/readmodel/commentary.py` — `ReadModelCommentary` | exists |
| `Commentary.quotable(lang)` | exists — summary, then detailed, **no cross-language fallback** |
| `DegradationKind.ANALYSIS_ABSENT` | exists |
| `ElementClass.ATTRIBUTED`, `Role.ANALYSIS`, `Role.COMMENTARY` | exist |
| `capability.no_commentary` in `en.yaml` **and** `ar.yaml` | exists |
| **`Engine.commentary`** | **missing** — `api/engine.py` has `datapoints`, `presentation`, `groups`, no commentary port |
| **`engine_for` constructing it** | **missing** |
| **a composer for `Operation.EXPLANATION`** | **missing** |

So the port is never constructed into the engine and the answer path cannot reach it. Everything
below is wiring plus one composer.

## Delete this comment, it is now false

`narrate/dispatch.py:179` refuses the explanation operation with:

> *"there is no composer: an explanation quotes analyst commentary, and the read model has no table
> for it (Story 1.6 creates none, Epic 6 is blocked on it)"*

The table exists and holds 1,031 rows. The stated reason for the block is gone; the block is not.
Removing that entry is part of your second story, not a tidy-up.

## Story 1 — commentary beside an ordinary answer

Session K's unfinished Story 2. When an answer is composed for a `(detail, period, country)` that
has published commentary, carry it as one element:

- class `ATTRIBUTED`, **not** `ARTICLE` — an analyst note carries indicator, grain, period and
  country; an article carries none, and collapsing them is how an opinion piece stands in for a
  statistic
- role `ANALYSIS`
- a `source_ref` naming `source_datapoint_id`, so the quote is traceable to the row it explains
- **quoted, never summarised.** An engine that paraphrased an approved statement would be
  publishing an unapproved one under an approved one's provenance

Wire `Engine.commentary` and construct `ReadModelCommentary` in
`adapters/readmodel/startup.py::engine_for`, beside `presentation` and `groups`.

## Story 2 — the explanation operation

`"Why did inflation move in April 2026?"` currently returns the bare figure. Route
`Operation.EXPLANATION` to a composer that answers **only** from published analyst commentary, and
refuses when there is none. FR-41's *never explain from the model* is the rule: the engine quotes a
person, or it says nobody wrote one.

The three corpus entries:

| id | Question | Expected |
| --- | --- | --- |
| `e6-001` | Why did inflation rise in Q4 2025? | answer |
| `e6-002` | Why did inflation move in April 2026? | answer |
| `e6-003` | Why was inflation negative in 2020? | **refusal** |

**`e6-003` is the load-bearing one**, and check the data before you make it pass. It expects a
refusal because no commentary covers that row — so the refusal must come from *the absence of a
note*, not from the operation being unsupported. If the 2020 datapoint turns out to have
commentary, say so in your report rather than forcing the expectation.

## Non-obvious constraints

- **Coverage is 8%** — 1,031 of 8,127 datapoints, 652 with a substantive English summary. So most
  answers carry no commentary and **that is the normal case, not a failure**. Say nothing rather
  than *"no commentary available"* on nine answers in ten. `DegradationKind.ANALYSIS_ABSENT` exists
  for recording it; use it there, not in the reader's sentence.
- **No cross-language fallback, and do not defeat it.** `quotable()` already refuses to hand an
  Arabic answer an English passage — *"the reader asked in Arabic and would be shown text they may
  not read, sourced as though it were approved for them."* An Arabic question against an
  English-only note carries no commentary element.
- **`CommentaryUnavailable` is a failure, `None` is an absence.** The store not working and the row
  having no note are different facts and must not collapse into one sentence.
- **14 notes decode to nothing at all** and are already reported as a rejection class at ingest.
  They must stay one.

## Coordination — read this before you start

`narrate/` is contended right now:

- **Session P** holds `narrate/structured.py` and `narrate/clarify.py`
- **Session Q** holds `narrate/dispatch.py`

You need exactly one line out of `dispatch.py` (the `Operation.EXPLANATION` entry). **Ask Q, or
wait for it to commit** — do not edit that file alongside it. Put your composer in a **new**
`assemble/commentary.py`; `assemble/written/` is Session O's.

## Own

`api/engine.py` · `adapters/readmodel/startup.py` (the `engine_for` construction) ·
`assemble/commentary.py` (new) · `corpus/epic-6.yaml` (the three `why` entries only) ·
`tests/test_commentary_answers.py` (new, all your tests) · **one line** of `narrate/dispatch.py`,
coordinated with Session Q

Not `pyproject.toml`, `uv.lock`, any existing test file, `adapters/index/` (Sessions O and R),
`execute/`, `compile/`, `narrate/structured.py` or `clarify.py` (Session P), `respond/` (Session S),
or `messages/data/*.yaml` unless a story genuinely needs a new id — `capability.no_commentary`
already exists in both.

All five gates must pass; see `AGENTS.md`.
