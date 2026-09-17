# Session T — Epic 7: the follow-up question

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

## Why this exists now, when the README says it should not

`sessions/README.md` has said since 2026-09-16 that Epic 7 has no brief **on purpose**: eight
stories, it multiplies the test surface of every other path, and it is the epic most likely to
destabilise what already works. That judgement still stands and this brief does not overturn it.

What changed is the demo. *"And monthly?"*, *"What about 2022?"*, *"And the UAE?"* are what a person
types within a minute of seeing an answer, and today every one of them is refused. So this brief
takes **the four corpus questions and nothing else** — it is deliberately not Epic 7's eight
stories. If you find yourself designing a session model, stop and re-read this paragraph.

## What already exists, which is most of it

This is the same shape as the ladder and the execution layer: the mechanism is built and nothing
feeds it.

| Piece | State |
| --- | --- |
| `CompileInput.history: tuple[str, ...]` | exists, `compile/binder.py:134`, **defaults to `()`** |
| `_inherited(earlier, field)` | exists, `:175` — and refuses to inherit an earlier `Unbound`, because carrying "the reader was not specific enough" forward would answer this question with the previous one's ambiguity |
| `_from_history` / `Precedence.INHERITED_FROM_HISTORY` | exists, recorded per field in `bound_by` |
| Every field binder taking `earlier` | exists — detail, period, country scope, measure, operation |
| `conversation_turn` table | **exists and is empty**, `adapters/store/schema.py:67` |
| `record.(conversation_id, turn)` unique index | exists, `schema.py:61` |
| `Ask.conversation_id`, and it on the wire | exists |
| `api/ask.py` passing `history=` | **missing** — `CompileInput(question=..., today=...)`, nothing else |
| `turn` | **hardcoded** to `FIRST_TURN` at `api/ask.py:547` |

`adapters/store/records.py:12` says it outright: *"It does not write `conversation_turn`. That table
is the conversation's, filled by the story that owns history."* You are that story.

So the follow-up logic — override what this question names, inherit the rest, never inherit an
ambiguity — is written, tested and unreachable. Read it before writing anything; you are likely
wiring rather than building.

## The decision to make first, and out loud

**Where does history come from?** Two answers are live in the codebase and they contradict:

1. **The client sends it.** `api/ask.py`'s docstring: *"The engine owns no session store (AD-24), so
   it cannot know a request is the fifth turn of anything; it records the turn it can defend, and
   the conversation id carries the thread the client is keeping."* This keeps the engine stateless
   and `CompileInput.history` is literally a tuple of question strings — the shape a client could
   send.
2. **The engine stores it.** `conversation_turn` exists, is owned by `askai.adapters.store`, and
   `records.py` says a story fills it.

Both cannot be true. **Settle it before the first line of code and write the reasoning into the
commit message**, because this is exactly the shape of the Epic 9 contradiction that cost a session:
two deliberate designs, each documented, quietly incompatible.

Points worth weighing: a stateless engine is easier to defend and matches AD-24 as written; a
client-supplied history is a client-supplied *input to binding*, so a client could fabricate a
previous turn — which matters for an engine whose whole claim is that answers are defensible. If
you choose the store, say what evicts a conversation and why.

## Scope — four questions

| id | Question | Expected |
| --- | --- | --- |
| `e7-001` | And monthly? | answer — same detail, new grain |
| `e7-002` | What about 2022? | answer — same detail, new period |
| `e7-004` | And the UAE? | **refusal** |
| `e2-026` | The real one | answer — disambiguates a previous clarification |

`e7-004` expecting a refusal is the load-bearing case. Work out *why* before you make it pass:
a follow-up naming a benchmark country against a national-scope previous turn is not a narrowing of
that question, and inheriting into it would answer something the reader did not ask. Getting
`e7-001` and `e7-002` to pass while `e7-004` also passes is the whole difficulty.

`e2-026` ("The real one") follows a clarification rather than an answer, which is a different
inheritance: the previous turn bound nothing, and `_inherited` deliberately refuses to carry an
`Unbound`. Decide whether a clarification's *candidates* are a thing the next turn may resolve
against, and say so.

## Out of scope

`e7-003` — *"What was inflation in April 2026, and how does Qatar's real GDP compare with Japan's?"*
That is multi-part detection. `CallSite.MULTI_PART_DETECTION` is one of AD-22's four permitted model
call sites and **has no prompt on disk**; adding one is a reviewed act with `verify_prompts()`
behind it. Leave it. Say in your report that it is the only corpus entry you did not take.

Also out: summarisation of earlier turns, pronoun resolution beyond the four cases above, any
session expiry policy beyond what your decision above requires, and anything touching the lens.

## Containing the risk the README named

- **Determinism is a gate (AD-17, NFR-1).** The same question with the same history and the same
  `today` must compile to an identical spec. History is an *input*; it may not become a clock or a
  store read at binding time. `tests/corpus_runner.py` asserts this and must keep passing.
- **Every field's `bound_by` already carries `inherited-from-history`.** Use it. A reader, and the
  record, should be able to see which parts of an answer came from a question they did not just ask.
- **No existing corpus entry may change behaviour.** 95 questions compile with empty history today;
  they must compile identically after. That is your regression gate, and it is cheap to run.

## Own

`api/ask.py` (the `CompileInput` construction and `turn`) · `adapters/store/` (the
`conversation_turn` writer, if your decision needs one) · `compile/binder.py` (only if the existing
inheritance is genuinely wrong — prefer feeding it) · `corpus/epic-7.yaml` ·
`tests/test_conversation.py` (new, all your tests)

Not `pyproject.toml`, `uv.lock`, any existing test file, `execute/`, `narrate/structured.py` or
`narrate/clarify.py` (Session P), `compile/operations.py` or `compile/lexicon.py` (Session Q),
`adapters/index/` (Sessions R and O), `respond/` or `domain/admission.py` (Session S).

**`api/ask.py` is contended.** Session L has committed work there and Session S will need
`_packages()`. Check `git log` and `sessions/README.md` before you start, and keep to the two lines
you need.

All five gates must pass; see `AGENTS.md`.
