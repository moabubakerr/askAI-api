---
title: "Findings triage — 151 findings against the architecture"
status: draft
created: 2026-09-14
source: "FINDINGS-INDEX.md + the explanatory blocks in app/"
purpose: "Decide, per finding, whether it is structurally foreclosed, becomes a rule, or becomes a corpus entry"
---

# Findings triage

> ## ⚠ Read this first — a rule register already exists
>
> While checking what the new codebase should carry across, I found **a machine-readable register
> of 166 rules** in the system being replaced — structured, with provenance, generated on
> **2026-09-08** from a document called **`askai-business-logic-spec v1.0 · release 4.6.0`**.
>
> **That specification is not in this tree and has not been mentioned in this project.**
>
> It is the most valuable artifact found so far, and it changes the next step from **harvest** to
> **obtain, validate, adopt**. The analysis below stands as a coverage map against it, but its
> effort estimate is superseded — see §0.

## 0. The existing rule register

166 rules, recovered from the reference system, generated 2026-09-08 from
`askai-business-logic-spec v1.0` at release 4.6.0. Every one of them is reproduced in
[`RULES.md`](RULES.md). Each carries:

| Field | Contents |
|---|---|
| `id` | `P-n` for principles, `R-n` for rules — stable |
| `part` / `section` | the specification's own structure, Parts A–M |
| `statement` | the rule, in reviewable prose |
| `clauses` | 46 across 43 rules — concrete values and constants |
| `source` | provenance: *"Council brief; findings 1, 32, 34, 49"*, `§18, §19`, `design`, `code` |
| `change` | `code` 111 · `wording` 21 · `principle` 12 · `constant` 12 · `switch` 8 · `table` 2 |
| `live` | 31 rules map to the env vars or code symbols that implement them |

**The specification has eleven parts**, and they map closely onto the architecture:

| Rules | Part | Corresponds to |
|---:|---|---|
| 35 | C — Reading the question (READ) | `compile/`, AD-1, AD-19, AD-25 |
| 29 | G — Composition: what the card says | `assemble/`, AD-6, AD-18 |
| 20 | B — System map and the life of a request | AD-9, AD-15 |
| 18 | D — Resolution: which indicator, or which indicators | AD-25, AD-26 |
| 17 | F — Fetching and selecting the rows | `execute/`, AD-3, AD-4, AD-5 |
| 13 | H — Checks and guards | AD-7, AD-28 |
| 12 | A — Principles | the product commitments |
| 7 | E — Planning: from a shape to a contract | AD-1 |
| 6 | I — The renderer (optional, on request, gated) | AD-8, AD-28 |
| 6 | J — Modes and the interface | AD-10, AD-23 |
| 3 | M — The reviewed data tables (the editable business logic) | AD-11 |

Rule `P-1` is, almost verbatim, this project's product commitment 2:

> *"**The model never produces a number, a topic, a chart, a period or a verdict about approved
> data.** … A language model is used only (a) optionally, on request, to re-tell a finished card,
> under a gate that rejects anything the card did not already contain; and (b) on the separate
> external-source agent, whose content is always labelled as external."*

And `P-2` — *"**Code enforces, data decides.**"* — is AD-11 and AD-12 in five words.

### What this is worth, and where it falls short

**Worth:** the domain harvest is substantially complete. These rules are written, sectioned,
sourced, and already classified by the *kind* of change each represents — which is precisely
AD-11's "rules as data" taxonomy, arrived at independently.

**Short, in three ways:**

1. **The source document is missing.** The register was *generated from* `askai-business-logic-spec
   v1.0`; the register is the extract, not the original. The spec carries the rationale.
2. **It is behind.** Baseline is **release 4.6.0**; this tree is 4.7.0 plus four patches. Findings
   **153–157** postdate it and are cited by nothing — including 156 and 157, which are guard holes
   AD-28 now closes.
3. **82 of 151 findings are cited; 69 are not.** Of those 69, **18 are bucket A** (structural, and
   correctly absent from a rules register). The remaining ~51 are mostly early findings (2–50) where
   the terse `source` field may simply not cite what the statement covers — **that needs checking
   rule by rule, not assuming.**

### Revised next step

**Not "harvest the findings into rules." Instead:**

1. **Obtain `askai-business-logic-spec v1.0`** — the highest-value missing input in the project.
2. **Reconcile** the 166 rules against the 151 findings and against this PRD's 128 FRs; close the
   ~51 uncited domain findings and the 4.6.0→4.7.0+4 gap.
3. **Re-baseline** onto the new architecture: `change: code` rules become tests, `constant`/`switch`/
   `table` rules become `rules/*.yaml` data, `wording` rules become the message catalogue.
4. **Then** get it agreed — which was always the part engineering cannot do (FR-72a).

That is a review-and-adopt exercise of days, not a harvest of weeks.

