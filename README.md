# Ask AI — Answer Engine

A rebuild of the Ask AI chat backend: questions about Qatar's national indicator data,
in English and Arabic, answered from approved published data only.

**No application code yet.** This repository currently holds the planning artifacts the build
is made from, and the reviewed data it inherits. Start by reading them in the order below.

## The documents, in reading order

| Document | What it is | Read it for |
|---|---|---|
| **[`docs/PRD.md`](docs/PRD.md)** | 132 numbered requirement ids — 127 in scope, 5 deferred — 12 NFRs, a glossary | *what* the engine must do, and how far each capability actually reaches |
| **[`docs/ARCHITECTURE-SPINE.md`](docs/ARCHITECTURE-SPINE.md)** | 30 architecture decisions, the layer contract, the API and index design | *how* it is built, and which invariants may not be broken |
| **[`docs/DATA-CONTRACT.md`](docs/DATA-CONTRACT.md)** | the published data, measured and verified — 31 files, 33 foreign keys | the seven structural facts behind almost every recorded failure |
| **[`docs/RULES.md`](docs/RULES.md)** | 188 business rules, sourced, mapped and status-bearing | *what is true* — the domain knowledge no architecture derives |
| **[`docs/FINDINGS-TRIAGE.md`](docs/FINDINGS-TRIAGE.md)** | 151 recorded failures, classified | which failures the architecture forecloses, and which need a rule |

If you read only one thing first, read the PRD's §1 and §4 — seven measured data facts and
four product commitments. Everything else follows from those.

## `data/` — the published CMS export, and the source of truth

31 files, 13 MB: the 2026-08-11 export the whole design was measured against. **Everything the
engine answers from is derived from these**, and they are here so the corpus and the tests run with
no service and no network (NFR-6).

`DATA-CONTRACT.md` is the map. The short version: `P01` indicators → `P02` details → `P03`
datapoints → `P04` analysis, with the `Item_*` files as the unpublished base layer used only to
shape refusals.

Everything the engine answers from is derived from `data/`. No generated or derived file is
checked in — a derived artifact in a repository goes stale silently, and regenerating it *is* the
ingest path (FR-108) being exercised.

## What is decided, and what is not

**Decided** — on-premises only; no hosted model or vector service; numbers stay relational and
are never embedded; the model never produces a figure; approved and external content never merge;
rules live as data and the service fails to start without them.

**Not decided** — the embedding model (chosen by corpus evidence, not reputation), the latency
budget's allocation, deployment topology, and who signs the rule catalogue off. Each is listed
under *Deferred* or *Open Questions* in the spine, with the reason it can wait.

## Ground rules for anyone building here

1. **The spine's ADs are binding.** Contradicting one is a spine change, not a local decision.
2. **`pyproject.toml` already carries the dependency contract** as `import-linter` layer and
   forbidden-module rules. It runs in CI from the first commit; a violation fails the build.
3. **Corpus entries assert on the bound query, never on prose.** Prose is brittle and bilingual.
4. **Every figure traces to an approved published row**, or it does not appear.

## The system being replaced

A read-only reference snapshot lives at `../abubaker/askai-src-snapshot-20260913/`. Its design was
sound and its domain knowledge is irreplaceable — 151 recorded findings, most of which became the
rules here. **Its implementation is not a template**; consult it as evidence, not as a base.
