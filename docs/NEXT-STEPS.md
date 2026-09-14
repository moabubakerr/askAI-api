# Next steps — who does what

Planning is complete. Nothing below is a document for its own sake; each task produces an input
the next one needs.

## Now — three tasks, no dependencies between them

### 1. Close the rule gaps → **Mary** (`bmad-agent-analyst`)

`RULES.md` holds 166 rules and states its own three gaps. Closing them is analysis, not
engineering.

- **Findings 153–157 postdate the 4.6.0 baseline and have no rule** — including 156 and 157, which
  are guard holes (a decimal glued to its scale defeating the number check; an attributed sentence
  moved onto another country).
- **~45 findings are cited by no rule.** The register's `source` field is terse, so some are
  certainly covered by a statement that does not name them — check rule by rule, do not assume.
- **Add a status to every rule: `agreed` · `proposed` · `rejected`.** Finding 133 records a rule
  that was implemented, broke twenty-two checks across five harnesses, and was withdrawn. A
  catalogue that records only what was adopted invites someone to re-propose it.

*In:* `RULES.md`, `FINDINGS-TRIAGE.md`, and the reference tree for the findings' own text.
*Out:* `RULES.md` at v2 — complete against release 4.7.0, every rule with a status.

### 2. Design the corpus and the retrieval evaluation → **Murat** (`bmad-tea` → `bmad-testarch-test-design`)

The largest single unblocking task. Three deliverables, and the second is easy to overlook.

- **The question corpus** — coverage over operation × scope × language × period form × data state,
  asserting on the **bound query**, never on prose.
- **The retrieval labelled set (AD-30).** Ground truth is mostly free: every `P04` analysis is
  already bound to a datapoint, so `(indicator, grain, period, country) → passage` is published
  ground truth. `names` ground truth comes from findings 42, 14 and 3. **Only the 67 articles need
  hand-labelling, and it is not optional** — nothing in the data constrains a wrong article.
  **The governing metric for articles is precision on questions that should return _nothing_.**
- **The parity baseline** — run the corpus against the *current* system, so "better" becomes a
  number rather than an opinion.

*In:* `PRD.md` §7, `ARCHITECTURE-SPINE.md` AD-30, `RULES.md`, the tester workbook.
*Out:* the coverage matrix, the corpus format, the labelled sets, the baseline score.

### 3. Repo context → `bmad-project-context`

Produce `AGENTS.md` for this repository so every later agent starts oriented.

---

## Next — once 1 and 2 are in hand

| # | Task | Agent / skill | Why it waits |
|---|---|---|---|
| 4 | **Epics and stories** — one epic per PRD capability group, one story per operation, with rules as acceptance criteria | **John** · `bmad-create-epics-and-stories` | stories written before the rules have status get rewritten |
| 5 | **Test framework and fixtures**, including the corpus runner | **Murat** · `bmad-testarch-framework` | needs the corpus format from task 2 |
| 6 | **CI quality gates** — corpus, `import-linter`, `mypy --strict`, `ruff` | **Murat** · `bmad-testarch-ci` | needs the framework |
| 7 | **Readiness check, then sprint status** | `bmad-sprint-planning` | needs the stories |

---

## Then — build, capability by capability

| # | Task | Agent / skill |
|---|---|---|
| 8 | **Red-phase acceptance tests**, per capability, before its code | **Murat** · `bmad-testarch-atdd` |
| 9 | **Implementation**, story by story | **Amelia** · `bmad-agent-dev` / `bmad-build` |
| 10 | **Per-story review** | `bmad-code-review` |
| 11 | **Rule → test traceability** | **Murat** · `bmad-testarch-trace` |
| 12 | **Latency and NFR evidence** | **Murat** · `bmad-testarch-nfr` |
| 13 | **Retrospective per epic** | `bmad-retrospective` |

**Build order:** `core/` first — it is pure, depends on nothing, and is the cheapest test of whether
the architecture survives a type checker. Then the read model and refresh, then the index, then one
capability end to end through every layer before building the rest.

---

## Not needed now

- **Winston** (`bmad-agent-architect`) — the spine is final. He returns only to change an AD, which
  is a deliberate act, not a side effect.
- **Sally** (`bmad-agent-ux-designer`) — the SPA is out of scope.
- **`bmad-correct-course`** — if scope moves materially, before anything else.

## Still needs a person, not an agent

| Open item | Blocks |
|---|---|
| **Who approves the rule catalogue?** | `RULES.md` answers *see*; the architecture answers *verify*; **agree** needs someone with standing (PRD FR-72a). Without it the rebuild can satisfy all 128 requirements and still meet the original complaint. |
| Does indicator-svc expose the group layer the export carries? | FR-29 |
| Does any platform assert a caller identity? | AD-24, NFR-9 |
| Is `/api/read` a real route, or another role in the lens mapping? | one route |
