# Session L — give `execute/` the shapes the composers already expect

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**This is the second half of "Epics 3, 4 and 5 are built but unreachable."** The README records the
first half: nothing classified the operation, so every question compiled to `operation: value`. That
was fixed (`0255de5`). The operation now binds correctly — and the answer still does not arrive,
because the layer under it produces one shape only.

## The finding, measured on the deployed VM at `7ef6973`

`api/ask.py:200` is the entire execution step of the answer path:

```python
execution = execute_value(compiled, engine.datapoints)
```

`execute/` contains `value.py`, `latest.py`, `readmodel.py` and nothing else. `execute_value`
fetches **one figure by exact key**, and refuses every operation that is not `value` before it
fetches anything. A multi-country scope returns `SCOPE_IS_NOT_ONE_SERIES` with the comment *"a
cross-country result is the union of two selections, assembled elsewhere"* — and nothing on the
answer path assembles it.

Observed against the real VM:

| Question | Got |
| --- | --- |
| "Compare Qatar's inflation with Singapore's in 2026-Q1." | `question-not-supported` — binds `comparison`, both country ids resolved |
| "Which country had the lowest inflation in 2026-Q1?" | `question-not-supported` |
| "What does inflation mean?" | **`data-could-not-be-reached`** — the wrong code entirely |
| "Show me inflation each year from 2019 to 2025." | a single figure for 2025 |

The last one is **correct and deliberate** — see the switch below. The third is a bug: an
unsupported operation is being reported as an engine fault.

## What is already built and waiting

Do not rewrite any of this. It is tested against directly constructed `QuerySpec`s and only needs
feeding:

- `assemble/change/` — `series.py`, `delta.py`, `compare.py`, `targets.py`, `selection.py`
- `assemble/compare/` — `countries.py`, `indicators.py`, `extrema.py`, `ordinals.py`,
  `readings.py`, `composed.py`
- `assemble/meta/` — `definitions.py`, `groups.py`, `overview.py`, `capability.py`, `periods.py`

Read what each expects **before** designing the execution shapes. The composers are the contract;
`execute/` is what is missing, not them.

## The work

1. **Execution shapes beyond one figure.** A series of readings; two readings for a change; the
   union of per-country selections for a comparison. AD-3 still holds without exception: *figures
   originate only in `execute/`*, nothing scores a row, nothing computes a value, every number names
   the datapoint it was read from. A comparison is a **union of exact-key fetches**, never a query
   that ranks.
2. **Widen the call site.** `api/ask.py:200` dispatches on the bound operation. Keep it one path
   parameterised by a closed type — the argument in `_packages`' docstring about there being no
   per-operation branch applies here too.
3. **Fix the wrong refusal code.** An operation `execute/` cannot perform is
   `question-not-supported`, never `data-could-not-be-reached`. The sixth cause means *a fault in
   the engine*, and spending it on an unimplemented feature makes the one code that should page
   someone useless. Check `execute/value.py`'s `FigureCause` mapping and `narrate/refusal.py`.
   **Also diagnose "What is Qatar's obesity rate?"**, which returns the same code for a plain
   `value` question — that one may be a genuine fault. Get its `degradations` array first.
4. **Then, and only then, flip the switch.**
   `rules/data/operation-words.yaml` → `R-OP-SERIES-FROM-A-MULTI-READING-REQUEST` is `enabled:
   false`, and its note says exactly why: *"Off because execute/ produces no series… Turning this on
   before the series execution exists would replace a partial answer with a refusal, which is a
   worse answer to the same question."* It is a switch precisely so that the day `execute/` can
   produce a series, **what changes is this word and not a binder.** Changing it is the last commit
   of this session, not the first.

## How you know you are done

`corpus/epic-3.yaml`, `epic-4.yaml` and `epic-5.yaml` carry entries that should start passing
without any other change. Run `uv run python tests/corpus_runner.py` before and after and report the
delta — that number is the deliverable, not the diff size.

## Own

`execute/` · `api/ask.py` (the execution step only) · `tests/test_execute_shapes.py` (new, all your
tests) · the one-line switch in `rules/data/operation-words.yaml`

Not `pyproject.toml`, `uv.lock`, any existing test file, `assemble/` (built), `compile/`,
`adapters/index/` (Session M), `narrate/structured.py` beyond the refusal-code mapping, or
`messages/data/*.yaml` unless a story genuinely needs a new id — and then both files, batched at the
end.

All five gates must pass; see `AGENTS.md`.
