# Session F — Epic 6: analyst passages and articles

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

## ⚠ You are probably blocked

The 1,031 published analyses are ingested, counted, and **stored nowhere**. Story 1.8 says load
them; Story 1.6 creates no table for them. Ingest refused to invent one, and a test asserts both
the count and the absence.

Ask a human before starting. If told to proceed, the schema change is your first story:
`adapters/readmodel/schema.py`, `adapters/store/provision.py`, `TABLE_OWNERS`, `SCHEMA_VERSION`
bump, all in one commit.

## Own

`adapters/index/` (analyst + article collections) · `assemble/written/` · `corpus/epic-6.yaml` ·
new `rules/data/` files · new test files

## Build on

`adapters/index/` — `vec_analyst` and `vec_articles` exist, empty. Story 2.2's `names.py` is the
shape to copy. `unit_vector_for()` is the single text-to-vector path. `IndexScope` is mandatory:
AD-14 filters scope **before** ranking. `adapters/readmodel/content.py` already decodes HTML,
base64, entities and PDF split-hyphens — do not write a second decoder.

## Stories

| Batch | Stories |
|---|---|
| 0 | the analyst table (only if a human says so) |
| 1 | 6.1 + 6.3 — chunk at the author's own boundaries; scope filter before ranking |
| 2 | 6.4 + 6.5 — answer "why" only from published analyst text; attribute to the publishing body |
| 3 | 6.2 + 6.6 + 6.7 — index articles; answer from one; always label it as an article |
| 4 | 6.8 + 6.9 — an article's figure is never promoted; retrieval that returns nothing |
| 5 | 6.10–6.13 — bilingual search, list/retrieve/summarise, data leads, depth without dumping |

## Non-obvious constraints

- **`ElementClass.ARTICLE` is separate from `ATTRIBUTED` on purpose.** An analyst note carries
  indicator, grain, period and country; an article carries none. Collapsing them is how an opinion
  piece stands in for a statistic.
- **A figure inside an article is never promoted to an approved figure.** Hard rule (6.8).
- **Invent no relevance floor.** Derive it from a labelled set and record the measured separation,
  as `rules/data/names-floor.yaml` does, or ship none.
- **6.9 — retrieval must be able to return nothing.** The story most likely to be quietly skipped.
- Quote with a `source_ref`; do not summarise.

## Measured, do not re-derive

1,031 analyses · 652 with substantive English summary · 14 whose every prose column decodes to
nothing · 67 live articles of 84 · 32 naming an author id no register holds · 10 with author
`NULL` · 237 definitions that decode to a bare `-`. Analyst passages are HTML `<ul>/<li>/<p>`;
articles have no headings at all.
