# Session H — Epic 9: one answer path, closed world, the external view

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

Most of this epic is pure type work and needs no model or network.

## Own

`respond/` · `adapters/external/` · new `ports/` filenames · `corpus/epic-9.yaml` ·
new `rules/data/` files · new test files

## Build on

- `respond/order.py`, `response.py` — Story 1.15 built these **generic over an opaque type**, so
  the layer cannot name or read a package. That is AD-2 made structural. Keep it.
- `ports/unpublished_catalogue.py` — names and existence only; `UnpublishedName` has two fields and
  no id, period, country, definition or value, with a test asserting no type from it reaches an
  `Answer`. That is 9.2's foundation, already laid.
- `observability/degradations.py` — closed `DegradationKind`, `Outcome[T]`, `Tally`.
  `EXTERNAL_AGENT_UNAVAILABLE` exists.
- `adapters/model/` — the pattern for an outbound adapter: non-raising, every failure a typed
  degradation, fakes so the suite passes with nothing reachable.

## Stories

| Batch | Stories |
|---|---|
| 1 | **9.1 + 9.3 + 9.5** — source admission set, structural closed world, every answer declares its agent. Pure. **Start here** — a closed-world invariant gets harder to retrofit with every epic on top. |
| 2 | 9.2 + 9.4 — the knowledge base and nothing else; say what is missing rather than reaching for something adjacent |
| 3 | 9.6–9.9 — the external agent: parallel, own budget, **two answers never one**, unconditional caveat, recorded |

## Non-obvious constraints

- **Two answers, never one** (9.7). Never merged, averaged or reconciled. The reader sees both
  labelled, or sees one and is told the other was unavailable. This is the story most likely to be
  softened by accident.
- **The caveat is unconditional** (9.8) — not "when they disagree". Always, and honest about its
  own limits.
- **Closed world is structural, not a filter** (9.3). Story 1.6 made confidential indicators
  unrepresentable with a `CHECK` rather than an ingest filter. Match that standard.
- **No external endpoint exists.** Port plus fake; every test passes with nothing reachable.

## Two things you will find

- **No published indicator is marked `Confidential`** — the type exists in
  `P13_Ref_IndicatorPriorityTypes`, the export has 105 `Priority`, 84 blank, **zero** confidential,
  in both layers. The exclusion is real and **cannot be evidenced from this export**. Say so
  rather than writing a test that passes vacuously.
- **342 CMS indicators were never approved for publication**, reachable only as names through the
  unpublished port. That is 9.2's worked example.
