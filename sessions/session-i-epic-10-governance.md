# Session I — Epic 10: rule governance and answer quality

**Read `AGENTS.md` first.** It carries the house rules, the VM facts and the build state.

This epic produces the evidence, not the capability. The founding complaint was *"I cannot see,
agree, or verify the business logic."* `docs/RULES.md` answers **see**. The architecture answers
**verify**. This epic is what makes *verify* demonstrable to someone who does not read code.

## What changed on 2026-09-16 — this unblocked you

**All 187 non-rejected rules are now agreed.** `R-157` stays `rejected` — it exists so it is not
re-proposed, not so it fires. The 49 rules encoded as data under `src/askai/rules/data/` carry
`status: agreed`, and `python -m askai.rules` reports:

```
50 rules from 12 files -- agreed 49 | proposed 0 | rejected 1
```

Story 1.4 built the loader to **read** status without gating on it, precisely so this would be a
data edit rather than a code change. It was: all 1,778 tests passed untouched.

So **Story 10.7's coverage gate can ship live rather than inert.** It was designed to ship inert
while zero rules were agreed, to avoid reporting a false pass. That reason is gone.

## The one thing still blocked

**`agreed_by` is `UNRECORDED`.** Agreement was given verbally and no approver was named, so nothing
claims one — writing a name nobody gave would be the exact failure FR-72a exists to prevent. The
rule schema has **no `agreed_by` field yet**, and adding it is Story 10.2's job.

**Do not invent an approver.** If nobody has been named when you get there, build the field, leave
it null, and say so — Story 10.2's own acceptance criteria call it blocked on naming a person.

## Stories

| Batch | Stories | State |
|---|---|---|
| **1** | **10.1 + 10.3** | Every rule traceable to the evidence that it holds; changing a rule is a reviewed change with an audit trail. Straightforward, same tooling. |
| **2** | **10.7** | The coverage gate, now live. Expect it to report honestly: **49 of 188 rules implemented, all agreed.** A number that flatters is worse than one that does not. |
| **3** | 10.4 | Bilingual parity asserted rather than assumed. Note Story 1.5 already asserts catalogue parity and Arabic plural completeness — extend, do not duplicate. |
| **4** | 10.2 | The approver field. Blocked on a person, not on code. |
| — | 10.5 | Answer quality as a continuously produced number. **Premature** — it needs the answer path exercised across epics, and operation dispatch only landed recently. |
| — | 10.6 | The stated limit and the human review that substitutes for it. Needs a person. |

## Useful facts

- `docs/RULES.md` is at **v2.2**, 188 rules. Its per-rule `Status:` column still reads `proposed`
  on every rule and §5 still argues the pre-agreement position; a dated note at the top of §5
  records what changed and that the section needs rewriting **by the catalogue's owner, not by
  find-and-replace**. Do not bulk-edit it.
- `src/askai/rules/schema.py` enforces `R-<AREA>-<SLUG>` ids, a required `status`, and that a
  `rejected` rule carries `withdrawn_because`. `loader.py` raises on an id reused across files.
- `rules/data/names-floor.yaml` is the model for recording *derived* evidence beside a rule: the
  criterion stated **before** the measurement, the separation, the sample sizes, the labelled set
  and the vector source it was derived against. Story 10.1 should look like that.
- `_bmad-output/implementation-artifacts/deferred-work.md` is the ledger of known gaps, several of
  which are traceability findings in their own right.

## Ownership

`src/askai/rules/` (new modules; **never edit an existing rules data file**, add a new one) ·
`corpus/epic-10.yaml` · new test files.

Do NOT edit `pyproject.toml`, `uv.lock`, any existing test file, `docs/RULES.md`, or anything under
`src/askai/domain/`, `compile/`, `execute/`, `assemble/`, `narrate/`, `adapters/`, `_bmad-output/`.
All five gates must pass; see `AGENTS.md`.
