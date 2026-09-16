# Session F — Epic 6: analyst passages and articles

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state.

## ⚠ Read this before anything else — you may be blocked

**The 1,031 published analyses are ingested, counted, and stored nowhere.** Story 1.8's
acceptance criteria say load them into the read model; Story 1.6's say create only catalogue,
details, datapoints, reference tables, records and conversation. The two contradict each other,
ingest correctly refused to invent a table, and a test asserts both the count and the absence.

Epic 6 cannot start until that is resolved. It is a DDL change plus a `SCHEMA_VERSION` bump —
maybe thirty minutes — but it is a **schema decision that needs a human**, not something to do
silently inside a content story. Ask, get an answer, then begin. If you are told to proceed,
that schema change is your first story and it belongs in `adapters/readmodel/schema.py` and
`adapters/store/provision.py` with `TABLE_OWNERS` updated in the same commit.

## You own

`src/askai/adapters/index/` (the analyst and article collections) · `src/askai/assemble/written/`
· `corpus/epic-6.yaml` · new files under `src/askai/rules/data/` · new test files

## What exists and what you build on

- `adapters/index/` — Story 2.1's generation file, atomic swap, exact search, and `unit_vector_for()`,
  the single text-to-vector path. **`vec_analyst` and `vec_articles` already exist in the index
  schema, empty.** Filling them is yours. Story 2.2 filled `vec_names` — read `names.py` for the
  shape to follow.
- `ports/index.py` — `IndexScope` is a **mandatory** argument. AD-14 requires the scope filter to
  run *before* ranking, never after.
- `adapters/readmodel/content.py` — already decodes the export's HTML, base64, entities and PDF
  split-hyphens, and delegates emptiness to `domain/text.py`'s single predicate. Do not write a
  second decoder.
- `rules/data/names-floor.yaml` — the floor derivation pattern. Analyst and article retrieval need
  their **own** floors, derived from their **own** labelled sets, recorded with the measured
  separation. `labelled/names/` is the shape to copy.

## Measured facts about your data — do not re-derive these

| | |
|---|---|
| Published analyses | **1,031** rows, of which **652** carry a substantive English summary |
| Analyses whose every prose column decodes to nothing | 14 — they claim analysis and have none |
| Live articles | **67 of 84** in `data/Articles.csv` |
| Articles naming an author id no register holds | **32** |
| Articles whose author column is the literal string `NULL` | 10 |
| Definitions that decode to no text (a bare `-`) | 237 |

Analyst passages are HTML with `<ul>/<li>` and `<p>` — chunk at the **author's own boundaries**
(Story 6.1), not at a fixed token count. Articles have no headings at all (6.2) and need a
different strategy; say which you chose and why.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **0** | the analyst table | Only if a human says so. Blocks everything below. |
| **1** | 6.1 + 6.3 | Chunk analyst passages at the author's boundaries; filter by scope **before** ranking. |
| **2** | 6.4 + 6.5 | Answer "why" only from published analyst text; attribute it to its publishing body. |
| **3** | 6.2 + 6.6 + 6.7 | Index articles; answer from one as a first-class source; always label it as an article. |
| **4** | 6.8 + 6.9 | An article's figure is **never** promoted to an approved one; retrieval that returns nothing when nothing answers. |
| **5** | 6.10 + 6.11 + 6.12 + 6.13 | Bilingual article search, list/retrieve/summarise, published data leads, depth without dumping. |

## The constraints that matter most

- **An article is not an indicator.** `ElementClass.ARTICLE` exists separately from `ATTRIBUTED`
  precisely because an analyst note carries indicator, grain, period and country while an article
  carries none. Collapsing them is how an opinion piece comes to stand in for a statistic.
- **A figure inside an article is never promoted to an approved figure.** This is a hard rule,
  not a presentation choice. Story 6.8 is where it is enforced.
- **No floor may be invented.** Story 2.2 shipped none and said so; 2.13 derived one for names
  from a labelled set and recorded it as `sufficient: false`. Do the same here or ship none.
- **Retrieval must be able to return nothing.** 6.9 is the story that says so, and it is the one
  most likely to be quietly skipped.
- Quote, never summarise, unless a later story says otherwise. Attribution with a `source_ref`
  is what separates this from a chatbot.

## Ownership and verification

Do NOT edit `pyproject.toml`, `uv.lock`, any existing test file, or anything under
`src/askai/domain/`, `compile/`, `execute/`, `messages/`, `config/`, `_bmad-output/` or `docs/`.
All five gates must pass; see `AGENTS.md`.
