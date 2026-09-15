---
title: "Ask AI — Rule Catalogue"
status: v2.1 — all three register gaps closed; agreement outstanding
created: 2026-09-14
updated: 2026-09-15
rules: 188
version: 2.1
statuses: "proposed 187 · rejected 1 · agreed 0"
baseline: "askai-business-logic-spec v1.0 · release 4.6.0, plus findings 154-157 and the 36 uncited findings read at source in 4.7.0+4"
governs: "the answer engine — see ARCHITECTURE-SPINE.md and prd.md"
---

# Ask AI — Rule Catalogue

**188 rules. Every one enumerable, sourced, status-bearing, and mapped to what enforces it.**

> **v2.1 — 2026-09-15.** The register's three stated gaps are closed. 19 rules recovered by reading
> the 36 uncited findings at their own reference sites (Part V2), 17 more findings cited on rules
> that already stated them, findings 154 and 155 resolved, and `R-157`'s statement corrected from
> inference to source. **No rule is `agreed`, and that is deliberate — see §5.**

## 1. Where these rules come from

They were **not written for this rebuild.** They were recovered from a machine-readable register
held by the system being replaced, generated on 2026-09-08 from a document called
**`askai-business-logic-spec v1.0 · release 4.6.0`**.

**That specification no longer exists.** Nobody holds a copy. The register is the extract that
survived it.

Nothing irreplaceable was lost. The spec carried the rules *and* their rationale; the register
carries the rules, and **131 of the 166 cite the findings they came from** — so the rationale has
been reattached here from the findings' own explanatory text in `app/`. Each rule below carries:

- its **statement**, verbatim from the register — not paraphrased
- its **clauses** — the concrete values, where it has them
- **Becomes:** where it lives in the new system
- **Source:** its provenance — a Council brief, a specification section, or findings
- **Implemented at:** the switch or symbol that carries it today, where one is recorded
- **Why:** the recorded failure that produced it

## 2. What kind of rule each one is

The register classifies every rule by the *kind* of thing it changes. That classification is the
migration plan, and it arrived at the same taxonomy the architecture did independently:

| Kind | Count | Becomes, in the new codebase |
|---:|---|---|
| `code` | **113** | a test — behaviour the corpus or a unit test asserts |
| `wording` | **21** | the bilingual message catalogue (`messages/`) |
| `principle` | **12** | already stated as a PRD commitment — verify, do not restate |
| `constant` | **12** | `rules/*.yaml` — a published value the engine reads |
| `switch` | **8** | `rules/*.yaml` — a toggle or budget, held as data |
| `table` | **2** | `rules/*.yaml` — a reviewed lookup |
| `rejected` | **1** | nothing — recorded so it is not re-proposed (`R-157`) |

**22 rules are data and can be carried across immediately.** 21 more become message-catalogue
entries. The 111 `code` rules are acceptance criteria, read as each capability is built — not a
phase of their own.

**31 rules record the env var or symbol that implements them today**, which makes the old system
readable as the reference it is meant to be.

## 3. How the specification is structured

Eleven parts, and they map onto the architecture closely enough to be worth noticing — two
independent attempts at the same system arriving at the same seams:

| Rules | Part | Architecture |
|---:|---|---|
| 35 | C — Reading the question (READ) | `compile/` · AD-1, AD-19, AD-25 |
| 29 | G — Composition: what the card says | `assemble/` · AD-6, AD-18 |
| 20 | B — System map and the life of a request | AD-9, AD-15 |
| 18 | D — Resolution: which indicator, or which indicators | AD-25, AD-26 |
| 17 | F — Fetching and selecting the rows | `execute/` · AD-3, AD-4, AD-5 |
| 16 | H — Checks and guards | AD-7, AD-28 |
| 12 | A — Principles | the product commitments |
| 7 | E — Planning: from a shape to a contract | AD-1 |
| 6 | I — The renderer (optional, on request, gated) | AD-8, AD-28 |
| 6 | J — Modes and the interface | AD-10, AD-23 |
| 3 | M — The reviewed data tables (the editable business logic) | AD-11 |

## 4. What is missing, and must be closed

**All three gaps are now closed.** v2 assigned a status to every rule and wrote the two guard rules;
v2.1 read the 36 uncited findings at their own reference sites and closed the coverage gap. What
remains open is named in §5, and it is not a gap in the catalogue.

### 4.1 It is a release behind — **closed**

The register's baseline is **release 4.6.0**; the reference tree is **4.7.0 plus four patches**.
Findings **153–157** postdate it.

| Finding | Resolution |
|---|---|
| **153** — the back-office phase 1 | **Correctly no rule** — out of scope with the deferred operator surface |
| **154** — the executive question and its spelling | **`R-164`** |
| **155** — the accounting contract | **`R-127`**, which already stated it; the citation was added |
| **156** — a decimal glued to its scale | **`R-155`** |
| **157** — an attributed sentence moved onto another country | **`R-156`** |

### 4.2 Sixty-nine findings were cited by no rule — **closed**

**82 findings were cited by at least one rule; 69 were not.** v2.1 read every one of the actionable
ones at the `file:line` the findings index gives for it, and the gap resolves as follows:

| Bucket | Count | Resolution |
|---|---:|---|
| **A** — foreclosed by the architecture | 22 | Correctly absent from a rules register. Each becomes a test. Findings 156 and 157 were given rules anyway, because a guard hole deserves both |
| **B** — domain knowledge | **36** | **Read and resolved: 19 new rules, 17 citations added to rules that already said it** |
| **C** — instances and tuning | 5 | Corpus entries and measured constants, not rules |
| **D** — no explanatory block | 4 | **Read at their reference sites** — 44 → `P-6`, 48 → `R-97`, 78 → `R-176`, 93 → `R-162` |
| **E** — out of scope | 2 | 31 (the SPA), 153 (the back-office) |
| **?** — appeared in no bucket | 6 | **They do not exist** — see below |

#### The six that were never issued

**Findings 40, 64, 65, 66, 98 and 107 are phantom numbers.** The findings index is explicit:
*"Numbers never issued in this tree: 0 occurrences anywhere, including `tests/` and the JSON data.
Most likely withdrawn, merged, or raised against the SPA, which is not in this tree. Nothing to
recover."*

The v2 revision of this section called them *"a gap the register did not know it had"* and *"the
highest-value item on this list, because a finding nobody has read is indistinguishable from one
that was lost."* **That was wrong**, and it is recorded rather than quietly deleted: the answer was
in the index all along, and the error was checking this repository for the findings source and
stopping there.

#### What the 36 actually contained

**Nineteen were genuine gaps** and became `R-158` – `R-176`, collected in **Part V2** rather than
threaded into Parts A–M, because they were never in `askai-business-logic-spec v1.0` and inserting
them would misrepresent what that specification said. Each names the part it would belong to.

**Seventeen needed no rule.** The catalogue already stated them and the terse `source` field simply
did not name them — exactly what v1 suspected. Each is now cited on the rule that covers it, marked
`**v2 also covers:**`:

| Finding | Already stated by | Finding | Already stated by |
|---|---|---|---|
| 2 — a growth question answered with a level | `R-132` | 67 — the group, not the category | `R-58` |
| 4 — the economy question answered with one indicator | `R-32` | 79 — the hyphens that came in from a PDF | `R-23` |
| 5 — a superlative answered with the newest row | `R-39` | 112 — polarity answers "are we going the right way" | `P-2` |
| 21 — a group scope dropped in silence | `P-3` | 123 — "our economy" too | `R-32` |
| 33 — six correct readings and no reasoning | `P-9` | 134 — the question a Council paper is written from | `R-112` |
| 42 — Arabic morphology defeats token overlap | `R-22` | 136 — "unchanged" beside a magnitude | `R-103` |
| 44 — three periods for one value | `P-6` | 137 — the ones set aside were never answered | `R-131` |
| 48 — the gap owns its sentence | `R-97` | 155 — the accounting contract | `R-127` |
| 59 — the headline is a derived quantity | `R-126` | | |

**The 2.5:1 collapse the triage predicted held**: 36 findings, 19 rules.

### 4.3 There is no `rejected` status — **closed**

**Every one of the 188 rules carries a status.**

| Status | Count | Meaning |
|---|---:|---|
| `proposed` | **187** | Described, sourced and reviewable — **not yet agreed by anyone** |
| `rejected` | **1** | `R-157`, with its reason |
| `agreed` | **0** | See §5. This is not an oversight |

**`R-157` records the rule that was withdrawn.** Finding 133's rule was implemented, fixed the
client's D5 case, and **broke twenty-two checks across five harnesses** — because it replaced
`R-95`, `R-104` and `R-118`, a deliberate and tested design, for *every* set question rather than
for the questions that want it. The entry exists so nobody re-proposes it in eighteen months.

> **A correction worth keeping.** v2 wrote `R-157`'s statement by inference — the register cites
> finding 133 only as supporting evidence under `R-30`, and never carried the withdrawn rule's own
> wording — and flagged it as reconstructed. v2.1 read the finding and **the inference was wrong**:
> the withdrawn rule triggered on the *data* (a member publishing a newer reading), not on the
> question's shape. The statement is corrected and now verbatim-sourced. The flag did its job.

**Twelve rules are `proposed` *(agreed candidate)*** — the Part A principles, each already a
ratified PRD commitment. They are the obvious first batch for whoever holds the pen. Flagging them
is as far as an analyst may go; marking them `agreed` would be an analyst asserting agreement on a
stakeholder's behalf, which is what FR-72a exists to prevent.

### 4.4 What each revision changed

| | v1 | v2 | v2.1 |
|---|---|---|---|
| Rules | 166 | 169 | **188** |
| Rules with a status | 0 | 169 | **188** |
| Findings 153–157 covered | 0 of 5 | 3 of 5 | **5 of 5** |
| Findings cited by no rule | 69, "roughly 45" actionable | 69, bucketed | **0 actionable** |
| Withdrawn rules recorded | none | 1, statement inferred | **1, statement verified** |
| Findings read at source | — | — | **40** |

## 5. What this catalogue cannot do

It cannot agree itself.

`see` is answered by this document. `verify` is answered by the architecture — 30 decision records,
a corpus, and a CI gate. **`agree` requires a person with the standing to agree**, and that person
has not been named (PRD FR-72a).

**v2 makes the gap visible rather than closing it.** Every rule now carries a status, and **every
one of them says `proposed`**. That is not an oversight and not a placeholder to be bulk-edited: it
is the honest state of a catalogue that describes a system accurately and has never been agreed by
anyone. The twelve Part A principles are flagged as **agreed candidates** because each is already a
ratified PRD commitment — they are the obvious first batch, and an analyst flagging them is as far
as this can be carried without a person.

A column of 169 `proposed` rules is now the most direct statement of the original complaint that
exists anywhere in this project. Until someone moves some of them to `agreed`, this is a very good
description of what the system does. It is not yet an agreement about what the system *should* do —
and that distinction is the whole of the original complaint.

---

## 6. The rules

Statements are verbatim from the register. Ids are stable and must not be renumbered.
## Part A — Principles


### Principles

#### `P-1`

**The model never produces a number, a topic, a chart, a period or a verdict about approved data.** Every figure on a card is read from an approved row or computed by code from approved rows. A language model is used only (a) optionally, on request, to re-tell a finished card, under a gate that rejects anything the card did not already contain; and (b) on the separate external-source agent, whose content is always labelled as external.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** Council brief; findings 1, 32, 34, 49 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 1* — the tooltip read "2022 / value : 686.131074" - the raw
  - *finding 32* — The model may name the SUBJECT. It may not produce anything else.
  - *finding 34* — The reading, on request, and never unasked.
  - *finding 49* — the pipeline declined to answer for agent=%r -

#### `P-2`

