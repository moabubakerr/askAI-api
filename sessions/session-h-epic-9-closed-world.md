# Session H — Epic 9: one answer path, closed world, and the external view

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state.

This epic is what makes "the engine answers only from approved published data" a property of the
code rather than a claim in a document. Most of it is pure type work and needs no model.

## You own

`src/askai/respond/` · `src/askai/adapters/external/` · `src/askai/ports/` (new filenames) ·
`corpus/epic-9.yaml` · new files under `src/askai/rules/data/` · new test files

## What exists

- `respond/order.py`, `respond/response.py` — Story 1.15 built these **generic over an opaque type**,
  so the layer literally cannot name or read a package. That is AD-2's "respond arranges packages,
  it never reaches inside one", made structural. Keep it that way.
- `narrate/package.py` — the only `AnswerPackage` constructor in the tree.
- `ports/unpublished_catalogue.py` — the base CMS layer, exposing **names and existence only**.
  `UnpublishedName` carries two fields and no id, period, country, definition or value, and a test
  asserts no type from it crosses into an `Answer`. That is 9.2's foundation, already laid.
- `observability/degradations.py` — the closed `DegradationKind` set, `Outcome[T]`, and `Tally`.
  `EXTERNAL_AGENT_UNAVAILABLE` already exists.
- `adapters/model/` — the pattern for an outbound adapter: totally non-raising, every failure a
  typed degradation, fakes so the suite passes with nothing reachable.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **9.1 + 9.3 + 9.5** | Source admission set, structural closed-world enforcement, every answer declares its agent. **All pure, no model, no network.** Start here — it is a type invariant that gets harder to retrofit with every epic that lands on top. |
| **2** | 9.2 + 9.4 | The knowledge base and nothing else; say what is missing rather than reaching for something adjacent. |
| **3** | 9.6 + 9.7 + 9.8 + 9.9 | The external agent: fetched in parallel on its own budget, returning **two answers never one**, with an unconditional caveat, recorded on every answer. |

## The constraints that define this epic

- **Two answers, never one.** 9.7 is the story most likely to be softened by accident. An external
  view and an approved answer are never merged, never averaged, never reconciled. The reader sees
  both, labelled, or sees one and is told the other was unavailable.
- **The caveat is unconditional.** Not "when the external answer disagrees" — always. 9.8 says it
  must also be honest about its own limits.
- **Closed world is structural, not a filter.** 9.3 is the difference between "we exclude
  unpublished content" and "unpublished content cannot be represented in an answer". Story 1.6
  already did this for confidential indicators with a `CHECK` constraint rather than an ingest
  filter — that is the standard to match.
- **No external endpoint exists.** Build behind a port with a fake, exactly as the model adapter
  does. Every test passes with nothing reachable.

## Two things you will find

- **No published indicator is marked `Confidential`.** `P13_Ref_IndicatorPriorityTypes` defines the
  type; the export has 105 `Priority`, 84 blank and **zero** confidential, in both layers. The
  exclusion is real and enforced, and **it cannot be evidenced from this export**. Say so rather
  than writing a test that passes vacuously.
- **342 CMS indicators were never approved for publication**, and they are reachable only as names
  through the unpublished port. That is your worked example for 9.2.

## Ownership

Do NOT edit `pyproject.toml`, `uv.lock`, any existing test file, or anything under
`src/askai/domain/`, `compile/`, `execute/`, `assemble/`, `narrate/`, `messages/`, `config/`,
`adapters/readmodel/`, `adapters/store/`, `adapters/index/`, `_bmad-output/` or `docs/`.
All five gates must pass; see `AGENTS.md`.
