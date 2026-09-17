# Session O — answer from the published articles

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**Run this after Session M.** Articles live in the same index generation the ladder does, so the
production index build and swap must exist first. Nothing here works without them.

## The decision, made and recorded

**No relevance floor.** When a reader asks something the articles can answer, answer it from the
articles. This was decided deliberately, against the position in `session-f-epic-6-analyst-and-articles.md`
("invent no relevance floor… derive it from a labelled set or ship none"), because the value of
demonstrating retrieval now outweighs shipping a measured threshold later.

**Do not re-open this in the session.** Build it without a floor.

Two things follow, and they are scope, not objections:

1. **Retrieval will always return its nearest match.** A question on a subject no article covers
   gets the closest article anyway. That is the accepted behaviour here.
2. **`corpus/epic-6.yaml` entry `e6-005`** — *"What do your articles say about Qatar's obesity
   rate?"* — is recorded as expecting a **refusal**. Under this decision it will return an article.
   **Re-record that entry's expectation in the same commit**, with a `why` naming this decision.
   A corpus entry left failing is indistinguishable from a regression three weeks from now.

## This is not all of Epic 6

Out of scope: chunking at author boundaries (6.1) · attribution to the publishing body (6.5) ·
data leads (6.12) · depth without dumping (6.13) · relevance floors (6.9) · the analyst passages,
which are Session K's table and a different retrieval path entirely.

In scope: index the articles, retrieve one, answer from it, label it as an article.

## Stories

**1 — index the articles.** `vec_articles` exists in `adapters/index/` and is empty. `names.py`
(Story 2.2) is the shape to copy; `unit_vector_for()` is the single text-to-vector path — do not
write a second one. `adapters/readmodel/content.py` already decodes HTML, base64, entities and PDF
split-hyphens; do not write a second decoder.

**Articles have no headings at all** (measured). There are no author boundaries to chunk at, so
index whole articles or split on paragraphs — state which you chose and why in the module docstring.

**2 — answer from one.** The article's text becomes an element of class `ARTICLE`, quoted with a
`source_ref`. Quote; do not summarise.

**3 — always label it.** The reader must be able to tell an article from a statistic without
reading carefully. `ElementClass.ARTICLE` is separate from `ATTRIBUTED` **on purpose**: an analyst
note carries indicator, grain, period and country; an article carries none. Collapsing them is how
an opinion piece stands in for a statistic.

## The two rules that still hold, floor or no floor

- **`IndexScope` filtering before ranking is mandatory** (AD-14). This is a filter, not a floor, and
  dropping it is not part of the decision above.
- **A figure inside an article is never promoted to an approved figure** (6.8). Absolute. An article
  may be quoted; a number inside it never becomes an answer's figure, never gets a `source_ref` into
  the approved half, and never reaches `assemble/` as a measured element. This is the rule that
  keeps the closed world closed, and it is unaffected by how relevance is decided.

## Measured, do not re-derive

**67 live articles of 84.** **32 name an author id no register holds; 10 have author `NULL`** — so
attribution is blank or broken on roughly half of them. Expect it, handle it without raising, and
say so in your report. 237 definitions decode to a bare `-`.

## Own

`adapters/index/` (the article collection only — coordinate with Session M, which owns the
generation and the build) · `assemble/written/` · `corpus/epic-6.yaml` · new `rules/data/` files ·
`tests/test_articles.py` (new, all your tests)

Not `pyproject.toml`, `uv.lock`, any existing test file, `execute/` (Session L),
`adapters/readmodel/` (Session K), or `messages/data/*.yaml` beyond ids your stories genuinely need
— and then both files, batched at the end, Arabic reviewed by a native speaker.

## Report

Say plainly what was and was not measured. Retrieval quality here is **unvalidated by design** —
that is a recorded decision, not an oversight, and the next person needs to read it as one.

All five gates must pass; see `AGENTS.md`.