**Code enforces, data decides.** Whether a move is favourable is the catalogue's Polarity field. Whether a reading exists is the database. Which indicators form a group is the CMS. The code applies those facts; it never guesses them from names.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** findings 83, 94, 113, 146 · **v2 also covers:** finding 112 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 83* — THE ASSESSMENT. Built ONCE, from what has already been fetched.
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE
  - *finding 113* — A BROAD QUESTION WANTS AN ASSESSMENT, NOT AN INVENTORY.
  - *finding 146* — THE REVIEWED DIMENSION TABLE, loaded like the tiers. Fail-soft: without it

#### `P-3`

**Never answer a different question than the one asked without saying so.** A follow-up that borrows its subject, a period that had to be substituted, a subject matched by similarity rather than by name, a set aligned on a period other than the one asked — each is disclosed on the card in one sentence.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** finding 32 and throughout · **v2 also covers:** finding 21 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 32* — The model may name the SUBJECT. It may not produce anything else.

#### `P-4`

**Never show a value without naming what it measures.** Every figure carries its indicator name, its unit and its period; a derived figure says it is derived and from what.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** findings 63, 141 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 63* — the growth rate outranks every row-derived
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `P-5`

**Absence is proven by asking, never inferred.** "The approved data holds no reading" may be said only after the database was asked. A vocabulary miss and an outage are reported as what they are, in different words.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** finding 125 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 125* — WHY THERE IS NO ANSWER. THREE REASONS, AND WE HAVE BEEN GIVING ONE.

#### `P-6`

**One selection of rows, shared.** The headline, the sentence, the change, the chart and the citations all read the same selection, so no card can name two periods for one value.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** pipeline rewrite (findings 11–41) · **v2 also covers:** finding 44 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 11* — "How many international visitors arrived in Qatar in May 2025?" returned

#### `P-7`

**The biggest number on the card must be the answer to the question.** A shape with no single answer (a series, a set) has no headline number.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** finding 63 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 63* — the growth rate outranks every row-derived

#### `P-8`

**A mode may show less than another; it may never show something the other does not.** Executive Lens is a filter over the same answer, never a different answer.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** finding 34 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 34* — The reading, on request, and never unasked.

#### `P-9`

**The computed text never states a cause, a forecast, a recommendation or a magnitude adjective.** Causes appear only inside a quoted SCEAI analyst note, with its byline. There is no score, no weighting and no index.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** findings 83, 113; §5, §7 · **v2 also covers:** finding 33 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 83* — THE ASSESSMENT. Built ONCE, from what has already been fetched.
  - *finding 113* — A BROAD QUESTION WANTS AN ASSESSMENT, NOT AN INVENTORY.

#### `P-10`

**Approved data is never shown under an external badge, and external content is never shown as approved.** Provenance is decided by which source produced the text.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** finding 49 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

**Why —**
  - *finding 49* — the pipeline declined to answer for agent=%r -

#### `P-11`

**The system's internal vocabulary never reaches a reader.** Words such as "approved readings", "polarity", "ledger" or "count of directions" are for the evidence panel and the log, not the card.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** §18, §19 · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*

#### `P-12`

**Every rule is reproducible and testable without a model.** The whole pipeline runs in the test harness with no application, no database and no model; a rule that cannot be exercised that way is not accepted.

**Becomes:** the PRD's commitments — already stated; verify, do not restate · **Source:** project practice (35 harnesses, 3,432 checks) · **Status:** `proposed` *(agreed candidate — already a ratified PRD commitment)*


## Part B — System map and the life of a request


### B2. The request

#### `R-1`

The answer language is the language of the current question (Arabic script anywhere in it → Arabic), never the language of the previous exchange.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** BRD §13.1; finding 27 · **Status:** `proposed`
**Why —**
  - *finding 27* — «هل هناك شركات تكنولوجيا مالية جديدة تم افتتاحها في عام 2025؟» answered

#### `R-2`

The interface sends the last three exchanges. The server reads the previous **questions** for context (Part C6) and the previous **answer** only to resolve "the article" (Part D5). It never parses its own prose to recover a subject.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 135 · **Status:** `proposed`
**Why —**
  - *finding 135* — A QUESTION THAT CARRIES NO SUBJECT OF ITS OWN.

#### `R-3`

A caller that does not declare `tables` receives any table as one line per row (`- **Indicator** · reading · period · change · signal`); the facts and their order are identical.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so


### B3. The routes and the agent gate

#### `R-4`

The library and the pipeline answer **only** for an approved-data agent (an agent configured with charts, and not the combined agent). The external agent and the combined view are answered by the chain, which owns the external fetch and its attribution.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 49 (P-10) · **Implemented at:** `ASKAI_PIPELINE` · **Status:** `proposed`
**Why —**
  - *finding 49* — the pipeline declined to answer for agent=%r -

#### `R-5`

The pipeline gate is asked of the **prepared** question (after resolution and the set decision), not of the raw intent — so a question the catalogue-or-overview reader would have claimed still reaches the set route when two or more indicators resolve from it.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 102 · **Status:** `proposed`
**Why —**
  - *finding 102* — THE SET ROUTE WAS BUILT, TESTED, AND UNREACHABLE.

#### `R-6`

Agents are configured, not hard-coded: `ASKAI_AGENTS` = `id

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** label_en · **Implemented at:** `ASKAI_AGENTS` · **Status:** `proposed`
### B4. Budgets and timeouts

#### `R-7`

The whole answer is held to one budget; an overrun returns a 200 card that says the answer did not arrive within N seconds and nothing was checked.

- **Value:** `ASKAI_ASK_BUDGET_S` = 85 s (under the edge's 100 s)

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 150 · **Implemented at:** `ASKAI_ASK_BUDGET_S`, `_ASK_BUDGET_S` · **Status:** `proposed`
**Why —**
  - *finding 150* — "THE SAME QUESTION SOMETIMES GETS A RESPONSE AND SOMETIMES NOT."

#### `R-8`

Idle connections are kept open longer than the tunnel connector's 90 s pool timeout, so a question rarely needs a fresh connection.

- **Value:** `ASKAI_KEEPALIVE_S` = 120 s

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 151 · **Implemented at:** `ASKAI_KEEPALIVE_S`, `_KEEPALIVE_S` · **Status:** `proposed`
**Why —**
  - *finding 151* — "HTTP 502 AFTER 21 s" - the failure card from 4.5.4 finally said which layer.

#### `R-9`

The interface abandons a request after 120 s (later than the edge's 100 s, so a gateway status is seen before the page gives up), names the layer, status and seconds on the failure card, and re-sends a transient failure (5xx, 429, 408, dropped connection, timeout) exactly once — never any other 4xx, and never a 401.

- **Value:** 120 s; one retry

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 150 · **Implemented at:** `_ASK_BUDGET_S`, `_KEEPALIVE_S`, `_LADDER_BUDGET`, `_WIDEN_TIMEOUT` · **Status:** `proposed`
**Why —**
  - *finding 150* — "THE SAME QUESTION SOMETIMES GETS A RESPONSE AND SOMETIMES NOT."

#### `R-10`

Resolution ladder budget; widening lookups run concurrently with a shorter timeout each.

- **Value:** 8 s total; 3 s per widening lookup

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** findings 25, 74 · **Implemented at:** `_LADDER_BUDGET`, `_WIDEN_TIMEOUT` · **Status:** `proposed`
**Why —**
  - *finding 25* — This call had no timeout of any kind.
  - *finding 74* — THE WIDENING WAS SERIAL, AND IT COST THE READER ELEVEN SECONDS.

#### `R-11`

Set resolution, set fetch, set notes, component fetch and journey fetch each have their own budget so that the sum stays inside R-7.

- **Value:** 6 s / 12 s / 6 s / 6 s / 6 s

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** findings 25, 74, 95 · **Implemented at:** `_SET_RESOLVE_BUDGET_S`, `_SET_FETCH_BUDGET_S`, `_SET_NOTES_BUDGET_S`, `_COMPONENT_BUDGET_S`, `_JOURNEY_BUDGET_S` · **Status:** `proposed`
**Why —**
  - *finding 25* — This call had no timeout of any kind.
  - *finding 74* — THE WIDENING WAS SERIAL, AND IT COST THE READER ELEVEN SECONDS.
  - *finding 95* — THE SET, FETCHED CONCURRENTLY AND LINED UP ON ONE PERIOD.

#### `R-12`

The legacy agent path and the external fetch have their own budgets.

- **Value:** 45 s / 90 s

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 25 · **Implemented at:** `_AGENT_BUDGET`, `_EXT_BUDGET` · **Status:** `proposed`
**Why —**
  - *finding 25* — This call had no timeout of any kind.

#### `R-13`

The renderer (Part I) has a request budget and a model budget.

- **Value:** 60 s / 20 s

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 145 · **Implemented at:** `_RENDER_BUDGET`, `_READING_BUDGET` · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.


### B5. One log line per request

#### `R-14`

Every `/api/ask` writes one line: `finding150: /api/ask 3.2s route=pipeline shape=set agent=sceai chars=1180 q='…'`. An overrun writes `finding150: /api/ask OVERRAN the 85s budget …` at error level; a non-200 pass-through writes `status=non-200`. This line is the primary source of the KPIs in Part K.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 150 · **Status:** `proposed`
**Why —**
  - *finding 150* — "THE SAME QUESTION SOMETIMES GETS A RESPONSE AND SOMETIMES NOT."

#### `R-15`

The reading side writes `finding145: read via … accepted/rejected: reason`, counted in `/api/read/stats` (asked, rendered, rejected by reason, model unavailable, cache size).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 145 · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.

#### `R-16`

Every stage writes its decision with its finding number (`finding103: … matched the reviewed surface …`, `finding95: 6 indicators at 2025 (annual), 2 stale, 0 absent`, `finding129: snapshot (asked for) …`). The decision trace screen in Part N is these lines, per request.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** project practice · **Status:** `proposed`
**Why —**
  - *finding 95* — THE SET, FETCHED CONCURRENTLY AND LINED UP ON ONE PERIOD.
  - *finding 103* — THE REVIEWED VOCABULARY WAS NEVER CONSULTED.
  - *finding 129* — THE QUESTION THAT WANTS EACH INDICATOR AT ITS OWN LATEST PERIOD.


### B6. The failure cards

#### `R-17` — Timeout

R-7 overran

- **Wording (EN):** "The answer did not arrive within 85 seconds, so nothing was checked. This is not a statement about the data. Please try again."

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-18` — Handler failure

An exception inside the answer (always a 200, never a 500)

- **Wording (EN):** "Something failed inside this service … no indicator and no figure was checked."

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-19` — Interface failure

No usable reply reached the page

- **Wording (EN):** "No answer arrived from the service. Please try again." + the detail: "(HTTP 502 after 21 s, sent again once)", "(no reply within 120 s)", "(connection dropped)".

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-20` — Unreachable data

indicator-svc raised or reported itself unavailable (finding 128)

- **Wording (EN):** The card says the approved data could not be reached — and never that it is absent.

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
**Why —**
  - *finding 128* — `unavailable` IS OVERLOADED, AND THE OVERLOAD ALMOST SHIPPED A NEW


## Part C — Reading the question (READ)


### C1. Language and normalisation

#### `R-21`

Arabic is detected by script. Both English and Arabic texts of every sentence are composed side by side by the same composer; the card shows the one matching the question.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** R-1 · **Status:** `proposed`
#### `R-22`

Before matching, text is normalised: Unicode NFKC, case-folded, diacritics removed, Arabic letter variants folded (أ إ آ → ا, ى → ي, ة → ه, tatweel removed), hyphens and runs of whitespace collapsed. The same normalisation is applied to the question and to every reviewed surface, so a spelling difference never decides a match.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 103, 115 · **v2 also covers:** finding 42 · **Status:** `proposed`
**Why —**
  - *finding 103* — THE REVIEWED VOCABULARY WAS NEVER CONSULTED.
  - *finding 115* — THE LINE THAT DECIDES WHICH WAY THE PARAGRAPH READS.

#### `R-23`

Analyst text from the CMS is repaired for the 44 hyphenation breaks the export carries ("in-crease" → "increase") from `hyphen_fixes.json`; 722 legitimate hyphens are left alone.

