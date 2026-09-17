# Session R — measure retrieval, then set the margin from the measurement

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**Run this after Session M** (landed as `b33a831`). The ladder is wired, a generation is published,
and BGE-M3 is serving. For the first time on this project, retrieval can be measured.

## Where it stands, measured on the VM 2026-09-17

A generation exists: `1101 name surfaces and 289 details, openai-embeddings/BAAI/bge-m3/d1024/folded`.

Four real responses, and they are the whole brief:

| Question | Result |
| --- | --- |
| `tourism sector contribution to GDP` | `several-indicators-match: Sector Exports, Sector Exports, Sector Exports` |
| `How fast are prices rising?` | `no-indicator-resolved: too-many-to-name` |
| `What is the unemployment rate?` | **bound the wrong indicator** — *Workforce (Economically Active)* |
| `What is GDP?` | `no-such-indicator` |

Retrieval is **working**: candidates are generated and stage 2 runs. What is unknown is whether it
is any good, and nothing in the repository can currently say.

Note the third row. With the ladder off that question refused; with it on it answers about a
different indicator. **Turning retrieval on has made some answers wrong that were previously
absent.** Whether that trade is acceptable is a decision this session's number informs.

## The blocker, and it is small

```
$ python -m askai.adapters.index
labelled/names/set.txt does not exist; a labelled set is a directory holding a
set.txt manifest beside its .cases files
```

The AD-30 harness exists and has never run against a real endpoint, because **no labelled set was
ever built**. `NEXT-STEPS.md` called it "the largest single unblocking task"; it was not done.

It is cheaper than that framing suggests. The README records that `names` ground truth is *mostly
free*, and you have 95 corpus questions whose intended indicator is known from the entry's `why`
text. **Roughly 40 unambiguous cases is enough for a first recall@1 number**, and an hour of work.
Do not attempt the article labelling here — that is Session O's problem and a different metric.

## The work

1. **Build `labelled/names/`** from the corpus: question -> the detail id it should bind. Take only
   the cases where the intended indicator is unambiguous; record the ones you skip and why, because
   the skipped set is itself a finding about the corpus.
2. **Run the harness** against the live generation and record the number. The recorded prior is
   **21% recall@1 for paraphrases on trigrams**, measured before this index existed. Whether BGE-M3
   beats it is the question.
3. **Then, and only then, set the margin.** `R-RESOLVE-AMBIGUITY-MARGIN`'s `maximum_offered`
   governs `too-many-to-name`; `rules/data/names-floor.yaml` is the shape to copy — a threshold
   with the measured separation recorded beside it. The project's rule is explicit: derive it from
   a labelled set and record the separation, or ship none. **Widening it without a measurement
   converts refusals into wrong answers**, which is the failure Session Q is cleaning up.
4. **Re-run the four questions above** and report what moved.

## The decision this session hands back

With a number in hand, someone can choose the serving posture deliberately rather than by feel:

- ladder on, margin tightened so weak matches refuse — more coverage, fewer false answers
- ladder on as-is — most coverage, some wrong answers
- `engine_at(..., index=IndexPolicy.ABSENT)` — honest refusals, exact names only

Write the recommendation into the report with the number that supports it. Right now that choice is
being made on three spot checks.

## A note on `What is GDP?`

It returns `no-such-indicator` — *nothing retrieved at all* — for a term appearing in many published
names. That is a different failure from `too-many-to-name` and may point at how surfaces were
indexed rather than at ranking. Worth isolating early; it may be the cheapest real finding here.

## Own

`labelled/` (new) · `adapters/index/quality.py`, `evaluation.py`, `tuning.py`, `floors.py` ·
`rules/data/` (new files only) · `scripts/` · `tests/test_retrieval_measurement.py` (new)

Not `pyproject.toml`, `uv.lock`, any existing test file, `compile/`, `execute/` (Session L),
`narrate/` (Sessions P and Q), or the generation format — a generation is rebuilt, never migrated.

All five gates must pass; see `AGENTS.md`.
