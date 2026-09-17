# Session I — Epic 10: rule governance and answer quality

Read `AGENTS.md` first (house rules, VM facts, build state). This brief adds only what is specific.

This epic produces evidence, not capability. The founding complaint was *"I cannot see, agree, or
verify the business logic."* `docs/RULES.md` answers **see**; the architecture answers **verify**;
this epic makes *verify* demonstrable to someone who does not read code.

## What unblocked you on 2026-09-16

**All 187 non-rejected rules are agreed.** `R-157` stays `rejected` — it exists so it is not
re-proposed, not so it fires. The 49 encoded as data carry `status: agreed`:

```
50 rules from 12 files -- agreed 49 | proposed 0 | rejected 1
```

Story 1.4's loader **reads** status without gating on it, so this was a data edit: all tests passed
untouched. **Story 10.7's coverage gate can therefore ship live** rather than inert.

## Still blocked

**`agreed_by` is `UNRECORDED`.** Agreement was verbal and no approver was named. The schema has no
such field yet — that is 10.2's job. **Do not invent an approver.** Build the field, leave it null,
say so.

## Stories

| Batch | Stories | State |
|---|---|---|
| 1 | 10.1 + 10.3 | Traceability and audit trail. Same tooling. |
| 2 | **10.7** | Live now. Will report **49 of 188 implemented** — a number that flatters is worse than one that does not. |
| 3 | 10.4 | Bilingual parity. Story 1.5 already asserts catalogue parity and Arabic plural completeness — extend, don't duplicate. |
| 4 | 10.2 | The approver field. Blocked on a person. |
| — | 10.5 | Premature — needs the answer path exercised across epics. |
| — | 10.6 | Needs a person. |

## Non-obvious

- `docs/RULES.md` is v2.2. Its per-rule `Status:` column still says `proposed` and §5 still argues
  the pre-agreement position; a dated note records why. **Do not bulk-edit it** — that section is an
  argument, not a column, and belongs to the catalogue's owner.
- `rules/schema.py` enforces `R-<AREA>-<SLUG>`, a required `status`, and `withdrawn_because` on a
  rejected rule. `loader.py` raises on an id reused across files.
- `rules/data/names-floor.yaml` is the model for recording derived evidence beside a rule: the
  criterion stated **before** the measurement, plus separation, sample sizes and provenance. Story
  10.1 should look like that.
- `_bmad-output/implementation-artifacts/deferred-work.md` is the ledger of known gaps.

## Own

`rules/` (new modules; **never edit an existing rules data file** — add one) · `corpus/epic-10.yaml`
· new test files. Not `docs/RULES.md`.