**Becomes:** `rules/*.yaml` — a reviewed lookup table · **Source:** finding 86 · **v2 also covers:** finding 79 · **Status:** `proposed`
**Why —**
  - *finding 86* — `missing_sentence` is NOT in this list, and that is deliberate.


### C2. The intent table — "the most specific claim wins"

#### `R-24`

The order above is the only order. A new intent is inserted at the position its specificity earns, and the harness asserts the position.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** pipeline design · **Status:** `proposed`
#### `R-25`

Intents that answer from the catalogue or the library rather than from rows (CATALOGUE, CAPABILITY, OVERVIEW, LIBRARY, ARTICLE, ABSENCE) never resolve an indicator and never carry a figure.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **Status:** `proposed`
#### `R-26`

When the library switch is off, ARTICLE and LIBRARY are unreachable — the intent cannot be claimed, so no reader meets an empty library card. Absence of a capability is expressed as unreachability, never as an empty answer.

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** findings 54, 68 · **Implemented at:** `ASKAI_ARTICLES` · **Status:** `proposed`
**Why —**
  - *finding 54* — THE PIPELINE ANSWERS ONLY WHAT IT CAN ACTUALLY COMPOSE.
  - *finding 68* — A question about ARTICLES is not a question about data.


### C3. Flags — the same shape, asked wider or narrower

#### `R-27` — `depth`

"impact", "effect", "why", "explain", "analysis", "assess", "brief", "tell me about", "context", «أثر», «لماذا», «تحليل».

- **Effect:** Strictly additive: adds *what it measures* (the CMS definition), the breakdown into components, the peer table and the full analyst note. Never applied to a set card (eight definitions is a wall, not depth).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 77 · **Status:** `proposed`
**Why —**
  - *finding 77* — DEPTH IS NOT A DIFFERENT QUESTION. IT IS THE SAME QUESTION, ASKED WIDER.

#### `R-28` — `wants_change`

"what is/was happening to", "what happened to", "how is/are/did", "going up or down", "is X growing/rising/falling", "improved / deteriorated", "year on year", "YoY", "compared with", «ماذا حدث», «كيف تغير», «هل ارتفع».

- **Effect:** One extra clause: the move against the same period a year earlier, after the level. Not on FORECAST or SCENARIO (a refusal never carries "that is up 2.0%").

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 91, 109, 144, 145 · **Status:** `proposed`
**Why —**
  - *finding 91* — A QUESTION ABOUT MOVEMENT WANTS THE MOVEMENT.
  - *finding 109* — "THAT IS" NEEDS SOMETHING TO REFER TO.
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.

#### `R-29` — `wants_set`

"snapshot", "overview", "across", "dashboard", "which ones / which indicators", "which are", "what does the data say", "the national / diversification / labour / economic indicators", "indicators say/show/tell", a list of names joined by "and / , / و".

- **Effect:** Permits the set route (Part D3). A flag only — the set exists only if ≥ 2 indicators resolve.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 94 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE

#### `R-30` — `snapshot`

A snapshot phrase ("latest snapshot", "snapshot of", "give me the latest", "where do we stand", "what do the indicators tell", "latest readings/figures", «أحدث صورة», «الوضع الحالي») or the executive phrasing, **and no period named** (R-154); also a level comparison of named indicators with no period and no superlative (finding 133).

- **Effect:** Each indicator at its own latest period, with the period on every line, instead of one aligned period.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 129, 133 · **Status:** `proposed`
**Why —**
  - *finding 129* — THE QUESTION THAT WANTS EACH INDICATOR AT ITS OWN LATEST PERIOD.
  - *finding 133* — THE RULE THAT WAS TRIED HERE AND TAKEN BACK OUT.

#### `R-31` — `snapshot_asked`