---

| Bucket | Meaning | Count | Share |
|---|---|---|---|
| **A — Foreclosed** | the architecture makes this class of failure unrepresentable. Becomes **one test**, not a rule. | **40** | 26% |
| **B — Domain rule** | knowledge no architecture can derive. **Must be captured.** | **96** | 64% |
| **C — Instance / tuning** | an example of a rule already captured, or a measured constant. Becomes a **corpus entry**. | **6** | 4% |
| **D — Unreadable** | no explanatory block; must be read at its reference sites. | **7** | 5% |
| **E — Out of scope** | SPA or deferred operator surface. | **2** | 1% |

**The headline: 96 findings carry domain knowledge, but they collapse to roughly 38 rules.**
The findings are *instances*; the rules are what they have in common.

---

## The answer to "do I still have to list them?"

**Yes for bucket B — and no, not as 151 rules.**

A quarter of the register is genuinely dead: the architecture prevents those failures by
construction, and each becomes a single test that passes on day one. But the other two thirds is
knowledge that was bought with Council meetings and client escalations, and **no architecture
invents it**. AD-11 makes this concrete — rules load at startup and the service fails without them,
so "skip the harvest" means "do not ship".

The relief is in the collapse ratio. Fifteen separate findings about grain and period are **one**
precedence rule plus corpus entries. That is the payoff of modelling operation × scope orthogonally
rather than as nineteen intents.

---

## Bucket A — foreclosed by the architecture (40)

These become tests, not rules. Each cites the AD that makes the failure unrepresentable.

| Findings | The failure class | Foreclosed by |
|---|---|---|
| 16, 26, 29, 43, 45, 83, 86, 87, 109 | **Two components deciding the same thing** — a superlative sentence overwritten by a later rebuild; one question producing three different cards; a contract that checked coverage but not shape; one fact stated twice in different words | **AD-1** — the QuerySpec is bound once and no later stage may reinterpret it |
| 19, 54, 55, 70, 102 | **Declared but unwired** — five intents with composers that did not exist; `needs_chart` read by nothing; the library reachable only when a switch was on; the SET route built, tested and unreachable | **AD-2** + a test that every operation produces a plan and every planned block has a composer |
| 1, 3, 18 | **A figure escaping the display policy** — the chart rendering raw payload; the fix applied in one of five citation builders | **AD-18** — one formatter owns value→string |
| 36, 61 | **Provenance as an afterthought** — computed prose reading as though an analyst wrote it | **AD-6** — class is set at construction, immutable |
| 32, 76 | **The model producing more than it may** | **AD-8** |
| 156, 157 | **Guard holes** — a decimal glued to its scale defeating the number check; an attributed sentence moved onto another country | **AD-28** — post-normalisation number matching, and the named-entity check |
| 49, 84, 89 | **Approved and external blurring** | **AD-10** — no function takes both and returns one |
| 20, 25, 74, 151 | **Unbounded or serial IO** — a call with no timeout; five serial rungs costing eleven seconds; a keep-alive mismatch surfacing as a 502 | **AD-9** — every port call budgeted; parts run concurrently |
| 23, 128, 150 | **Failure indistinguishable from absence** — every error returning `None` and rendering as "no approved figures"; `unavailable` overloaded | **AD-15** — typed degradations, counted |
| 13, 17 | **A card contradicting itself** — a refusal in prose under an assertion in the headline; two different charts on two runs | **AD-1**, **AD-17** |
| 103, 116, 127, 146 | **A component trusting an upstream that did not deliver** — the reviewed vocabulary never consulted; HTML assumed pre-stripped | **AD-11**, **AD-25**, **AD-26** |
| 145 | The evidence package built once and kept | **AD-16** |

> **Sanity check on the architecture:** every AD in bucket A is load-bearing for at least one
> recorded failure. ADs that appear nowhere here — AD-3, AD-4, AD-5, AD-12, AD-13, AD-14, AD-19,
> AD-20, AD-21, AD-24, AD-27, AD-29, AD-30 — are justified by the **data facts** and the tester
> workbook instead, which is the complementary source. No AD is unjustified by both.

---

## Bucket B — domain rules (96 findings → ~38 rules)

Grouped by the rule they share. **The rule count is the work; the finding count is the evidence.**

