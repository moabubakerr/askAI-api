# Session K — stop discarding the analyst commentary

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

**This is deliberately not Epic 6.** Epic 6 is 14 stories of chunking, semantic retrieval,
attribution and article handling. This is the 30-minute change underneath it, plus one small story
on top — most of the value for a fraction of the work. Do not start Epic 6's stories here.

## ⚠ Check the tree first

Two other sessions recently finished and may have left ~11,000 lines uncommitted across 46 files
(Epic 2's refusals and tie-break, Epic 9's admission and external agent). Run `git status` before
you touch anything. If that work is still uncommitted, **do not `git add -A`** — commit only paths
you own, and expect the five gates to be reporting on other people's code as well as yours.

## The problem

The export holds **1,031 rows of analyst commentary** in `P04_Published_DataPointAnalysis` — a
person explaining a figure:

> *"The cost of clearing exports in Qatar QAR 1,935 was one of the highest in the region during
> 2019… in Oman it was equivalent to QAR 1,406. This is contrasted with KSA, where the cost was
> QAR 1,427. The latter achieved a 31% reduction…"*

Ingest reads them, counts them, and **throws them away**, because no table holds them. Two stories
contradict: 1.6 says create only Epic 1's tables and names them; 1.8 says load 1,031 analyses. The
ingest agent refused to invent a table — correctly — and wrote a test asserting both the count and
the absence.

**Resolved in favour of the read model.** You fetch an analysis by `(detail, period)`, which is an
exact-key lookup, not a similarity search. The semantic index finds *which* passage is relevant;
the read model *holds* it. Epic 6 will need both.

## Story 1 — the table (~30 minutes)

- `adapters/readmodel/schema.py` — an `analysis` table keyed to match the datapoint identity
  `(detail_id, period, country_id)`, carrying the published prose columns. Decode through the
  existing `adapters/readmodel/content.py`; **do not write a second decoder**.
- `adapters/store/provision.py` — the `TABLE_OWNERS` entry, owner `askai.adapters.readmodel`.
- `adapters/store/database.py` — bump `SCHEMA_VERSION` to 2.
- `adapters/readmodel/ingest.py` — write the rows. Assert the measured counts: **1,031 rows, 652
  with a substantive English summary**, and **14 whose every prose column decodes to nothing** —
  those are already reported as a rejection class and must stay one.
- `tests/test_schema.py` — **you must edit this**, unusually. It pins `EPIC_1_TABLES` longhand and
  asserts `set(TABLE_OWNERS) == EPIC_1_TABLES`, so a new table fails it by design. Update the set
  and nothing else in that file.

**Operational consequence, and say it in your report:** bumping `SCHEMA_VERSION` makes every
existing estate fail at startup with a version mismatch until it is re-provisioned. That is Story
1.6 working as designed, not a regression. The deployed VM is at version 1 and will need
`python -m askai.adapters.store provision` followed by a refresh.

## Story 2 — attach the commentary to an answer

One element, not a retrieval system. When an answer is composed for a detail and period that *has*
published commentary, include it as an element of class `attributed` with a `source_ref`, alongside
the figure. Quote it; do not summarise.

- `ElementClass.ATTRIBUTED` already exists and is deliberately separate from `ARTICLE` — an analyst
  note carries indicator, grain, period and country; an article carries none.
- The element goes through the same provenance envelope as every other: `assemble/provenance.py`.
- **Coverage is 8%.** 1,031 of 8,127 datapoints have any commentary, 652 a substantive English
  summary. So most answers will have none, and that is the normal case rather than a failure —
  say nothing rather than saying "no commentary available" on nine answers in ten.

## Explicitly out of scope

Chunking at author boundaries (6.1) · semantic retrieval over passages (6.3) · answering *"why"* as
its own operation (6.4) · articles in any form (6.2, 6.6–6.11) · relevance floors. Those are Epic 6
and they need the labelled sets and floors that do not exist yet.

## Own

`adapters/readmodel/` · `adapters/store/schema.py`, `provision.py`, `database.py` ·
`tests/test_schema.py` (the table set only) · `tests/test_analysis.py` (new, all your tests) ·
`corpus/epic-6.yaml`

Not `pyproject.toml`, `uv.lock`, any other existing test file, `domain/`, `compile/`, `execute/`,
`narrate/`, `adapters/index/`, `_bmad-output/` or `docs/`.

All five gates must pass; see `AGENTS.md`.