The reader asked for the picture (R-30's phrases or the executive phrasing), as opposed to a level comparison that merely had to be read at mixed periods.

- **Effect:** Selects the consolidated §17 structure (G5) rather than the set composers.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-32` — `executive`

The executive phrasing: "how is / was / has the economy (doing, performing, faring)", "how did the economy perform", "state of the economy", "give me an overview", "executive summary", "how are we doing", "the main signals a decision-maker should watch", "key takeaways", «كيف حال الاقتصاد», «كيف كان أداء الاقتصاد», «حالة الاقتصاد», «ملخص تنفيذي».

- **Effect:** The SET shape's four-sentence mode; since 4.5.0 both it and the snapshot share one composer.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 113 · **v2 also covers:** findings 4, 123 · **Status:** `proposed`
**Why —**
  - *finding 113* — A BROAD QUESTION WANTS AN ASSESSMENT, NOT AN INVENTORY.

#### `R-33` — `wants_amount`

"how much" (not "how much of", not followed by share/percentage), "what was the amount / value / level / size / total", "how large / big was", "in QAR", «كم بلغ», «ما مقدار», «ما حجم».

- **Effect:** Where the catalogue publishes only shares of the quantity, the amount is derived and said to be derived (Part D4).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 141 · **Status:** `proposed`
**Why —**
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `R-34` — `wants_complement`

"the rest", "remainder", "what is left", "100 minus", "what share still comes from", «الباقي», «المتبقي».

- **Effect:** The complement of a share (100 − x), labelled derived, without naming the remainder as anything the catalogue does not publish.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 99 · **Status:** `proposed`
**Why —**
  - *finding 99* — THE REST OF A SHARE, AND WHAT IT MUST NOT BE CALLED.

#### `R-35` — `wants_product`

"so that is about N", "multiply", "times", "×", "would that give / mean", "works out to", «هل يعني ذلك», «بضرب».

- **Effect:** A multiplication the **reader** proposed, computed from exactly two readings and only when the denominator guard passes (G4).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 100 · **Status:** `proposed`
**Why —**
  - *finding 100* — THE MULTIPLICATION THE CLIENT MOST WANTS US TO REFUSE.

#### `R-36` — `wants_verdict`

"is that good / bad / positive / worrying?", "good or bad", «هل هذا جيد».

- **Effect:** The catalogue's polarity read against the move — never an opinion of the system's.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 144 · **Status:** `proposed`
**Why —**
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.

#### `R-37` — `wants_peers`

"how does that compare?", "compared to what?", «كيف يقارن هذا».

- **Effect:** The peer table where benchmarks are published, without the rest of the depth card.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 144 · **Status:** `proposed`
**Why —**
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.

#### `R-38` — `cross_country`

The question ranges over countries ("which country had the lowest inflation").

- **Effect:** The peer table leads and Qatar's own reading follows; the period extreme is not shown in their place.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 119 · **Status:** `proposed`
**Why —**
  - *finding 119* — "WHICH COUNTRY HAD THE LOWEST INFLATION" WAS ANSWERED WITH A YEAR.

#### `R-39` — `superlative`

Which extreme (max / min) the words asked for.

- **Effect:** The composer leads with the extreme that was asked for, not always the maximum.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 119 · **v2 also covers:** finding 5 · **Status:** `proposed`
**Why —**
  - *finding 119* — "WHICH COUNTRY HAD THE LOWEST INFLATION" WAS ANSWERED WITH A YEAR.

#### `R-40` — `period_unparsed`

The question plainly carries a period phrase (a year, "N years/quarters/months", «سنوات») and none could be read from it.

- **Effect:** The card says a period could not be read and shows the latest instead; the log reports it so the missing word is found by the system rather than by a screenshot. A granularity word alone ("monthly") is not a period.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 53, 54 · **Status:** `proposed`
**Why —**
  - *finding 53* — and never echo a period phrase this system could not read -
  - *finding 54* — THE PIPELINE ANSWERS ONLY WHAT IT CAN ACTUALLY COMPOSE.


### C4. Periods and granularity

#### `R-41`

Periods are read from the question by the shared period reader (years, quarters "Q1 2026" / "2026-Q1", months, "last N years", "from 2022 to 2025", "the latest 3 years", Arabic forms). A year expands to its quarters and months when the indicator publishes at those grains, so one list serves an indicator at any interval.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 41, 53 · **Status:** `proposed`
**Why —**
  - *finding 41* — —
  - *finding 53* — and never echo a period phrase this system could not read -

#### `R-42`

Granularity is read separately ("monthly", "quarterly", "annual"). When the reader names no period, the granularity they named is the only thing they said about shape, and it decides the interval; when they named periods, the periods decide.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 56 · **Status:** `proposed`
**Why —**
  - *finding 56* — "Show the trend of Inflation" returned TWO readings: 2026-03 and 2026-04.

#### `R-43`

A period-less question about one indicator is about a **window** expressed in years: 3 years at monthly grain, 6 at quarterly, 10 at annual; the fetch expands the window to the indicator's own grain. A period-less set fetch uses the quarterly window (6 years) unless a granularity was named.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** design · **Implemented at:** `_WINDOW_YEARS` · **Status:** `proposed`
#### `R-44`

A trend is drawn at the interval that yields at least 3 readings (`TREND_MIN`), and never more than 24 rows are shown (`SERIES_MAX`) — the most recent are kept and the card says how many matched.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** findings 56, 58 · **Implemented at:** `TREND_MIN`, `SERIES_MAX` · **Status:** `proposed`
**Why —**
  - *finding 56* — "Show the trend of Inflation" returned TWO readings: 2026-03 and 2026-04.
  - *finding 58* — "give the chart of monthly inflation" was answered with A SINGLE VALUE:

#### `R-45`

A named single period is answered at that period. A question that names three or more periods on a change / growth / comparison shape is widened: the span is listed, not just its ends.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **Status:** `proposed`
#### `R-154`

**The reader's period outranks every convention of ours, on the first question as on a follow-up.** "The latest snapshot of the national indicators for 2024" and "How was the economy doing in 2024?" are the picture **at 2024** (the executive structure aligned there, members without 2024 at their own latest with their date, the table column headed "Reading" rather than "Latest reading"), not each indicator's own latest. Until 4.5.5 the snapshot flag was set from the words alone and won over the named period with no disclosure; the past tense of the executive question reached no shape at all. Corrected in 4.5.6 (finding 152).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 148, 152 · **Status:** `proposed`
**Why —**
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The
  - *finding 152* — THE READER'S PERIOD OUTRANKS OUR CONVENTION - ON THE FIRST QUESTION TOO.


### C5. Follow-ups — what context is carried, and how the card says so

#### `R-46` — A dimension, not a question

The whole question is a period or a relative period: "2023", "what about 2023?", "and 2024?", "for 2024", "Q4", "the previous year", «ماذا عن 2024؟», «وفي 2023», «العام السابق». Framing words («وفي», «لعام», «بالنسبة», "for", "in", "and") are stripped and what remains must be only a period.

- **What is carried:** The previous question's subject — one indicator, or the whole set (with its executive / snapshot-asked flags) — and the new period.
- **What the card says:** "…, read for 2024" on the carried block; the set lead reads "the period you asked about".

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 139, 148 · **Status:** `proposed`
**Why —**
  - *finding 139* — A YEAR IS A DIMENSION. IT IS NOT AN INDICATOR.
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The

#### `R-47` — Ellipsis — a new subject, the old framing

"And exports?", "what about inflation?", "the same for GDP", «وماذا عن الصادرات».

- **What is carried:** Only the framing (the shape, the periods) — the subject is the reader's own and is resolved from their words. A question that names its own subject can never fall through to a subject carry.
- **What the card says:** finding 135

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** code · **Status:** `proposed`
**Why —**
  - *finding 135* — A QUESTION THAT CARRIES NO SUBJECT OF ITS OWN.

#### `R-48` — A pronoun follow-up

"Why?", "Why is that?", "Why did it increase?", "What caused that?", "What is the reason for it?", "Which one fell the most?", "Is that good?", "How does this compare?", "Compared with when?" — a pronoun and no subject noun. "Why did inflation increase" names its own subject and never borrows one.

- **What is carried:** The subject (or set). The follow-up's **own** shape decides what is composed: "why" is a depth question about the carried subject; "which one fell most" is a superlative over the carried set; "is that good" adds the polarity verdict.
- **What the card says:** finding 135, 144

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** code · **Status:** `proposed`
**Why —**
  - *finding 135* — A QUESTION THAT CARRIES NO SUBJECT OF ITS OWN.
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.

#### `R-49`

When a relative period ("the previous year", "Q4") follows a question that pinned no period, the shift is **deferred to the fetch** and computed from the indicator's own latest period — never claimed before a row for the shifted period actually comes back.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 142, 143 · **Status:** `proposed`
**Why —**
  - *finding 142* — THE PERIOD THE READER WAS LOOKING AT IS NOT ALWAYS ONE
  - *finding 143* — THE ORDINAL QUARTER WAS READ AS ITS YEAR.

#### `R-50`

"For 2024" after a snapshot is the **same picture at 2024**: the executive structure, aligned at the period named — not the movement card, and never "the latest readings" under a disclosure that says 2024.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 148 · **Status:** `proposed`
**Why —**
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The

#### `R-51`

A dimension with no previous question to apply it to is an absence card of its own kind ("a period with nothing to apply it to"), never a failed catalogue search.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 139 · **Status:** `proposed`
**Why —**
  - *finding 139* — A YEAR IS A DIMENSION. IT IS NOT AN INDICATOR.

#### `R-52`

The shape follows the subject that was carried: a follow-up that inherits a set of eight is composed as a set (or executive), never as a value card about one of the eight that contradicts its own first sentence.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 135 · **Status:** `proposed`
**Why —**
  - *finding 135* — A QUESTION THAT CARRIES NO SUBJECT OF ITS OWN.

#### `R-53`

Every carried card records what it carried. Until 4.5.2 this was a preface sentence ("Reading your question as: Gross National Income, for 2024."); at the Council's request (finding 149) the preface is no longer printed. The carry is now visible in three places: the period on every figure is the period asked; a set's lead sentence says "the period you asked about"; and the ledger block (evidence panel) is labelled with the carried subject and "read for 2024". A generated reading of a carried card must still disclose the carry or it is rejected (Part I). **Decision O-3 asks the Council to confirm this is the disclosure it wants.**

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** P-3; findings 135, 149 · **Status:** `proposed`
**Why —**
  - *finding 135* — A QUESTION THAT CARRIES NO SUBJECT OF ITS OWN.
  - *finding 149* — —

#### `R-54`

Context is never carried into the library: a question that says both "articles" and "national indicators" asked for the articles.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 85 · **Status:** `proposed`
**Why —**
  - *finding 85* — NAMING THE TITLE IS THE REQUEST.


## Part D — Resolution: which indicator, or which indicators


### D1. The ladder for one indicator

#### `R-55`

A fragment of a list ("…, revenues and the trade balance") is resolved by rungs 1–2 **only** — never by retrieval, which always returns its nearest match and would put an indicator nobody named on a Council card. A fragment that does not lexically name an approved indicator contributes nothing.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 94 · **Implemented at:** `_SURFACE_MIN`, `ASKAI_SURFACES`, `_LADDER_CONFIDENT`, `ASKAI_RESOLVE_CONFIDENT`, `_LADDER_BUDGET`, `_WIDEN_TIMEOUT`, `N`, `MIN_SCORE`, `MIN_MARGIN`, `TOP_K`, `ASKAI_RETRIEVAL`, `FLOOR`, `RELATIVE`, `TERMS_WEIGHT`, `_ASK_BAND_MAX` · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE

#### `R-56`

"The service says inactive" is a fact and the indicator is never answered; "the service did not say" is not read as inactive. (The same rule as absence, applied to a flag.)

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 28 · **Implemented at:** `_SURFACE_MIN`, `ASKAI_SURFACES`, `_LADDER_CONFIDENT`, `ASKAI_RESOLVE_CONFIDENT`, `_LADDER_BUDGET`, `_WIDEN_TIMEOUT`, `N`, `MIN_SCORE`, `MIN_MARGIN`, `TOP_K`, `ASKAI_RETRIEVAL`, `FLOOR`, `RELATIVE`, `TERMS_WEIGHT`, `_ASK_BAND_MAX` · **Status:** `proposed`
**Why —**
  - *finding 28* — This resolver filtered confidential candidates and nothing else, so an

#### `R-57`

Resolution is cached only for catalogue lookups (10 minutes); a question is never answered from a cached answer.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** design · **Implemented at:** `_RETRIEVAL_TTL` · **Status:** `proposed`
### D3. Sets and groups

#### `R-58` — Group

The question names a group the CMS holds — one of 22 (8 sectors, 14 entities) built from the sectors and entities exports with reviewed surfaces per group ("national indicators", "our economy", "the diversification targets", "health", "banking", "SMEs", "the free zones", "Hormuz"…). The group's members become the set, ordered by English name, capped at 12; the card states how many further members are not listed. A group of one member is a sole member (rung 5).

**Becomes:** `rules/*.yaml` — a reviewed lookup table · **Source:** findings 94, 102, 114 · **Implemented at:** `_SET_MAX`, `_SET_MIN` · **v2 also covers:** finding 67 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE
  - *finding 102* — THE SET ROUTE WAS BUILT, TESTED, AND UNREACHABLE.
  - *finding 114* — the group route found exactly ONE indicator. That is not a

#### `R-59` — List

The question lists indicators joined by "and", commas or «و»; each fragment (≥ 3 characters, leading verbs and question words stripped) resolves lexically (R-55); the distinct indicators, in the order named, become the set.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 94 · **Implemented at:** `_FRAG_MIN` · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE

#### `R-60` — A group that claims a question and then can answer nothing hands it back: the card says the reader asked about a group and is being answered about something else, or that the group's indicators returned nothing.

finding 140

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** code · **Status:** `proposed`
**Why —**
  - *finding 140* — THE GROUP HAD ITS TURN AND PRODUCED NOTHING. SAY SO.

#### `R-61` — Group surfaces are reviewed like indicator surfaces, with the same collision refusal, and are attached to the group index by the build tool, not typed at runtime. Champions (the accountable ministry or authority) are attached to 10 of the 22 groups from the Champions export; a group with no champion says nothing about ownership.

findings 90, 120, 121

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** table · **Status:** `proposed`
**Why —**
  - *finding 90* — WHO OWNS THE INDICATOR.
  - *finding 120* — "WHAT IS THE DIFFERENCE BETWEEN THE EXPLORER DATA AND THE EXECUTIVE LENS"
  - *finding 121* — THE SECOND HALF of the same defect. `related`, `all` and `down` are all IN


### D4. The amount route — when the catalogue publishes only shares

#### `R-62`

When the reader asks for an **amount** (R-33) and the resolved indicator is a share ("… as Share of …"), the pipeline finds every published share of the quantity the phrase names (the words before "as share of", matched across catalogue names) and pairs each with the indicator its name says it is a share **of**. Each pair must pass the same-population guard (the share and its base must be shares/levels of the same population). The set becomes the share-and-base indicators; the card derives the amount, says it is derived and from which readings, and shows the readings under it.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 141 · **Status:** `proposed`
**Why —**
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `R-63`

Where two published routes give amounts more than 2 % apart, the card prints both and says they disagree, rather than silently picking one.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** finding 141; `_AMOUNT_DISAGREE` 0.02 · **Implemented at:** `_AMOUNT_DISAGREE` · **Status:** `proposed`
**Why —**
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `R-64`

Where no route exists, the card says plainly that the amount is not published and shows the share it did find, named as a share.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** finding 141 · **Status:** `proposed`
**Why —**
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.


### D5. Articles

#### `R-65`

A library question searches the shipped article index (title, body, sector and entity tags, both languages) and lists the matching articles as data (title, date, id) with a preview control; no figure from an article is ever placed beside an approved value, and the preview says "Figures inside it are the authors' own and are not approved indicator data."

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 68, 122 · **Status:** `proposed`
**Why —**
  - *finding 68* — A question about ARTICLES is not a question about data.
  - *finding 122* — THE ARTICLE LIST, AS DATA AS WELL AS AS PROSE.

#### `R-66`

"The article" in a follow-up («أريد محتوى المقال») is resolved against the previous **answer** — the list the reader is looking at — and a title named in the question resolves directly. When it cannot be narrowed to one, the candidates are listed.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 75, 85 · **Status:** `proposed`
**Why —**
  - *finding 75* — A request for ONE article's CONTENT, as opposed to a list of what exists.
  - *finding 85* — NAMING THE TITLE IS THE REQUEST.

#### `R-67`

A summary of an article is generated by the model **only** when the reader asks for one ("summarise"), under the article summariser's own gate (every figure and name in the summary must be in the article), and is labelled generated. Off unless `ASKAI_ARTICLE_SUMMARY` and a model URL are set.

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 87 · **Implemented at:** `ASKAI_ARTICLE_SUMMARY`, `ASKAI_ARTICLE_MODEL_URL` · **Status:** `proposed`
**Why —**
  - *finding 87* — THE CARD PROMISED TWO NOTES AND RENDERED ONE. MINE, FROM 3.3.0.

#### `R-68`

A card about an indicator offers "Articles about X" as a follow-up chip when the library holds pieces on it; the chip carries the question, never the content.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 69 · **Status:** `proposed`
**Why —**
  - *finding 69* — THE BRIDGE, AND IT IS A LINK, NOT CONTENT.


### D6. The four reasons for "no answer"

#### `R-69` — `no_rows`

An indicator resolved, the database was asked, it holds no reading for what was asked.

- **What the card says:** "X is published, but the approved data holds no reading for …" — absence, proven.

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-70` — `unresolved`

The reader's words reached no indicator; the database was never asked.

- **What the card says:** "Your question did not name an indicator the approved catalogue holds" + up to three candidates as questions. A set-shaped absence names no indicator at all.

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-71` — `unreachable`

indicator-svc raised or reported itself unavailable (set in exactly two places).

- **What the card says:** "The approved data could not be reached" — an outage is never dressed as a statement about the data.

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
#### `R-72` — `dimension_alone`

A period with no previous question to apply it to (R-51).

- **What the card says:** "A period with nothing to apply it to."

**Becomes:** `messages/` — reader-facing text, in both languages · **Status:** `proposed`
## Part E — Planning: from a shape to a contract


### E2. Modifiers applied to the shape

#### `R-73`

An amount question (R-33, D4) is answered by the derivation, its readings and the analysts' notes; the movement, the tally and the "newer readings" paragraphs are not composed — a mode may show less.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 141; §31 · **Status:** `proposed`
**Why —**
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `R-74`

A snapshot that was asked for (R-31) and is not a product question gets the consolidated structure (`snapshot`, `evidence`). An **aligned** set — the reader asked for one period, or asked which rose and which fell — keeps the set composers: its question is the movement, not the picture.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-75`

A cross-country question puts the peer table first; the period extreme becomes a headline of Qatar's own figure rather than nothing.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 119 · **Status:** `proposed`
**Why —**
  - *finding 119* — "WHICH COUNTRY HAD THE LOWEST INFLATION" WAS ANSWERED WITH A YEAR.

#### `R-76`

Three or more named periods on a change / growth / comparison shape widen the blocks to list the span.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **Status:** `proposed`
#### `R-77`

Depth (R-27) widens a single-indicator shape: `measures` first (a reader cannot weigh a number before knowing what it counts), then the breakdown, then the peer table, then the champion, with the analyst block allowed to say more. Never on a set.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 77, 80, 90 · **Status:** `proposed`
**Why —**
  - *finding 77* — DEPTH IS NOT A DIFFERENT QUESTION. IT IS THE SAME QUESTION, ASKED WIDER.
  - *finding 80* — THE COMPONENTS, WHICH EXISTED THE WHOLE TIME.
  - *finding 90* — WHO OWNS THE INDICATOR.

#### `R-78`

`wants_change` inserts the `change` block immediately after the first block; `wants_peers` inserts `peers` before `evidence`; `wants_verdict` inserts `favourable` after `change` (or after `assessment`, or second). None of these apply to SET, EXECUTIVE, FORECAST or SCENARIO.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 91, 144 · **Status:** `proposed`
**Why —**
  - *finding 91* — A QUESTION ABOUT MOVEMENT WANTS THE MOVEMENT.
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.

#### `R-79`

The plan records the interval the question was phrased in (from its periods, or its granularity when it named no period) so the check stage can say when the data could not honour it.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 56 · **Status:** `proposed`
**Why —**
  - *finding 56* — "Show the trend of Inflation" returned TWO readings: 2026-03 and 2026-04.


## Part F — Fetching and selecting the rows


### F1. One indicator

#### `R-80`

Rows come from indicator-svc `/refs` for the resolved indicator over the periods the question named (expanded to the indicator's grains) or, for a period-less question, the window of R-43. The meta (name, unit, display decimals, polarity, source, definition) comes with the rows.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **Status:** `proposed`
#### `R-81`

**Interval discipline.** A selection never mixes a year with its own quarters. When the reader named an interval and rows exist at it, only those rows are used; when they exist at no such interval, the card says so (gap `granularity`) and uses what exists.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 1, 46, 56 · **Status:** `proposed`
**Why —**
  - *finding 1* — the tooltip read "2022 / value : 686.131074" - the raw
  - *finding 46* — THE QUESTION'S GRANULARITY OUTRANKS THE DATA'S LAST ROW.
  - *finding 56* — "Show the trend of Inflation" returned TWO readings: 2026-03 and 2026-04.

#### `R-82`

A trend with no named grain is drawn at the **coarsest** interval that carries at least 3 readings (seven annual rows are not discarded because two monthly rows are newer). A single reading is the newest of its kind. Two endpoints are the first and last of the selection.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 56 · **Status:** `proposed`
**Why —**
  - *finding 56* — "Show the trend of Inflation" returned TWO readings: 2026-03 and 2026-04.

#### `R-83`

**The other grain.** When the question named no period and no grain, and the indicator publishes at more than one grain (public debt 42.4 % at 2025-Q4 and 40.6 % for 2025), the card names the newest reading at the coarser grain as well, rather than choosing silently. Applies to value, polar, change, comparison and growth shapes.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 96 · **Status:** `proposed`
**Why —**
  - *finding 96* — WHICH GRAIN "RIGHT NOW" MEANS, WHEN THE INDICATOR PUBLISHES AT TWO.

#### `R-84`

**The year-ago row.** Wherever the move is asked (R-28) or depth is asked (R-27), the same period one year earlier is fetched as one extra row (2025-Q4 → 2024-Q4; 2026-04 → 2025-04; 2025 → 2024). If the database holds no row for it, the card says which comparison period is absent; it never compares against some other period.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 91, 144 · **Status:** `proposed`
**Why —**
  - *finding 91* — A QUESTION ABOUT MOVEMENT WANTS THE MOVEMENT.
  - *finding 144* — "IS THAT GOOD?" IS ANSWERED BY THE CATALOGUE, NOT BY US.

#### `R-85`

**The analyst note** (`/commentary`) is fetched for the periods the answer shows, widened so that a quarterly note about 2025 is reachable from a card that cites 2025; a note that covers none of the card's periods is filed in the ledger, not spoken. One covering note per period on the card (the "journey"), at most 8.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 51, 82, 117 · **Implemented at:** `_JOURNEY_MAX` · **Status:** `proposed`
**Why —**
  - *finding 51* — A NOTE THAT COVERS NOTHING ON THIS CARD IS NOT SPOKEN.
  - *finding 82* — THE JOURNEY. ONE NOTE PER PERIOD, NOT ONE NOTE PER CARD.
  - *finding 117* — ONE ANALYSIS ON A CARD, AND IT IS THEIRS WHERE THEY HAVE WRITTEN ONE.

#### `R-86`

**Depth data** (only when R-27): the peer table from `/benchmark` (at most 6 peers; a comparison at a period the card does not cover is flagged as not aligned); the sibling detail rows from `/refs` by detail id at the card's own period (at most 8, one fetch each within 6 s); the CMS definition; the group champion.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** findings 77, 80, 81, 90 · **Implemented at:** `_PEERS_MAX`, `_COMPONENTS_MAX`, `_COMPONENT_MAX_FETCH` · **Status:** `proposed`
**Why —**
  - *finding 77* — DEPTH IS NOT A DIFFERENT QUESTION. IT IS THE SAME QUESTION, ASKED WIDER.
  - *finding 80* — THE COMPONENTS, WHICH EXISTED THE WHOLE TIME.
  - *finding 81* — THE COMPARISON MUST BE AT A PERIOD THIS CARD IS ABOUT.
  - *finding 90* — WHO OWNS THE INDICATOR.

#### `R-87`

**What a breakdown is** is decided from the rows, never from the shape of the CMS table: a *decomposition* when the parts reconcile to the published whole (tolerance 1e-4); *additive peers* when they are additive units with no published whole; *related series* otherwise — and related series are never summed. Balancing items and non-additive units (rates, ranks, shares) are never summed.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 97 · **Implemented at:** `RECONCILE_TOL` · **Status:** `proposed`
**Why —**
  - *finding 97* — A SIBLING IS NOT A COMPONENT.

#### `R-88`

A chart is built over exactly the periods the card cites; any point the card does not cite is dropped and a chart left with fewer than two points is not shown. Tooltip values follow the display policy (never 686.131074).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 55 · **Status:** `proposed`
**Why —**
  - *finding 55* — THE PIPELINE DREW NO CHARTS AT ALL, AND THAT IS MINE.


### F2. A set

#### `R-89`

Every member is fetched concurrently over the union of the named periods and the window, inside one budget (12 s). A member with no rows is recorded as **absent** and named on the card. Fewer than two members with rows is "not a set" — an ordinary empty result, never an outage.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** findings 95, 128, 131 · **Implemented at:** `_SET_FETCH_BUDGET_S`, `_SET_MIN` · **Status:** `proposed`
**Why —**
  - *finding 95* — THE SET, FETCHED CONCURRENTLY AND LINED UP ON ONE PERIOD.
  - *finding 128* — `unavailable` IS OVERLOADED, AND THE OVERLOAD ALMOST SHIPPED A NEW
  - *finding 131* — WE ASKED FOR EVERY ONE OF THEM AND EVERY ONE CAME BACK EMPTY.

#### `R-90`

**The named-period rule.** When the reader named a period: if every member has it, the set is aligned on it. If at least two and at least **half** of them have it, the set answers at that period, and the rest are shown at their own latest reading — those older than the named period as "not published for 2024; the latest available reading is older", those newer as newer readings. If fewer than half have it, the card states who has it and who does not, at the newest period the majority reaches. The lead sentence then reads "**Readings at 2024** — the period you asked about; these 6 have it."

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 104, 148 · **Status:** `proposed`
**Why —**
  - *finding 104* — A NAMED PERIOD MUST NOT BYPASS THE ALIGNMENT.
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The

#### `R-91`

**Alignment with no named period** (a comparison, "which rose and which fell"): the set is lined up on the newest period **every** member shares; a laggard is dropped from the alignment whenever dropping it buys recency, and the dropping stops when it stops buying any, with a floor of a majority (never fewer than 2). Dropped members are listed with their own dates, never removed from the card. On the eight national indicators this gives six at 2025 with GNI (2023) and FDI Stock (2024) listed separately.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 108 · **Status:** `proposed`
**Why —**
  - *finding 108* — the grain the QUESTION was phrased in steers the tie-break.

#### `R-92`

Grains are compared separately (a year and its own quarter are not the same reading); a tie on end-date goes to the **coarser** grain ("2025" over "2025-Q4") unless the reader named a grain ("in Q1 2026"), whose grain outranks the convention.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 1, 108 · **Status:** `proposed`
**Why —**
  - *finding 1* — the tooltip read "2022 / value : 686.131074" - the raw
  - *finding 108* — the grain the QUESTION was phrased in steers the tie-break.

#### `R-93`

**Newer readings.** Members whose own latest reading is newer than the aligned period are read at their own latest **too**, in a separate paragraph, so that a card aligned at 2025 cannot hide that revenues have a 2026-Q1 reading.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 138 · **Status:** `proposed`
**Why —**
  - *finding 138* — THE READINGS THAT REACH FURTHER WERE DISCLOSED AND NEVER READ.

#### `R-94`

**A snapshot** (R-30) — or a set with no shared period at all — reports each member at its own newest reading (ties to the finer grain), sorted by name, and the card says the periods differ.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 129, 130 · **Status:** `proposed`
**Why —**
  - *finding 129* — THE QUESTION THAT WANTS EACH INDICATOR AT ITS OWN LATEST PERIOD.
  - *finding 130* — —

#### `R-95`

Each member's **change** is the move against the same period one year earlier, computed from the rows already fetched for that member — never a second fetch, so the pair can never come from two different requests.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **Status:** `proposed`
#### `R-96`

The analysts' notes for the set are fetched per member at the period the card shows it; up to 3 are spoken, all are in the ledger.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** finding 111 · **Implemented at:** `_SET_NOTES_SHOWN` · **Status:** `proposed`
**Why —**
  - *finding 111* — THE ANALYSIS THE COUNCIL ALREADY WROTE.


## Part G — Composition: what the card says


### G1. The block model and the ledger

#### `R-97`

Composers **append**; none may overwrite another's sentence, so no ordering can lose a sentence. Structured content (a list, a table) starts its own line; once an answer is multi-line it stays multi-line.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** design · **v2 also covers:** finding 48 · **Status:** `proposed`
#### `R-98`

Measured first, generated last, absent never omitted. There is no "unknown" class: a fact the system cannot place is not shown.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** block model · **Status:** `proposed`
#### `R-99`

Every card ends with the evidence block: the citations (indicator, period, value, revision status, source) — the source is a CMS field and is labelled as such, not as a reading.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 36 · **Status:** `proposed`
**Why —**
  - *finding 36* — `derived` against

#### `R-100`

Executive Lens is a filter over classes and display sections; dropping `generated` provably removes only generated content.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 34 (P-8) · **Status:** `proposed`
**Why —**
  - *finding 34* — The reading, on request, and never unasked.


### G2. Numbers, units, periods and Arabic

#### `R-101`

A value is shown with the CMS display decimals and its unit; the money form is `QAR 185.2bn` (the scale prefix comes from the CMS Format field, e.g. "bn0.0", composed by the loader into "bn QAR"); percentages as `2.6%`; ranks as ordinals (`78th`); an `NA` unit is silent. Arabic writes the scale in words: «185.2 مليار ر.ق».

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 60, 147 · **Status:** `proposed`
**Why —**
  - *finding 60* — THE UNIT RIDES EVERY ROW.
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-102`

A **percent-measured** indicator changes in **points** (pp), never in per cent of itself; a **rank** changes in **places** ("up 9 places", «تقدّم 9 مراتب») and lower is better; everything else changes in per cent. A rank whose catalogue polarity says "increase" contradicts itself and the card says so.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 1, 109 · **Status:** `proposed`
**Why —**
  - *finding 1* — the tooltip read "2022 / value : 686.131074" - the raw
  - *finding 109* — "THAT IS" NEEDS SOMETHING TO REFER TO.

#### `R-103`

A move smaller than 2 % of the starting level (floored at 0.05 in the unit) is **flat** — not a direction.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** `FLAT_RATIO` 0.02, `FLAT_FLOOR` 0.05 · **Implemented at:** `FLAT_RATIO`, `FLAT_FLOOR` · **v2 also covers:** finding 136 · **Status:** `proposed`
#### `R-104`

Periods are written as the database writes them (`2025`, `2025-Q4`, `2026-04`) and every figure carries one. Signed changes and periods are isolated for bidirectional text so that Arabic prose never shows "Q4-2025" or "2.0%+".

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-105`

Arabic sentences are composed in parallel, not translated: feminine agreement for «الإشارة» (إيجابية / سلبية / مستقرة / غير مصنّفة), «بحسب تحليل الأمانة،» for the analysts' sentence, «الصورة العامة» for the overall assessment.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 115, 147 · **Status:** `proposed`
**Why —**
  - *finding 115* — THE LINE THAT DECIDES WHICH WAY THE PARAGRAPH READS.
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so


### G4. The set card (aligned or listed)

#### `R-106`

Lead line: "**Readings at 2025** — the latest annual period these 6 share." or "**Latest readings** — each indicator at its own latest period." or, at a named period, "**Readings at 2024** — the period you asked about; these 6 have it." Then one line per member: name · reading · period · change.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 95, 129, 147, 148 · **Status:** `proposed`
**Why —**
  - *finding 95* — THE SET, FETCHED CONCURRENTLY AND LINED UP ON ONE PERIOD.
  - *finding 129* — THE QUESTION THAT WANTS EACH INDICATOR AT ITS OWN LATEST PERIOD.
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The

#### `R-107`

Members that could not reach the period: "Not published for 2024; the latest available reading is older: …". Members that returned nothing: "No reading was returned for X." A trimmed group: "This group holds N further indicators that are not listed here."

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 102, 104, 131 · **Status:** `proposed`
**Why —**
  - *finding 102* — THE SET ROUTE WAS BUILT, TESTED, AND UNREACHABLE.
  - *finding 104* — A NAMED PERIOD MUST NOT BYPASS THE ALIGNMENT.
  - *finding 131* — WE ASKED FOR EVERY ONE OF THEM AND EVERY ONE CAME BACK EMPTY.

#### `R-108`

Movement: "Signal — **Positive**: …; **Negative**: …; **Stable**: …; **Not classified**: …" against the same period a year earlier — direction from arithmetic, the signal word from the catalogue's polarity. When the reader named the period, the "newer readings" paragraph is not spoken (ledger only).

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 94, 148 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE
  - *finding 148* — THE READER'S PERIOD, WHEN MOST OF THE SET HOLDS IT. "The

#### `R-109`

The largest move is taken over percentage changes only; a member that cannot supply one (a rate, a rank, points) is reported as excluded, never ranked anyway.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 94 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE

#### `R-110`

A product the reader proposed (R-35) is computed only from exactly two readings whose denominators are the same population; otherwise it is refused and the refusal says why ("a share of government revenue cannot be applied to non-hydrocarbon GDP").

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 100 · **Status:** `proposed`
**Why —**
  - *finding 100* — THE MULTIPLICATION THE CLIENT MOST WANTS US TO REFUSE.

#### `R-111`

Analysts' notes: "**Trade Balance (Goods & Services), 2025-Q4** — SCEAI notes that …", up to 3; the remainder counted in the ledger only (`set_analyst_more`).

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** finding 111, §19 · **Implemented at:** `_SET_NOTE_MAX` · **Status:** `proposed`
**Why —**
  - *finding 111* — THE ANALYSIS THE COUNCIL ALREADY WROTE.


### G5. The snapshot and executive card — the Council's §17 structure

#### `R-112`

**The lead order** for the concerns (and the positives): a signal whose published analysis states a historical extreme reaching back at least one year ("the lowest since Q3 2017") leads; then the tier; then the size of the move; then the name. An extreme reaching back less than a year ("since February 2026") stays in the ledger. This reproduces the Council's own worked example on the real export.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** §6; finding 147 · **Implemented at:** `_EXTREME_MIN_YEARS` · **v2 also covers:** finding 134 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-113`

The table rows are ordered by tier then size; only the lead concern uses the extreme-first rule.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-114`

The confidence level and the rule that produced the label are in the ledger and the reasoning object, not printed on the card ("Confidence: medium" reads like a score). **Decision O-4.**

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 113 · **Status:** `proposed`
**Why —**
  - *finding 113* — A BROAD QUESTION WANTS AN ASSESSMENT, NOT AN INVENTORY.

#### `R-115`

When no analyst note exists for any concern, the SCEAI sentence is omitted. The Council's §22 wording for that case was not recoverable from the thread and is not implemented. **Decision O-5.**

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** §22 · **Status:** `proposed`
#### `R-116`

None of the banned §18/§19 vocabulary appears on this card (Appendix B); every underlying fact stays in the ledger (`set_snapshot`, `executive` with the assessment JSON, `exec_analyst`, `context`, `set_note`, `set_trimmed`, `set_absent`).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** §18, §19 · **Status:** `proposed`
### G6. Refusal, scenario, absence, library, article cards

#### `R-117`

**Scenario** ("if gas prices rise, will GDP grow?"): the card names what the approved data holds about each indicator the question named (with a citation), states that no approved analysis connects them (the CMS mappings table is empty; 32 indicator-to-indicator links across 1,031 analyses, nearly all part-of-whole), and says what would have to exist for the question to be answerable. No headline figure.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** finding 88 · **Status:** `proposed`
**Why —**
  - *finding 88* — A CONDITIONAL IS NOT A READING, AND ANSWERING IT WITH ONE IS WORSE THAN

#### `R-118`

**Forecast**: refused — no projection series exists in the approved data; the external agent is where projections live.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** design · **Status:** `proposed`
#### `R-119`

**Absence** names the question and the reason (D6), and offers candidates as questions.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 39, 125, 126 · **Status:** `proposed`
**Why —**
  - *finding 39* — The reader typed «لاقتصاد في قطر» - "the economy in Qatar" one letter
  - *finding 125* — WHY THERE IS NO ANSWER. THREE REASONS, AND WE HAVE BEEN GIVING ONE.
  - *finding 126* — THE GATE IS STRUCTURAL, NOT NUMERIC, AND THAT WAS MEASURED.

#### `R-120`

**Library / article** cards carry no headline, no chart, no approved figure; the article's own words are shown in the language held, with a note when the language differs from the question's and when the text is truncated.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 68, 75, 122 · **Status:** `proposed`
**Why —**
  - *finding 68* — A question about ARTICLES is not a question about data.
  - *finding 75* — A request for ONE article's CONTENT, as opposed to a list of what exists.
  - *finding 122* — THE ARTICLE LIST, AS DATA AS WELL AS AS PROSE.


### G8. Analyst notes and attribution

#### `R-121`

Only an **attributed** block may carry a cause, and only in the analysts' own words with the byline ("According to SCEAI, 2026-Q1:", "SCEAI notes that …", «بحسب تحليل الأمانة،»). The computed paragraph (assessment, narrative, themes, takeaway) never states why.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 83 (P-9) · **Status:** `proposed`
**Why —**
  - *finding 83* — THE ASSESSMENT. Built ONCE, from what has already been fetched.

#### `R-122`

A note is spoken only when it covers a period the card shows; the note nearest the card's period is chosen; the detailed section is spoken only on a depth card. Analyst text is cleaned of the export's hyphenation breaks (R-23) and of markup.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 51, 77, 117 · **Status:** `proposed`
**Why —**
  - *finding 51* — A NOTE THAT COVERS NOTHING ON THIS CARD IS NOT SPOKEN.
  - *finding 77* — DEPTH IS NOT A DIFFERENT QUESTION. IT IS THE SAME QUESTION, ASKED WIDER.
  - *finding 117* — ONE ANALYSIS ON A CARD, AND IT IS THEIRS WHERE THEY HAVE WRITTEN ONE.

#### `R-123`

On a snapshot the analysts' sentence is condensed to the first sentence, at most 180 characters, re-cased to read after "SCEAI notes that" (proper nouns and "QAR" keep their capitals).

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** finding 147 · **Implemented at:** `_EXEC_NOTE_MAX` · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-124`

A historical extreme in a note ("the lowest total revenue since Q3 2017") is recognised by pattern (lowest / highest / … since <period>) in both languages, and its reach in years is computed against the card's period.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-125`

The attribution tag is configurable (`ASKAI_TAG_EN` / `ASKAI_TAG_AR`, default "According to SCEAI" / «وفقًا للأمانة»).

**Becomes:** `rules/*.yaml` — a toggle or budget, held as data · **Source:** finding 117 · **Implemented at:** `ASKAI_TAG_EN`, `ASKAI_TAG_AR` · **Status:** `proposed`
**Why —**
  - *finding 117* — ONE ANALYSIS ON A CARD, AND IT IS THEIRS WHERE THEY HAVE WRITTEN ONE.


## Part H — Checks and guards


### H1. The check against the plan

#### `R-126`

A plan that wanted a headline and got none, a headline composed for a shape that has no single answer, a headline whose period is outside the selection, or a chart plotting a period the card does not cite, marks the answer `shape_ok = false`, repairs what it can (drops the headline or the uncited points) and logs a warning. The KPI in Part K counts these.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 37, 55 · **v2 also covers:** finding 59 · **Status:** `proposed`
**Why —**
  - *finding 37* — The live card read
  - *finding 55* — THE PIPELINE DREW NO CHARTS AT ALL, AND THAT IS MINE.

#### `R-127`

A set that was asked for N members and delivered fewer says so and is marked `shape_ok = false` unless every missing member is accounted for as absent, stale or trimmed.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 94, 102, 130 · **v2 also covers:** finding 155 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE
  - *finding 102* — THE SET ROUTE WAS BUILT, TESTED, AND UNREACHABLE.
  - *finding 130* — —


### H2. The standing prohibitions (enforced in code, not in a prompt)

#### `R-128`

No cause, forecast, recommendation or policy word in computed text.

- **Enforced where:** composers (none is able to write one); renderer gate step 1

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 83; §7 · **Status:** `proposed`
**Why —**
  - *finding 83* — THE ASSESSMENT. Built ONCE, from what has already been fetched.

#### `R-129`

No score, no weighting, no index, no percentage "of positivity"; no magnitude adjective ("strong", "robust", "sharp", "moderately"). The number carries the size.

- **Enforced where:** reasoning engine (no such field exists); composers' fixed vocabulary; renderer gate

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 113; §5 · **Status:** `proposed`
**Why —**
  - *finding 113* — A BROAD QUESTION WANTS AN ASSESSMENT, NOT AN INVENTORY.

#### `R-130`

No internal vocabulary on a card (Appendix B).

- **Enforced where:** composers rewritten in 4.5.0; renderer gate step 0; harness32 asserts every card

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** §18, §19 · **Status:** `proposed`
#### `R-131`

One card, one indicator — unless the question asked for a set; and a set card names every member it was asked about.

- **Enforced where:** plan (the set shape exists only when ≥ 2 resolve); check

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 94, 130 · **v2 also covers:** finding 137 · **Status:** `proposed`
**Why —**
  - *finding 94* — A QUESTION CAN BE ABOUT SEVERAL INDICATORS AT ONCE, AND NINE OF THE
  - *finding 130* — —

#### `R-132`

The biggest number on the card is the answer (no headline on a series, a set, a scenario).

- **Enforced where:** shape table; check

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 63 · **v2 also covers:** finding 2 · **Status:** `proposed`
**Why —**
  - *finding 63* — the growth rate outranks every row-derived

#### `R-133`

No value without its name, unit and period; a derived value says it is derived.

- **Enforced where:** composers; ledger classes

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 63, 141 · **Status:** `proposed`
**Why —**
  - *finding 63* — the growth rate outranks every row-derived
  - *finding 141* — "HOW MUCH WAS GENERATED" IS A QUESTION ABOUT AN AMOUNT.

#### `R-134`

Absence is proven by asking (D6); an outage is never dressed as absence and absence never as an outage.

- **Enforced where:** `Ask.absence_reason`, `Plan.unreachable`

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 125, 128 · **Status:** `proposed`
**Why —**
  - *finding 125* — WHY THERE IS NO ANSWER. THREE REASONS, AND WE HAVE BEEN GIVING ONE.
  - *finding 128* — `unavailable` IS OVERLOADED, AND THE OVERLOAD ALMOST SHIPPED A NEW

#### `R-135`

Approved data never under an external badge; external content never as approved.

- **Enforced where:** route gate (R-4)

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 49 · **Status:** `proposed`
**Why —**
  - *finding 49* — the pipeline declined to answer for agent=%r -

#### `R-136`

A mode shows less, never more (R-100).

- **Enforced where:** interface filter

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 34 · **Status:** `proposed`
**Why —**
  - *finding 34* — The reading, on request, and never unasked.

#### `R-137`

A carried context is disclosed (R-53); a substituted period is disclosed (H1); a similarity match is disclosed (D1 rung 3).

- **Enforced where:** composers; renderer gate step 9

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 32 · **Status:** `proposed`
**Why —**
  - *finding 32* — The model may name the SUBJECT. It may not produce anything else.

#### `R-138`

"It does not editorialise; it will summarise when asked": nothing generated is produced unless a reader presses the action.

- **Enforced where:** interface + `/api/read`

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 34 · **Status:** `proposed`
**Why —**
  - *finding 34* — The reading, on request, and never unasked.


#### `R-155`

**A number in prose must match a number on the card after normalisation, not before it.** A figure written with its scale attached — `753.2bn`, `٧٥٣٫٢ مليار` — is the same figure as the card's `753.2` carrying unit `bn`. The guard compares the normalised numeric token and the normalised unit separately; it does not compare the rendered string.

- **Effect:** the guard stops rejecting correct sentences, which is what makes a discard rate readable as a real signal rather than as noise.
- **Enforced where:** the narration guard, number check (AD-28 check 1)

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 156 (postdates the 4.6.0 baseline; written for v2) · **Status:** `proposed`

**Why —**
  - *finding 156* — a decimal glued to its scale is still a decimal. A number guard rejected a correct sentence because `753.2bn` did not match `753.2`.

**`[v2]`** New in this revision. The register's baseline is release 4.6.0 and this finding postdates it.

#### `R-156`

**An attributed sentence belongs to the entity it was written about, and may not be moved.** A passage carrying a byline is bound to the indicator, period and country of the datapoint it was published against. Re-using it on a card for a different entity is prohibited even where the sentence reads as generic, and the guard's named-entity check tests the attribution's entity against the card's, not merely the sentence's wording.

- **Effect:** closes the hole where a sentence about Qatar appeared on a Bahrain card **carrying its byline**, and the guard passed it because every number and name in the sentence was legitimate — just legitimate somewhere else.
- **Enforced where:** the narration guard, named-entity check (AD-28 check 2); provenance envelope (AD-6)

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 157 (postdates the 4.6.0 baseline; written for v2) · **Status:** `proposed`

**Why —**
  - *finding 157* — the Council's sentence, moved onto another country. An attributed sentence about Qatar re-used on a Bahrain card, carrying its byline, and the guard passed it.

**`[v2]`** New in this revision. The register's baseline is release 4.6.0 and this finding postdates it.

#### `R-157`

**`[REJECTED]` When any member of a set publishes a reading newer than the aligned period and the reader named no period, switch the whole set to per-indicator latest.** Tried, implemented, and **withdrawn**.

- **Why it was withdrawn:** it fixed the client's D5 case and **broke twenty-two checks across five harnesses**, because it replaced `R-95`, `R-104` and `R-118` — a deliberate, tested design — for *every* set question rather than for the questions that actually want it.
- **What survived instead:** the switch belongs on the **question**, not on the data — `R-30`'s snapshot phrasing, the executive shape, and a level comparison between named indicators with no period stated. Alignment is kept so the tally and the ranking mean something, and the card names each member that has a newer reading and the period it sits at. Nothing is hidden; a different thing is emphasised.
- **Do not re-propose without reading those twenty-two checks first.** This entry exists so the next person who notices the same client case learns the outcome in a minute rather than re-discovering it over a release.

**Becomes:** nothing — it is not implemented, and must not be · **Source:** finding 133, read at `answer_pipeline.py:2748` · **Status:** `rejected`

**Why —**
  - *finding 133* — the rule that was tried here and taken back out. "The first draft made 'any member publishes further, and the reader named no period' switch the whole set to per-indicator latest. It fixed the client's D5 and broke twenty-two checks across five harnesses."

**`[v2]`** New in this revision, and the reason §4.3 asked for a `rejected` status. **Statement corrected in the same revision:** the first draft of this entry inferred the rule as the inverse of `R-30` and was wrong — the withdrawn rule was triggered by the *data* (a member publishing further), not by the question's shape. Verified against the finding's own text.

#### `R-139`

The package is built at answer time from the same ledger the card was composed from, cached under an opaque `read_id` (up to 400 entries), and rebuilt from the question and history after a restart — so the reading is of **this** card, never of a second run that might resolve a follow-up differently.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 145 · **Implemented at:** `ASKAI_READING_MODEL_URL`, `_READ_CACHE_MAX` · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.

#### `R-140`

Cards with no measured evidence (absence, forecast, scenario, library, article, catalogue, capability) are not renderable.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 145 · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.

#### `R-141`

The prompt (v4) instructs the model to restate only; to use the computed labels exactly; to keep the analysts' sentence in the "SCEAI notes that" form; never to reproduce the table; and never to use the §14a banned words. Prompt text is a file shipped with the release (`renderer_prompt.md`).

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** findings 143, 147 · **Status:** `proposed`
**Why —**
  - *finding 143* — THE ORDINAL QUARTER WAS READ AS ITS YEAR.
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-142`

Length by shape: word budgets (value 140 · change 200 · growth 200 · comparison 220 · polar 160 · series 280 · spread 220 · superlative 200 · sort 220 · set 420 · executive 400 · overview 400), 3,000 characters, and token caps (set 720 · executive 760 · series 520 · overview 760 · default 440); a reply cut off by its cap is rejected.

**Becomes:** `rules/*.yaml` — a published value the engine reads · **Source:** §21 · **Implemented at:** `BUDGET_WORDS`, `MAX_CHARS`, `MAX_TOKENS`, `MAX_TOKENS_DEFAULT` · **Status:** `proposed`
#### `R-143`

Every request, acceptance and rejection (with its reason) is counted and exposed at `/api/read/stats`; the rollout decision for the renderer is taken on those numbers.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 145 · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.

#### `R-144`

The reader is told **why** a reading was withheld, in words that describe the rule rather than the mechanism. The withheld line is "The figures above stand as written."

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** finding 145 · **Status:** `proposed`
**Why —**
  - *finding 145* — THE EVIDENCE PACKAGE IS BUILT HERE, FROM THIS ANSWER, AND KEPT.


## Part J — Modes and the interface


### Modes and the interface

#### `R-145`

**Executive Lens** and **Explore Data** are the same request and the same answer. Executive Lens hides the chart, the "How to read this" definition, the analysts' detailed section and the related-indicator list, and shows the "what changed" sentence only when there is no headline figure. Nothing is hidden that the reader asked for.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 26, 34 · **Status:** `proposed`
**Why —**
  - *finding 26* — ONE question, asked five times, produced THREE different cards:
  - *finding 34* — The reading, on request, and never unasked.

#### `R-146`

The evidence panel ("Where each part came from" / "Data evidence") is collapsed by default in both modes and one click from open; it shows the ledger classes with their descriptions and the citations with revision status and source.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 26 · **Status:** `proposed`
**Why —**
  - *finding 26* — ONE question, asked five times, produced THREE different cards:

#### `R-147`

Suggested follow-ups are questions, never content; "Articles about X" is offered where the library holds pieces on the indicator.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 69 · **Status:** `proposed`
**Why —**
  - *finding 69* — THE BRIDGE, AND IT IS A LINK, NOT CONTENT.

#### `R-148`

Combined view makes two labelled requests — the approved agent and the external agent — and renders two cards under two source headings ("According to SCEAI" / "According to <external label>"), never a merged one.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 49, 84, 89 · **Status:** `proposed`
**Why —**
  - *finding 49* — the pipeline declined to answer for agent=%r -
  - *finding 84* — TWO SOURCES, COMPARED - NEVER MERGED.
  - *finding 89* — ONE CARD, TWO SOURCES, EACH UNDER ITS OWN HEADING.

#### `R-149`

A table is drawn as a table (header, numeric columns right-aligned, every cell in its own text direction) by the current bundle; an older bundle receives lines (R-3).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 147 · **Status:** `proposed`
**Why —**
  - *finding 147* — A TABLE ONLY FOR A SCREEN THAT CAN DRAW ONE. The 4.5.0 bundle says so

#### `R-150`

Two disclaimers are fixed on the page: "Ask AI is an assistive layer. Verify figures against the Economic Monitoring Dashboard as the source of truth." and the POC note that roles and privileges are not enforced.

**Becomes:** `messages/` — reader-facing text, in both languages · **Source:** BRD · **Status:** `proposed`
## Part M — The reviewed data tables (the editable business logic)


### The reviewed data tables (the editable business logic)

#### `R-151`

A table change is published by rebuilding the index (where generated), running the harnesses that assert the table's invariants, and restarting the service. A back-office editor must run the same validations and the same harness subset before a change becomes live; a change that fails them is not published.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Status:** `proposed`
#### `R-152`

No table may contain a value, a period or a new indicator. Tables add spellings, groupings, orderings and repairs to what the catalogue already holds; they never add facts.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** P-2 · **Status:** `proposed`
#### `R-153`

Every table carries provenance (the export files and row counts it was built from, the date, the Council document it implements).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** practice · **Status:** `proposed`

## Part V2 — recovered in the v2 pass

**Nineteen rules, recovered by reading the 36 uncited findings at their own reference sites in
`app/`.** They are collected here rather than threaded into Parts A–M because they were never in
`askai-business-logic-spec v1.0` — the register's parts are that specification's structure, and
inserting into it would misrepresent what the specification said. Each rule names the part it
would belong to, so a future re-baseline can place it.

Every one is `proposed`. Seventeen further findings needed no rule: their statements were already
in the catalogue, and the v2 pass added the citation rather than a duplicate — listed in §4.2.

### V2.C — Reading the question

#### `R-158`

**A period phrase changes *when* a question asks about, never *what*.** Period and span vocabulary is removed before a question is scored for subject salience, and the same list serves the follow-up test and the salience test — one list read twice, never two lists that drift.

- **Effect:** «الاقتصاد في السنوات الخمس الماضية» stops resolving to a labour indicator on its span words while «الاقتصاد في قطر» correctly gives the overview.
- **Would belong to:** Part C — Reading the question.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 38, read at `main.py:5860` · **Status:** `proposed`

**Why —**
  - *finding 38* — the span words counted as salient and the question therefore "had another subject". It does not.

#### `R-159`

**A vocabulary used for matching is structural and exists in both languages, never a list of fixed phrases in one.** Where English matches on a shape — a cue word, a short window, a topic word — Arabic matches on the same shape. A phrase list is permitted only where the phrases are themselves the reviewed data (Part M).

- **Effect:** «وضع الاقتصاد» (the genitive construct) is recognised as readily as «الوضع الاقتصادي»; the Arabic follow-up words — ماذا، خلال، لعام، بالنسبة، أما، كان — exist because their English counterparts do.
- **Why it is one rule and not two:** findings 14 and 30 are the same defect in two features. The English path is exercised constantly in development and the Arabic path only by the client, so a per-feature fix never generalises.
- **Would belong to:** Part C — Reading the question.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 14 and 30, read at `main.py:5795` and `main.py:6817` · **Status:** `proposed`

**Why —**
  - *finding 14* — the English side above is STRUCTURAL and it generalises. The Arabic side was a list of four fixed phrases. A phrase list will always miss the next phrasing.
  - *finding 30* — the feature was half-built in one language and complete in the other, and the half that was missing is the half a bilingual deployment is judged on.

#### `R-160`

**A qualifier the resolved indicator's own name contradicts is a different question, not a near miss.** The subject guard asks whether this is the right *subject*; a second guard asks whether it is the right *measure* of it. Where the two disagree the question is declined and the difference named, never smoothed over.

- **Clause:** the reviewed basis table is a tuple of **sides**, each side a tuple of names for one basis, so that "nominal" and "at current prices" are one basis under two names and «بالأسعار الجارية» can collide with "Real". A flat list of mutually exclusive terms cannot express this and will report no conflict.
- **Effect:** "What is the value of Nominal GDP in Q4-2025?" is no longer answered with Real GDP because "GDP" appears in "Real Gross Domestic Product". The gap between them *is* inflation.
- **Would belong to:** Part C — Reading the question; the table to Part M.

**Becomes:** a test — behaviour a corpus entry or unit test asserts, plus `rules/*.yaml` for the basis table · **Source:** finding 9, read at `main.py:3125` · **Status:** `proposed`

**Why —**
  - *finding 9* — the only thing distinguishing them — the word in the indicator's own name — was the word the matcher discarded as noise.

#### `R-161`

**A polar question is answered yes or no, computed from approved readings, and the pair compared is the one the question's own scope names.** «هل» and the English polar forms mark a question the reader wants decided, not two numbers to subtract themselves. A question scoped to a year compares the end of the preceding year with the end of that year, which may require fetching a period the retrieval was not asked for.

- **Effect:** «هل هناك شركات تكنولوجيا مالية جديدة تم افتتاحها في عام 2025؟» stops returning `14 · 2025-Q4` and "no change" for a quarter when it was asked about a year.
- **Would belong to:** Part C (the intent) and Part G (the composition).

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 15, read at `main.py:4538` · **Status:** `proposed`

**Why —**
  - *finding 15* — every figure correct, and not an answer. The reader asked for yes or no and was handed two numbers and left to subtract.

### V2.D — Resolution

#### `R-162`

**The reviewed vocabulary is consulted on every resolution, not only after the service fails.** A reviewed surface table that runs as a fallback behind a scoring service is inert whenever that service returns anything above its own floor — which is nearly always.

- **Effect:** the 97 reviewed surfaces stop being unreachable. "Are Qatar's exports going up or down?" stops resolving to Helium Export, and "How big is Qatar's non-oil economy?" stops resolving to Real GDP.
- **Would belong to:** Part D — Resolution.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 93, read at `main.py:462` · **Status:** `proposed`

**Why —**
  - *finding 93* — THE REVIEWED VOCABULARY WAS NEVER CONSULTED. The retrieval ladder only runs when the service resolve has ALREADY FAILED.

#### `R-163`

**Resolving to *something* and resolving to something *useful* are different outcomes, and the rescue fires on the outcome.** Where a question is better answered by a group or a set, that route is tried because the single-indicator answer is unhelpful — not only because nothing resolved at all.

- **Effect:** "Is Qatar's economy growing?" reaches the group route that resolves all eight national indicators, instead of taking the ladder's nearest match above its floor and reporting "Nothing in the approved data matches".
- **Would belong to:** Part D — Resolution.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 110, read at `answer_pipeline.py:4452` · **Status:** `proposed`

**Why —**
  - *finding 110* — THE RESCUE FIRES ON THE OUTCOME, NOT ON THE RESOLUTION. Live, something almost always resolves.

#### `R-164`

**When the question is the executive question and nothing resolved from its own words, the reviewed national group answers it.** The group is looked up in the same reviewed table by the name that table publishes; this adds no membership decision and no vocabulary of ours. The fallback is recorded on the answer, in the log and in the trace, so a card that arrived this way is never silent about it.

- **Clause:** a constant, not an environment switch — the module that holds it reads no environment (`P-12`).
- **Clause:** where the group holds fewer members than a set requires, the question is answered as it was before rather than as a short set.
- **Effect:** the Council's specified card stops being replaced by whatever the chain returns whenever the reader's exact phrasing is not among the reviewed surfaces.
- **Would belong to:** Part D — Resolution, or Part E — Planning.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 154, read at `answer_pipeline.py:1737` · **Status:** `proposed`

**Why —**
  - *finding 154* — THE EXECUTIVE QUESTION HAS ONE ANSWER, AND A SPELLING MUST NOT DECIDE IT. That is what happened live.

#### `R-165`

**A category is answered with the groups inside it and their counts — the level above the list, not the list.** Naming the group level makes a new question askable; the category name then no longer names any group and must not fall through to the whole catalogue.

- **Effect:** "List the indicators in Sectors" returns the eight sectors and their counts, not 105 indicator names nobody can scan.
- **Would belong to:** Part D — Resolution, sets and groups.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 71, read at `main.py:6454` · **Status:** `proposed`

**Why —**
  - *finding 71* — naming the level made a new question askable and left it unanswered, which is the same shape as finding 67 itself.

### V2.F — Fetching and selecting

#### `R-166`

**A cross-country question the approved data cannot answer is answered by naming the absence.** A ranking over periods is never presented as though it were a ranking over countries.

- **Effect:** where the peer table exists the question is routed to it; where it does not, the card says so rather than quietly substituting a different comparison.
- **Would belong to:** Part F — Fetching and selecting the rows.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 101, read at `answer_pipeline.py:3685` · **Status:** `proposed`

**Why —**
  - *finding 101* — THE READER ASKED ABOUT COUNTRIES AND WE HAVE ONLY QATAR. Say so. This is the half of the fix that matters most.

### V2.G — Composition

#### `R-167`

**Where the reader asks for the absolute value of a change, the magnitude in the indicator's own unit leads and the percentage follows — never the reverse.**

- **Effect:** "How did Qatar's GDP change between Q1 2025 and Q4 2025? Provide the absolute value." leads with the change, not with the level at the end of the span in 48pt.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 8, read at `main.py:4308` · **Status:** `proposed`

**Why —**
  - *finding 8* — a reader who asked for a change was shown a level in 48pt. "Provide the absolute value" says the quantity wanted is the magnitude in the indicator's own unit.

#### `R-168`

**A change is always shown with the reading it moved to.** A percentage on its own makes the reader ask "from what?" and go looking, which is the opposite of an executive summary.

- **Effect:** "Real GDP +2.0% (2025-Q4)" becomes "Real GDP reached QAR 185.2bn in Q4 2025, up 2% year-on-year". The neighbouring branches already carried the value; the rule makes it uniform.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 132, read at `pipeline_blocks.py:3324` · **Status:** `proposed`

**Why —**
  - *finding 132* — A CHANGE WITH NO READING BEHIND IT.

#### `R-169`

**A series names each period with its reading, in sequence.** Endpoints and a delta are not a series; the reader asked how it moved, and the movement is the sequence.

- **Effect:** closes the gap the client demonstrated by putting the external card beside ours — "in 2024 the inflation rate was 1.23% year-on-year; in 2025 it decreased to 0.54%; by 2026 it increased again to 2.05%" against our two endpoints and a pp delta. Every figure is still read from an approved row; only the shape of the telling changes.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 57, read at `pipeline_blocks.py:512` · **Status:** `proposed`

**Why —**
  - *finding 57* — what Oxford does that we did not.

#### `R-170`

**A list is a list: one reading, or one name, per line.** Items run together with semicolons or commas are a paragraph the reader must parse rather than a list they can scan.

- **Effect:** four readings stop sharing one sentence, and twelve indicator names stop running together with commas. The renderer already splits on newlines, so this needs nothing from the interface.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 50 and 73, read at `pipeline_blocks.py:486` and `main.py:6505` · **Status:** `proposed`

**Why —**
  - *finding 50* — a series is a LIST. Semicolons ran four readings into one sentence and the reader had to parse it.
  - *finding 73* — ONE NAME PER LINE.

#### `R-171`

**A name and its period are written together, in the same breath — never as two lists the reader must pair positionally.** Two adjacent lists of equal length mean a positional pairing to a reader, and any independent ordering of them produces a wrong claim.

- **Effect:** "Government Revenues, Inflation have a more recent approved reading (2026-04, 2026-Q1)" — where the names were sorted alphabetically and the periods as text, so both pairings came out inverted — becomes impossible to express.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 118, read at `answer_pipeline.py:3614` · **Status:** `proposed`

**Why —**
  - *finding 118* — EACH NAME CARRIES ITS OWN PERIOD, IN THE SAME BREATH.

#### `R-172`

**The card opens in the reader's own words, by deterministic string surgery on the question.** The interrogative is stripped and the reader's own phrase becomes the opening; nothing is invented and no model is involved.

- **Clause:** the opener list is matched **longest first**, so "what is happening to" is stripped before "what is" and the bare subject is left standing.
- **Clause:** **never echo a question that proposes its own answer.** Where the reader's words contain a figure they supplied themselves, the echo is suppressed rather than welded to an approved reading — the alternative puts a reader-invented number beside an approved one under one sentence.
- **Effect:** "Inflation — 4 approved readings in %" becomes "The inflation for the last 5 years — 4 approved readings in %"; "The happening to government revenues" stops occurring; and the worst card of the client's acceptance run stops being producible.
- **Would belong to:** Part G — Composition.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** findings 52, 92 and 105, read at `pipeline_blocks.py:110`, `:120` and `:286` · **Status:** `proposed`

**Why —**
  - *finding 52* — the answer opens in the reader's own words. Correct, and it reads like a database replying.
  - *finding 92* — the opener list is matched LONGEST FIRST.
  - *finding 105* — NEVER ECHO A QUESTION THAT PROPOSES ITS OWN ANSWER. It is the worst card in the set.

#### `R-173`

**A rank is an integer ordinal.** The display-decimal policy cap never applies to a rank, whatever the CMS publishes in the format field — including an empty one.

- **Effect:** `11.00 Rank` stops occurring where an indicator carries `Format=''` while another carries `Format='00'`. "11.00th" is not a thing.
- **Would belong to:** Part G — Numbers, units, periods.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 106, read at `main.py:2878` · **Status:** `proposed`

**Why —**
  - *finding 106* — A RANK IS AN ORDINAL. The difference is one CMS field.

### V2.G/L — Language

#### `R-174`

**Arabic counts do not pluralise the way English does, and the card applies the Arabic bands.** One takes the singular; two takes the dual; three to ten take the plural; eleven upwards returns to the singular accusative.

- **Clause:** `1 → مؤشر واحد` · `2 → مؤشران` · `3–10 → 3 مؤشرات` · `11+ → singular accusative`.
- **Effect:** «يضم قطاع السياحة 6 مؤشرًا» and «ضمن 17 قطاعات» — wrong in opposite directions — stop reaching a Council card. Written the English way they read to an Arabic reader as "6 indicator" and "17 sectorses" read to an English one.
- **Would belong to:** Part G — Numbers, units, periods and Arabic.

**Becomes:** a test, plus `rules/*.yaml` for the bands · **Source:** finding 72, read at `main.py:5429` · **Status:** `proposed`

**Why —**
  - *finding 72* — ARABIC COUNTS DO NOT PLURALISE THE WAY ENGLISH DOES. And this card goes to the Council.

#### `R-175`

**A composed sentence agrees in number with the count it carries, and names the unit the reader asked in.** The count is known where the sentence is built, so the sentence agrees with it rather than being written for the common case and left wrong for the other one.

- **Effect:** "2026 do not" — a plural verb on a singular subject — stops reaching a Council card; and the sentence says "of the 5 years requested" rather than "periods", which is our word for it and not the reader's.
- **Would belong to:** Part G — Composition; the Arabic half is `R-105`'s territory.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 47, read at `answer_pipeline.py:3563` · **Status:** `proposed`

**Why —**
  - *finding 47* — a plural verb on a singular subject, on a card that goes to the Council.

#### `R-176`

**Every path that renders CMS text strips its markup itself, and never relies on an upstream having done so.** Markup is formatting from another medium, never content.

- **Effect:** the one path that trusted indicator-svc to have stripped the HTML — the article index — put a base64 `<img>` string on a Council card in front of the client. Nothing that renders CMS text should depend on someone upstream having remembered.
- **Would belong to:** Part G — Composition; companion to `R-23`, which repairs the hyphenation the same export carries.

**Becomes:** a test — behaviour a corpus entry or unit test asserts · **Source:** finding 78, read at `pipeline_blocks.py:1406` · **Status:** `proposed`

**Why —**
  - *finding 78* — markup is formatting from another medium, never content.