| Family | Findings | Findings | Est. rules |
|---|---|---|---|
| **Grain & period binding** — the question's grain outranks the data's last row; relative periods; ordinal quarters; month names; a named period must not bypass alignment; which grain "right now" means | 2, 11, 35, 38, 46, 56, 96, 104, 108, 129, 133, 142, 143, 148, 152 | 15 | **4** |
| **The headline is the answer to the question** — not the last row, not the level on a change question, not a row at all when the answer is derived | 5, 8, 37, 59, 63, 91, 132, 141 | 8 | **2** |
| **Operations** — polar, superlative, sort, spread, series, conditional, article, capability, set, product-about-itself | 6, 7, 15, 58, 68, 75, 85, 88, 94, 110, 113, 114, 120, 134, 135, 139, 140 | 17 | **8** |
| **Refusal & absence** — never substitute a different indicator; an absence claim must be true; three reasons not one; name what was checked | 9, 27, 28, 101, 119, 125, 131, 137 | 8 | **3** |
| **Display** — the unit rides every row; one name per line; a rank is an ordinal; a change needs its reading | 50, 60, 73, 106, 118, 136, 147, 155 | 8 | **3** |
| **Language & bilingual** — Arabic plurals; the genitive construct; bidi first-strong; PDF hyphens; request words; verb agreement | 14, 47, 72, 79, 92, 115, 121, 123 | 8 | **4** |
| **Attribution & assessment** — the reading on request; whose analysis it is; polarity answers "is that good?" | 33, 34, 111, 112, 117, 144 | 6 | **3** |
| **Components & shares** — components exist; a sibling is not a component; the residual must not be named; the multiplication to refuse | 80, 97, 99, 100 | 4 | **3** |
| **Set scope & alignment** — one note per period; the comparison at the card's own period; scope narrowing stated; readings that reach further | 21, 81, 82, 95, 138, 154 | 6 | **3** |
| **Catalogue & groups** — the group not the category; "Sectors" names a category; who owns the indicator; the economy question | 4, 12, 67, 71, 90, 122 | 6 | **3** |
| **The answer's voice** — open in the reader's words; never echo a question that proposes its own answer; depth is the same question asked wider; a note covering nothing is not spoken | 51, 52, 53, 57, 77, 105 | 6 | **2** |
| **Follow-up & context** | 30, 42 | 2 | **1** |
| **Data-model rules** — inactive indicator behaviour; the accounting contract | 28, 155 | — | included above |

**Estimated total: ~38 rules from 96 findings — a 2.5:1 collapse.**

### The ones I would write first

Highest reference counts, and each is the head of a family:

| Finding | Refs | The rule |
|---|---|---|
| **94** | 22 | a question can be about several indicators at once |
| **68** | 22 | a question about articles is not a question about data |
| **34** | 19 | the reading, on request, and never unasked |
| **95** | 19 | the set, fetched concurrently and lined up on one period |
| **77** | 18 | depth is not a different question — it is the same question asked wider |
| **148** | 18 | the reader's period, when most of the set holds it |
| **80** | 17 | components exist, and they are in the detail table |
| **113** | 16 | a broad question wants an assessment, not an inventory |
| **135** | 16 | a question that carries no subject of its own |
| **129** | 15 | each indicator at its own latest period |

### One rule that is a *negative*

**Finding 133** — *"the rule that was tried here and taken back out."* A rule was implemented, fixed
one client case and broke twenty-two checks across five harnesses. **Rules that were rejected must
be captured too, with the reason**, or someone re-proposes them in eighteen months. The rule
catalogue needs a `rejected` status, not just `agreed`.

---

## Bucket C — instances and tuning (6)

Not rules. **Findings 10, 22, 24, 39** are four instances of "resolution must survive paraphrase and
Arabic morphology" — they become **corpus entries** with expected resolutions. **Findings 62, 124**
are measured constants already captured in the spine's inherited-tuning table.

## Bucket D — unreadable without more work (7)

**Findings 41, 44, 48, 78, 93, 130, 149** carry no explanatory block. `FINDINGS-INDEX.md` notes they
are written in prose forms a regex cannot anchor and are readable at their reference sites. Each is
1–2 references — small, but they must be read before the harvest is called complete, because an
unread finding is indistinguishable from a lost one.

## Bucket E — out of scope (2)

**Finding 31** — a stale browser bundle and missing cache headers. SPA.
**Finding 153** — the back-office phase 1. Deferred with the operator surface.

---

## What this means for the plan

1. **Bucket A is nearly free.** 40 findings become ~12 tests, because they collapse by AD rather
   than one-to-one. Write them early: they are the proof the architecture does what it claims, and
   any that cannot be written reveals an AD that does not actually foreclose what it says.
2. **Bucket B is the real work: ~38 rules.** Not 151. Estimate a day per rule including its
   rationale, its data fact and its corpus entries, and the harvest is weeks, not months.
3. **Bucket C and the F-series from the tester workbook seed the corpus**, which is needed anyway
   for the embedding decision and the retrieval floors (AD-30).
4. **Bucket D is a half-day** of reading reference sites, and should not be skipped.
5. **The rule catalogue needs a `rejected` status** — finding 133 is the proof.

**Sequence:** bucket A tests alongside the first vertical slice, bucket B by family in traffic order,
bucket D before anyone claims the harvest is done.
