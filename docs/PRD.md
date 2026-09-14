---
title: "Ask AI — Answer Engine (rebuild)"
status: final
created: 2026-09-14
updated: 2026-09-14
owner: Mammohamed
scope: chat-backend answer engine only
---

# Ask AI — Answer Engine

## 1. Why we are rebuilding

Ask AI answers questions about Qatar's national indicator data, in English and Arabic, for an
executive audience. The current build answers them wrongly often enough that it cannot be trusted
in front of the Council.

The failure is not random. Measured against `docs/inputs/` on 2026-09-14, the wrong answers cluster
around **seven properties of the data the current system does not model**:

| # | data fact | what it breaks |
|---|---|---|
| 1 | 90 of 261 populated details publish at **more than one grain**; system-wide "latest" is `2026-04` monthly, `2026-Q1` quarterly, `2025` yearly | the system picks a grain by accident, then answers a monthly question with quarterly data |
| 2 | change/growth is **published** in ten precomputed columns, in two distinct flavours (`%` and `pp`) | the system computes its own growth between arbitrary points, and does not say which basis it used |
| 3 | **Qatar never appears as a country value** — 5,263 of 8,127 rows are national, 2,864 are benchmark rows. Worse, the benchmark *configuration* names Qatar in all 21 declared sets while the data names it in **none** of 8,127 rows | a two-country question returns six countries; look up the declared benchmark list by name and you retrieve every country except the one that matters |
| 4 | the **group layer** (7 classifications, 20 entities, sized 1–23) is present and complete in the published catalogue, but was never queryable | "how many indicators in Diversification Targets" goes unanswered, though the data says exactly 12 |
| 5 | 322 rows are **future-dated**; 42 of them carry an `Actual`, mostly placeholder zeros | a naive "latest" lands in the future, on a zero |
| 6 | **257 of 320 distinct indicator names are ambiguous**; 15 details contain the string "GDP" | "a chart of Qatar's GDP" resolves to a venture-capital indicator |
| 7 | **country identity is not clean** — `Korea` and `South Korea` both exist as published country values | a reader naming one reaches half the data; a benchmark set can list the same country twice |

Each is a rule the system must hold, not a bug to patch. The current implementation encodes its
rules as prose in code comments — they exist and they are good, but they cannot be enumerated,
executed as a set, tested, reviewed by a stakeholder, or traced to evidence that they hold.

**So when the complaint is "it does not have good business logic", the accurate translation is
"I cannot see, agree, or verify the business logic."** That is the problem this PRD solves.

### 1.1 The sharper complaint

The most important line in the tester workbook is not a defect:

> *"SCEAI answers are only related to indicators without any reasoning at all."*
> *"The chatbot is not able to reason with the available data, it simply retrieves it."*

The product commitment is therefore **not** "retrieve the right number". It is **"answer the
question that was asked, from the data that exists, and be explicit about the rest."** A correct
number that answers a different question than the one asked is still a failure.

**Confirmed: no QC assessment against release 4.7.0 exists.** The tester workbook (15–25 Aug 2026,
predating 4.7.0) and its two trailing comments are therefore the *complete* written record of the
complaint driving this rebuild. Nothing further is coming.

That is worth stating plainly rather than treating as a gap, because it has a consequence: **there
is no independent statement of what "good" looks like**, and §7's metrics plus the rule catalogue
(F8) are the only mechanisms that will ever produce one. The first time anyone writes down an
agreed standard for this system will be during this project.

## 2. Who this is for

| reader | what they need | what breaks them today |
|---|---|---|
| **Council member / executive** — opens the tool cold, asks a broad question, has 30 seconds | a short, correct, confident briefing; to know when to trust it | "what can you do?" got no answer; "what's the latest in Qatar's economy?" returned one indicator |
| **Analyst** — checks a figure they already half-know, in either language | the exact value, at the grain they asked for, with provenance | grain chosen by accident; precision inconsistent with the source system |
| **QC tester** — tries to break it, and judges the result | consistent behaviour, and a stated rule to test against | same question, three different cards; no rule to appeal to |
| **Data steward** — owns whether an answer is defensible | traceability from answer back to approved row | no mapping from rule to evidence that it holds |

`[ASSUMPTION]` Bilingual EN/AR is mandatory for every capability, at equal quality. Arabic is not a
translation layer over an English answer — it is a first-class path.

`[ASSUMPTION]` **Stakes are launch-grade** — a government deployment with a Council audience,
external QC, and reputational exposure. This is what sets the rigour of §5's requirements, the
sign-off gate in F8, and the auditability demands in F9 and NFR-9. If this is in fact an internal
tool with a tolerant audience, much of F8 and F9 could be scaled back.

## 3. Scope

**In scope:** the chat backend answer engine — everything between a question arriving and a
structured, grounded answer package leaving.

**Out of scope**, and deliberately so:

| excluded | why |
|---|---|
| the SPA (`static/`) | separate codebase; consumes the answer package |
| indicator-svc / the CMS | separate service; this rebuild consumes its published data, it does not change it |
| the **admin panel**, and every operator surface | **Deferred by decision on 2026-09-14.** What is *not* deferred is data refresh (FR-108–FR-110): the engine holds a local copy of the published data, so a refresh mechanism is mandatory whether or not a UI exists. When a panel returns it needs its own spec for screens, roles and auth. |
| the legacy back-office and Control Center | separate surfaces, and not replaced while the operator surface is deferred |
| **authoring** indicator data, analyses or articles | the engine reads published content; it never writes it |
| **Oxford Economics content *correctness*** | third-party figures are not ours to validate. The **agent itself is in scope** — routing to it, labelling it, plausibility-flagging it and keeping it separate are all engine behaviour (F10). What it says is not. |
| indicator-to-indicator relationships and scenario answers | `P10_Published_Mappings` is an **empty file**. No engine creates data nobody published. |

## 4. The product commitment

Four sentences, and every requirement below serves one of them.

1. **The engine answers the question that was asked** — at the grain, period, country scope and
   measure the question specified, or it says which of those it could not determine.
2. **Every figure is traceable to an approved published row.** No figure is computed where one is
   published; no figure is generated by a language model, ever.
3. **The SCEAI answer is closed-world.** Everything it states comes from the approved knowledge
   base and nothing else — not the model's training data, not the open web, not inference beyond
   what the published data supports. Where the knowledge base is silent, the answer is silent and
   says so.
4. **The rules governing the answer are readable, agreed and continuously proven** — not buried in
   code.

### 4.1 The asymmetry that defines this product

The founding complaint — *"Oxford answers provide reasoning, SCEAI answers are totally
unintelligent"* — compares two things that are not permitted to be the same.

Oxford Economics is a generative third party drawing on world knowledge. It can always produce a
fluent explanation, because it is never constrained to approved Qatari figures. **That freedom is
also its failure mode**: F-002 recorded Oxford forecasting GDP growth of **-28.76%**, a number the
tester immediately flagged as impossible.

SCEAI has the opposite properties. It is closed-world by mandate (commitment 3), so it cannot
match Oxford's fluency, and it should not try. **Closing the perceived intelligence gap by
loosening grounding would destroy the only thing SCEAI has that Oxford does not: an answer the
Council can defend.**

The gap closes the other way — by being *better at the question*. Re-read what the tester actually
asked for in F-029: not insight, not narrative, but **three lines of correctly-bound figures**,
each labelled with its basis and period. The engine reads as unintelligent today because it answers
a different question than the one asked, at a grain nobody chose, without saying what it did. Every
one of those is fixable inside the closed world.

This asymmetry must be visible to the reader, not just true in the code — which is what F10
requires.

## 5. Capabilities and requirements

Requirement IDs are globally numbered and stable. Grouping is for the reader. Suffixed IDs
(`FR-11a`, `FR-37b`) were added after the surrounding requirement and keep their neighbour's
numbering rather than renumbering the document.

**This PRD deliberately contains no user journeys.** The readers are single-role, the product is one
question-and-answer interaction, and journey narratives would be overhead. Reader context is carried
inline in §2 where it changes a requirement.

### 5.0 Glossary

These are domain nouns with precise meanings. They are used identically throughout, and downstream
documents should adopt them rather than paraphrase.

| term | meaning |
|---|---|
| **indicator** | A named thing the catalogue publishes — 189 of them. What a reader usually names. |
| **detail** | An indicator's *measurable variant* — 289 of them, median 1 per indicator, up to 10. **A detail, not an indicator, is what carries the unit, format, polarity, source, target and data.** Wherever this PRD says "detail" as a domain noun it means this. *(Where it means "more information", the surrounding sentence makes that plain — e.g. "Explore Data adds depth".)* |
| **datapoint** | One published value: a detail at one grain, one period, one country scope. 8,127 of them. |
| **grain** | The publication frequency of a datapoint — `monthly`, `quarterly`, or `yearly`. A detail may publish at more than one; 90 do. |
| **period** | A point or range in time, expressed at a grain: `2026-04`, `2026-Q1`, `2025`. |
| **measure** | Which quantity is wanted — actual, target, baseline, or a published change column. |
| **basis** | Which comparison a change is computed against — YoY, QoQ, MoM — and in which unit, `%` or `pp`. |
| **country scope** | Which countries an answer covers. **National scope (Qatar) is the absence of a country value, not a country named "Qatar"** (FR-10, FR-11b). |
| **bound query** | The fully determined tuple — detail, grain, period, country scope, measure — that an answer is computed from. Nothing is fetched until it is bound or explicitly marked unbound. The central artifact of the engine. |
| **operation** | What is being asked for over a bound scope: value, series, change, comparison, extremum, rank, spread, list, count, definition, explanation. |
| **classification** | The top grouping level — 7 of them: Sectors (105 indicators), Special Entities (29), Special Projects (14), Diversification Targets (12), Enablers (11), Drivers (10), National Indicators (8). |
| **entity** | The named group beneath a classification — 20 of them, sized 1–23. Two classifications have none. |
| **group** | A classification **or** an entity, where the distinction does not matter. Where it does, FR-30 applies. |
| **the knowledge base** | Exactly the sources listed in FR-77. Nothing else. |
| **live** (of an article) | Published, active, not deleted, not draft — 67 of the 84 exported. |
| **published / approved** | Present in the published layer of the CMS export. Distinct from merely *existing* in the CMS: 342 indicators exist but are not published (FR-38, FR-38a). |
| **agent** | One of the three provenance contracts a reader selects: SCEAI Indicators, Oxford Economics, Combined (F10). |
| **lens** | Executive Lens or Explore Data — two renderings of **one** bound answer (FR-59). |

### F1 — Understanding and binding the question

The engine must convert a natural-language question into a **fully bound query**: which measure,
at what grain, over what periods, for what country scope. Nothing is fetched until all four are
bound or explicitly marked unbound. This is the root fix for facts 1, 3, 5 and 6.

| ID | requirement |
|---|---|
| **FR-1** | Resolve the reader's words to a specific indicator **detail** — not an indicator name, and not a substring match. Resolution must handle paraphrase ("how big is the economy" → Real GDP), Arabic morphology, and misspelling. |
| **FR-2** | Where resolution is ambiguous, the engine returns a **disambiguation response** naming the candidates, rather than silently choosing. Given 257 ambiguous names, this is a primary path, not an error path. **The threshold at which a resolution counts as ambiguous is itself a rule in the catalogue (F8)** — reviewable and tunable, not implicit in code, because FR-93 pushes the other way and the balance between them is a product decision. |
| **FR-3** | Never resolve on substring containment alone. *"A chart of Qatar's GDP"* has 15 candidate details; picking one by string overlap is prohibited. |
| **FR-4** | Determine grain from the question first (`monthly`, `quarterly`, `yearly`). Where the question names a grain, that grain wins over every other signal, including the data's most recent row. |
| **FR-5** | Where the question names no grain, use the detail's **declared default**, not the grain of its latest row. A period phrase implying a grain ("over the last 5 years" → yearly) counts as naming one. |
| **FR-6** | Where the question's grain is not published for that detail, say so explicitly. Do not silently substitute an adjacent grain. |
| **FR-7** | Resolve period expressions in both languages: absolute (`Q4-2025`, `2026-04`), relative ("last 5 years", "lately", "right now"), ranges, and open ranges. |
| **FR-8** | **"Latest" means the most recent *actual* value at or before today.** Future-dated rows and placeholder values are never eligible. 322 rows are future-dated and 42 carry an `Actual`. |
| **FR-9** | Bind country scope explicitly: countries **named in the question** filter the benchmark set; they never expand it. |
| **FR-10** | Where no country is named, the scope is Qatar/national only. Qatar is represented by the **absence** of a country value, not by a country named "Qatar" — in the CMS this is the explicit value `National / Overall`, which publication converts to empty. An ingest that "fills in" those blanks would merge the national series into the benchmark set and reproduce F-001 at the data layer. |
| **FR-11** | Distinguish *"this country is not a declared benchmark"* from *"it is declared but has no rows"*. Both occur; they are different answers. |
| **FR-11a** | Country identity resolves through a **reviewable alias map held as data**, not a hard-coded list. `Korea` and `South Korea` both exist as published country values and are almost certainly one country; a reader must reach both, and a benchmark set must not show the country twice. This duplicate will not be the last. |
| **FR-11b** | **National scope is a distinct query shape, not a country filter value**, and this is bound once rather than at each call site. The benchmark configuration names Qatar in all 21 declared sets, but the data table names it in none of its 8,127 rows — so any implementation that reads the declared list and looks up each country by name retrieves every benchmark and silently loses Qatar. A cross-country answer is always the union of the national selection and the benchmark selection. |
| **FR-12** | Decompose a multi-part question into independently answerable parts, each bound and answered through the identical path. No part may take a shortcut. |
| **FR-13** | Bound the decomposition, and **name what was dropped**. A part that could not be bound is reported, never silently discarded. |
| **FR-14** | Record which mechanism bound each element of the query (rule, semantic match, model, reader-supplied), on every answer, for audit. |

### F2 — Answering

The engine supports a closed set of **operations** over a bound scope. An operation that the bound
query does not support is refused (F3), never approximated.

| ID | requirement |
|---|---|
| **FR-15** | **Value** — a single figure for a bound (detail, grain, period, country). |
| **FR-16** | **Series** — an ordered run of values across a period range at one grain. A series has no single headline figure; it must not be collapsed into one. |
| **FR-17** | A series is contiguous at its grain, or the gaps are stated. Silently skipping periods is prohibited. |
| **FR-18** | **Change** — the movement between two bound periods, or across a range. |
| **FR-19** | **Use the published change column** matching (grain × basis) where one exists. Compute a change only where none is published, and mark it as computed when you do. |
| **FR-20** | **Always name the basis and the periods**: "YoY", "QoQ", "MoM", and which two periods. An unlabelled growth figure is a defect. |
| **FR-21** | Never conflate **percent** with **percentage points**. On an indicator already measured in `%`, a change is in `pp`. |
| **FR-22** | **Comparison across countries** — values for a bound country set at a **common period**, stated. |
| **FR-23** | **Comparison across periods** — the same detail at two named periods. "Compare X in 2024-05 and 2026-04" is a period comparison, not a country comparison. The comparison dimension comes from the entities in the question. |
| **FR-24** | **Comparison across indicators** — several details lined up. Where their latest periods differ, show each period alongside its figure rather than forcing a false alignment. |
| **FR-25** | **Superlative / extremum** — highest, lowest, best, worst, within a bound scope, returning both the value and the period or country that carries it. |
| **FR-26** | **Ranking and ordering** — ordered lists within a bound scope. Ranks are ordinals, formatted as ordinals. |
| **FR-27** | **Spread** — difference between extrema within a bound scope. |
| **FR-28** | **Catalogue** — answer questions *about* the data: how many indicators in a group, what are they called, what does this indicator mean, what periods exist. |
| **FR-29** | Expose the **group layer**: 7 classifications and 20 entities. "How many indicators in Diversification Targets" must return 12, with names. |
| **FR-29a** | Grouping is read from the **published catalogue's own classification and entity fields**, which are complete for all 189 indicators — every indicator has exactly one classification *and* exactly one entity. Entity *names* require resolving across two sources (16 sectors and 104 named entities); an ownership question resolves one step further, to the champion that owns the group. **Two classifications — Diversification Targets and National Indicators — map to a single container entity named after the classification itself** (*"Economic Diversification Targets"*, *"National Economic Indicators"*). Answer those at classification level, because the entity adds no information — not because the entity is missing. |
| **FR-30** | Distinguish a **group** from a **classification**. "List the indicators in Sectors" names a classification (105 indicators); a sector names one entity. |
| **FR-31** | **Overview / executive summary** — a broad question ("what's the latest in Qatar's economy?") returns a *published, curated set* of indicators at their own latest periods with a short read, not one indicator. The set is **not chosen by the engine**: the catalogue's `NationalIndicators` classification holds exactly 8, all active — FDI Stock, Real GDP, Total Exports, Gross National Income, Inflation, Government Revenues, Trade Balance, and Public Debt as % of GDP. That set is reviewable and changeable by the people who own the data, which is what makes the answer defensible. F-007 asked for *"GDP, inflation, trade balance, etc."*; the published set matches. |
| **FR-31a** | Each indicator in an overview is shown **at its own latest period, with that period stated** — they will differ (FR-24). Never force a common period on an overview, and never present one indicator's period as though it covered the set. |
| **FR-32** | **Capability** — "what can you do?" returns a grounded summary of what the engine can answer, given the data it holds. |
| **FR-33** | **Definition** — what an indicator means, from its published definition. |
| **FR-34** | **Explanation ("why")** — answered **only** from published analyst text, always attributed. Where none exists for the bound scope, the engine says so. It never generates a cause. |
| **FR-35** | Explanation retrieval is filtered by the bound scope (indicator, grain, period, country) **before** relevance ranking. A passage outside the bound scope is not a candidate. |
| **FR-36** | **Articles** — support listing them, retrieving one, summarising against the article body, and answering from article content. A question about articles is a distinct answer type from a data answer, but an equally legitimate one. Elaborated in F10 (FR-95–FR-103). |
| **FR-37** | **Forecast and target** — where target or baseline values are published (98 and 135 of 289 details), answer from them, labelled as target/baseline, never as actual. |
| **FR-37a** | **Components** — answer what an indicator is made up of. 24 indicators declare sub-indicator membership (113 rows) and details run up to 10 per indicator. Recovered from findings 80, 97 and 99, which carry 27 references between them in the old system. |
| **FR-37b** | Components come from the **detail** level, not from a sibling list. **A sibling is not a component** — two indicators under the same group are not parts of each other, and presenting them as such is a false claim about the data. |
| **FR-37c** | Where components are shares, the **residual is named honestly**. The unaccounted remainder of a share is not "other" unless the data says so, and is never silently dropped to make the parts sum to the whole. |
| **FR-37d** | **Chartability is part of the answer.** Chart configuration is published per indicator — type, default view, the named alternate views, and whether target, baseline, trajectory, legend and source are shown. The engine states whether an answer can be charted and under which view; it never offers a chart the configuration does not support. F-035 is the failure of this being unstated. |

#### How far each capability actually reaches

The requirements above read as general. They are not — the published data supports each to a very
different extent, and this is a property of the data, not of the engine:

| capability | reaches | of |
|---|---|---|
| value, series, change (FR-15–FR-21) | 161 indicators / 261 details | 189 / 289 |
| **explanation, "why" (FR-34)** | **652 datapoints — 8.0%** | 8,127 |
| **cross-country comparison (FR-22)** | **21 details — 7.3%** | 289 |
| ranking (FR-26) | 12 indicators | 189 |
| targets (FR-37) | 98 details | 289 |
| baselines (FR-37) | 135 details | 289 |
| definitions (FR-33) | ~143 distinct; many are literally `-` | 289 |
| components (FR-37a) | 24 indicators declare sub-indicators | 189 |
| articles (FR-95) | 67 live | 84 exported |

**This table sets the refusal budget.** If cross-country comparison is possible for 7.3% of
details, then refusing a comparison is the *normal and correct* outcome, not a failure — and §7's
refusal counter-metric must be read against this baseline or it will look like the engine is
declining to work. A rising refusal rate matters; a high one may simply be honest.

### F3 — Honesty and refusal

Refusals are a feature with an executive audience. The engine's credibility depends more on what
it declines than on what it answers.

| ID | requirement |
|---|---|
| **FR-38** | Distinguish and phrase differently: **no such indicator**, **it exists in the CMS but is not approved for publication** (342 of 531 — see FR-38a), **indicator exists and is published but has no data** (28 of 189), **no data for this period/grain/country**, **the question is unsupported**, and **the system could not reach the data**. These are six different statements. |
| **FR-38a** | The engine may use the unpublished CMS catalogue **solely to improve a refusal** — telling a reader their question was sensible and the gap is editorial, not a failure of understanding. It must never surface a value, period, definition or any other content from an unpublished row, and must not imply the data can be obtained. |
| **FR-39** | Never substitute a different indicator for the one asked about. Where "Nominal GDP" is asked and only "Real GDP" exists, say so — do not answer with Real GDP. |
| **FR-40** | Never invent a figure for a country, period or indicator that has no approved row. |
| **FR-41** | Where a question **asserts a figure that the data contradicts**, correct the premise before answering. "Why did inflation fall to 0.2%?" when it did not must challenge the 0.2%. |
| **FR-42** | Where a question cannot be bound, ask a clarifying question naming what is missing, rather than guessing or refusing flatly. Governed by FR-91–FR-94. |
| **FR-43** | An answer is never partially silent: any part of a multi-part question that was not answered is named. |

### F4 — Evidence and provenance

| ID | requirement |
|---|---|
| **FR-44** | Every figure in an answer carries its source: the detail, grain, period, country, and the publishing source (41 distinct sources across the catalogue). |
| **FR-45** | Classify every element of an answer by how it was obtained — **measured** (a published row), **derived** (computed here, from stated inputs), **attributed** (published written content), or **absent**. The class governs what the element may contain. |
| **FR-46** | Attributed content **always** carries its attribution and its period, and neither is stripped for brevity. **Attribution is to the publishing body, not to a person** — the published data source for analyst text (41 distinct sources), the title and date for an article. **Confirmed: no authorship metadata exists beyond the supplied export.** `P04` has no author column of any kind and `Articles.AuthorId` resolves to nothing, so person-level bylines are not achievable and are not promised. The engine attributes what it can and never invents a name. |
| **FR-47** | Apply the indicator's published **unit and format** to every figure shown. 28 distinct units and 20 distinct format specifications exist. |
| **FR-48** | Headline figures round per the display rule; evidence retains full published precision. The divergence is intentional and must be consistent. |
| **FR-49** | Never surface internal CMS state to a reader. `PublishingStatusName` is `Amended` on **100%** of published indicators and carries no information. |
| **FR-50** | Respect the confidentiality flag. `Confidential` indicators are excluded from every answer, including counts, lists and group totals. |
| **FR-51** | Where an indicator is flagged inactive (65 of 189), handle it by a designed, stated behaviour — not an interstitial prompt that blocks the answer. `[NOTE FOR PM]` **The behaviour itself is not yet decided.** The options are: answer with the inactivity noted; answer and carry the publisher's own overlay text (17 indicators have bilingual overlay wording already written); or decline. This affects a third of the catalogue and should be decided with QC before build. F-003's interstitial prompt is what happens when it is not. |
| **FR-52** | Where third-party content is shown, it is a **separate, labelled element**, never merged with approved figures, and never presented as approved. Elaborated in F10. |

### F5 — The answer as a piece of writing

This is where the "no reasoning" complaint is actually answered.

| ID | requirement |
|---|---|
| **FR-53** | The answer opens by addressing the question in the reader's own terms, before any figure. |
| **FR-54** | Prose may make an answer **read better**; it may never make it **say more**. Any generated sentence that introduces a figure, a comparison, or a claim not present in the structured answer is discarded, and the structured answer stands. |
| **FR-55** | No figure is ever produced, formatted or restated by a language model. |
| **FR-56** | The answer states what it did: which grain, which periods, which countries, which basis. The reader should never have to guess what was compared with what. |
| **FR-57** | Where an answer is narrower than the question (a subset of countries, a shorter range, one grain of several), say so in the answer. |
| **FR-58** | Answers are proportionate, and this is **testable on the answer's structure, not judged on its prose**: the element that directly answers the question is first. A yes/no question leads with the yes or no; a single-value question leads with the value; a "which" question leads with the name. Supporting detail follows, and is subject to the lens rules. F-021 was a *technically correct* answer the tester rejected as *"I did not ask for all of this"* — this is the requirement that prevents it. |
| **FR-59** | Support the two lenses — **Executive Lens** (short briefing) and **Explore Data** (full detail) — from **one** underlying bound answer, so the two can never disagree about a figure, a period or a scope. |
| **FR-59a** | Flipping the lens **re-renders**; it never re-answers. The same question must not produce a different bound query, a different grain, or a different figure because a toggle moved. |
| **FR-59b** | Executive Lens carries the answer, its basis and its provenance in short form — not a truncation that drops the scope statement of FR-56. Brevity may remove detail; it may not remove what makes the figure defensible. |
| **FR-59c** | Explore Data adds depth over the same bound answer: the full series, the chart, attributed analysis, comparison detail and evidence rows at published precision. |
| **FR-59d** | A capability available in one lens is available in both. A refusal, a disambiguation or a premise correction appears in both — an executive must not be shielded from the reason an answer is thin. |

### F6 — Language

| ID | requirement |
|---|---|
| **FR-60** | Every capability works identically in English and Arabic. Parity is asserted, not assumed. |
| **FR-61** | Answer in the language of the question. |
| **FR-62** | Arabic output uses Arabic indicator names, country names, period forms, number formatting and pluralisation rules — Arabic counts do not pluralise as English does. |
| **FR-63** | All reader-facing text comes from a single bilingual catalogue keyed by id. No language string is written at the point of use. |
| **FR-63a** | The catalogue is a **reviewable artifact**, agreed with the same people who agree the rules (FR-72). Labels are cheap to fix and easy to leave rotting: F-028 (*"Analyst Summary" should be "Summary Analysis"*) and F-034 (*"should be listed professionally"*) are 2 of 35 recorded findings, and neither is a code defect. |
| **FR-64** | Published content is stored as HTML and, in places, base64-encoded. Normalise it before it reaches a reader — including hyphenation artefacts carried in from PDFs. |

### F7 — Conversation

| ID | requirement |
|---|---|
| **FR-65** | Carry context across turns: a follow-up inherits the subject, grain, period and country scope of the previous answer unless it overrides one. |
| **FR-66** | A follow-up that changes only one dimension ("what about 2022?", "and monthly?") changes only that dimension. |
| **FR-67** | State the inherited subject when answering a follow-up, so an inheritance error is visible rather than silent. |
| **FR-68** | Where context has been lost or is ambiguous, ask rather than answer about a different indicator. |

### F8 — Rules as a reviewable artifact

This group is the direct answer to the founding complaint and is **not optional**.

| ID | requirement |
|---|---|
| **FR-69** | The rules governing answers — grain selection, country scope, latest-value definition, refusal wording, rounding and units — exist as **data**, readable without reading code. |
| **FR-70** | The rule set is **enumerable**: it is possible to produce the complete list of rules the engine implements. |
| **FR-71** | Every rule is traceable to evidence that it holds, and that evidence runs continuously rather than on request. |
| **FR-72** | Each rule records **who approved it and when**. The identity of the approver is an organisational decision and is deliberately not fixed here; the *mechanism* is not optional. A rule nobody agreed is documentation, not a rule. |
| **FR-72a** | `[NOTE FOR PM]` **This is the requirement that answers the founding complaint, and it is the one currently without an owner.** The stated problem is *"I cannot see, agree, or verify the business logic"* — F8 delivers *see* (FR-69, FR-70) and *verify* (FR-71) through engineering alone, but **agree** requires a person with the standing to agree. Until someone holds that, the rebuild can satisfy every other requirement in this document and still meet the original objection. Naming them costs nothing now and cannot be retrofitted cheaply. |
| **FR-73** | Changing a rule is a reviewable change with an audit trail, not a code edit. |

### F9 — Observability

| ID | requirement |
|---|---|
| **FR-74** | Every answer is recorded with its bound query, the mechanism that bound each element, the rows used, the rules that fired, and the version of any prompt involved — sufficient to reconstruct why the answer said what it said, months later. |
| **FR-75** | Degradations are **typed and counted**, never silent. A rule that stops firing must be distinguishable from one that was never reached. |
| **FR-76** | Expose answer quality operationally: refusal rate by cause, disambiguation rate, unresolved-question rate, latency distribution. |

### F10 — Agents, sources and the closed world

The reader selects one of three agents: **SCEAI Indicators**, **Oxford Economics**, or
**Combined**. They are not three skins on one answer — they are three different provenance
contracts, and the engine's credibility depends on never blurring them.

#### The closed-world rule

| ID | requirement |
|---|---|
| **FR-77** | **Every SCEAI statement originates in the approved knowledge base.** The knowledge base is exactly: (a) published indicators, details and datapoints; (b) published analyst text attached to a datapoint; (c) **live published articles**; (d) the reference, group, country and champion/entity tables. Nothing else is a permitted source. |
| **FR-77a** | The knowledge base honours publication state. Articles enter it only when published, active, not deleted and not draft — **67 of the 84 exported rows qualify**. The same principle applies to every source: exported ≠ publishable. |
| **FR-78** | The SCEAI path must not use a language model's own knowledge as a source of fact — no figure, no date, no country fact, no definition, no causal claim. The model's only roles are wording, disambiguation among supplied candidates, and structural classification. |
| **FR-79** | The SCEAI path must not reach the open web or any external data service at answer time. |
| **FR-80** | Where the knowledge base does not contain what the question needs, SCEAI says so with a specific cause (FR-38). It does not fall back to general knowledge, and it does not hand the question to Oxford silently. |
| **FR-81** | Closed-world compliance is **enforced structurally, not by prompt instruction**. A statement that cannot be tied to a knowledge-base source does not reach the reader. |

#### Agent routing and identity

| ID | requirement |
|---|---|
| **FR-82** | The reader's agent selection is honoured exactly. The engine never silently answers from a different agent than the one selected. |
| **FR-83** | Every answer declares which agent produced it, visibly, in both languages and in both lenses. |
| **FR-84** | Oxford content is **always** marked as external and unverified against approved data. The label is a property of the content, not a footnote that brevity may drop. |
| **FR-85** | **Combined returns two distinct answers, never one blended one.** SCEAI first, then Oxford, each under its own heading with its own provenance. No figure, period, unit or claim crosses between them. |
| **FR-86** | The engine never reconciles, averages, corrects or arbitrates between SCEAI and Oxford figures. Where they disagree, both are shown and the disagreement is visible. |
| **FR-87** | In Combined, an SCEAI refusal is still shown. An Oxford answer does not paper over the fact that approved data could not answer the question — that substitution is precisely what makes a refusal untrustworthy. |
| **FR-88** | **An implausible external figure must not reach the reader unflagged.** F-002 recorded a −28.76% GDP growth forecast that the tester rejected on sight. The Oxford interface will not be investigated before design, so **the PRD takes the weaker guarantee as the baseline**: a standing, prominent caveat on every external card stating that its figures are not verified against approved data. If the interface turns out to expose structured figures, a per-figure range check against the approved series is an upgrade to add then — but nothing downstream may assume it exists. Deliberately under-promising: a caveat that survives any interface beats a check that may be unimplementable. |
| **FR-88a** | Whichever mechanism applies, the limits of the check are stated to the reader. A caveat that implies figures were verified when they were not is worse than no caveat. |
| **FR-89** | Oxford unavailability or timeout degrades to the SCEAI answer with the gap stated. It never blocks the SCEAI answer, and never produces an empty card. `[ASSUMPTION]` Combined's current latency of roughly twice single-agent is acceptable; see NFR-3. |
| **FR-90** | Record the agent, the external call and its outcome on every answer (FR-74), so an external figure shown to the Council can be traced later. |

#### Clarifying questions — confirmed in scope

| ID | requirement |
|---|---|
| **FR-91** | The engine may ask a clarifying question where a question cannot be bound, rather than guessing. Confirmed in scope. |
| **FR-92** | A clarifying question is **specific and closed**: it names the candidates or the missing dimension. "Which of these three indicators?" or "for which period?" — never "please rephrase". |
| **FR-93** | Ask at most one clarifying question per turn, and prefer answering with a stated assumption over asking, where one candidate is clearly dominant. The clarification rate is a tracked counter-metric (§7) precisely because this capability degrades the product if overused. |
| **FR-94** | A clarifying question preserves the bound elements already determined, so the reader's reply completes the query rather than restarting it. |

#### Articles as a first-class knowledge-base source

Articles are a **full member of the knowledge base**, not a supplementary one. The engine may
answer a question entirely from an article, cite one, summarise one, list them, and use them to
address questions the indicator data cannot reach — context, policy, interpretation, the "so what".

This matters for the founding complaint. With 92% of datapoints carrying no analyst text, the 67
live articles are a substantial part of the engine's capacity to say anything beyond a number. They
are, for many questions, where the reasoning actually lives.

They do carry one property the rest of the knowledge base does not, and the requirements below
exist to preserve it rather than to limit them: an article is a **dated, authored piece of
writing**, whereas a datapoint is a measurement. Both are approved; they are true in different ways,
and a reader must be able to tell which they are being given.

| ID | requirement |
|---|---|
| **FR-95** | Articles are a **first-class answer source**. A question that an article answers and the indicator data does not is a question the engine answers — from the article, attributed. It is not a refusal. |
| **FR-96** | Articles carry their own **provenance class**, distinct from measured data and from datapoint analysis. The class travels with the content into the answer; it is not a label applied at render time. |
| **FR-97** | Article-sourced content is always attributed — **title and date at minimum**, in both languages and both lenses. **Author attribution is currently unobtainable**: `Articles.AuthorId` holds 32 distinct values and no authors table exists anywhere in the export. Either an authors table is supplied (§9 #9) or attribution is title-and-date only. The engine must never invent or omit-silently an author — an unattributable article is cited without a byline, not presented as unsourced. |
| **FR-98** | **A figure quoted from an article is reported as the article's statement, never as an approved figure.** The engine may say what an article states and cite it; it may not promote that number into a data card, a chart, an evidence row, or a comparison against published values. Both are in the knowledge base; only one is a measurement. |
| **FR-99** | Where a figure in an article and a published figure disagree, both may be shown, each under its own provenance, and the disagreement is left visible. The engine does not reconcile them — the same rule that governs SCEAI against Oxford (FR-86). |
| **FR-100** | Where an answer draws on both an article and published data, the two are distinguishable to the reader. |
| **FR-101** | An article is used to explain a movement in an indicator only where it demonstrably concerns that indicator. Articles carry **no indicator foreign key**, so topical proximity is not evidence of relevance — this is the highest-risk retrieval path in the system and needs a relevance floor, not a nearest-neighbour result. |
| **FR-102** | Article recency is surfaced. 65 of 67 live articles carry a date; commentary written against a different macro environment must not read as current. |
| **FR-103** | Article search works in both languages over both bodies. All 67 live articles carry EN and AR content; an Arabic question must reach an article as readily as an English one. |
| **FR-104** | **Precedence: published data leads, written content gives it meaning.** Where both a published series and written content (analyst text or an article) address a question, the answer opens with the figure and its scope, then the meaning. The tester's expectations state this order three times independently — Test Ideas row 2 (*"hero number … analyst summary block … evidence rows"*), F-007 (*"indicators ordered by recency, and a few lines explaining what it all means"*) and F-029 (*"a simple answer before it goes in details"*). |
| **FR-105** | Precedence holds **even when written commentary is what was asked for**, where the question names an indicator. F-019 asked for *"the latest analysis of inflation"* and the expectation was still to anchor on the inflation indicator first. Commentary about an indicator is presented against that indicator's current figure, not free-floating. |
| **FR-106** | Written content leads only where published data cannot address the question at all, or where the question is about the writing itself — an article by name, a list of articles, a summary, a policy or context question with no indicator behind it. |
| **FR-107** | Leading with data is not licence to lead with **all** the data. F-021 recorded a technically correct answer the tester rejected as *"I did not ask for all of this."* The figure that answers the question comes first; everything else is depth, subject to FR-58 and the lens rules. |

### F11 — Operational surface `[DEFERRED]`

**The admin panel is out of scope for now, by decision on 2026-09-14.** The requirements below are
retained with their IDs intact rather than deleted, so that reinstating them later costs nothing and
downstream references do not break.

**Two of them are not deferred, because the engine cannot work without them.** The engine holds a
local copy of the published data, so a refresh mechanism is mandatory — without the panel it is a
scheduled job or a command, not a screen. FR-108 and FR-110 therefore stay **in scope**; everything
else in this group waits.

Deferring the panel reopens what it had closed: **refresh cadence and audit retention return to
open questions** (§9 #8), since there is no longer an operator setting to carry them. Rule and
message changes fall back to a reviewed change in version control, which still satisfies FR-73 —
an audit trail and a reviewer — but puts them out of reach of anyone who does not work in the repo.
That is a real cost against F8's purpose, and it is the reason to reinstate the panel eventually.

| ID | requirement |
|---|---|
| **FR-108** | **IN SCOPE.** **Data refresh is an explicit, observable action** — a scheduled job or a command while there is no panel. It reports what changed, what failed, when it last ran, and what the engine is now serving. A silent refresh is indistinguishable from a broken one. |
| **FR-109** | **IN SCOPE** (it is a property of FR-108, not of the panel). Refresh is **safe against a live system** and atomic from a reader's perspective: a question served during a refresh sees the old content or the new, never a mixture. |
| **FR-110** | **IN SCOPE.** **Ingest rejections are surfaced, not swallowed** — to a log and the request record while there is no panel. Publication-state filtering (FR-77a), unresolvable references and malformed content are reported with counts and examples. The export today contains `Korea`/`South Korea` duplicates, 61 orphaned details and 32 unresolvable author ids; those must be learned from a refresh report, not from a wrong answer. |
| ~~FR-111~~ | `[DEFERRED]` Administering the rule catalogue through a UI. Until then rules change by reviewed commit, which satisfies FR-73's audit trail but not F8's intent that non-engineers can see and change them. |
| ~~FR-112~~ | `[DEFERRED]` Administering the bilingual message catalogue. Wording fixes need a deployment until this exists. |
| ~~FR-113~~ | `[DEFERRED]` Retention as an operator setting — reverts to open question 8. |
| ~~FR-114~~ | `[DEFERRED]` Exposing quality signals for display. FR-76 still requires them to be produced; nothing displays them yet. |
| ~~FR-115~~ | `[DEFERRED]` Operator-action auditing — nothing to audit while there are no operator actions beyond FR-108. |

`[NOTE FOR PM]` When the panel returns it needs its own specification — authentication, roles,
approval workflow, screens are a different product. Reinstating F11 is then mostly un-deferring
these IDs.

## 6. Non-functional requirements

| ID | requirement |
|---|---|
| **NFR-1** | **Determinism.** The same question, asked repeatedly, produces the same bound query and the same figures. Variation in figures is a defect, not tolerable variance. |
| **NFR-1a** | **Decomposition stability.** Multi-part splitting (FR-12) is the only genuinely non-deterministic step on the answer path. The same question must split the same way on repeated runs; a question that partitions two different ways across runs is a defect, not variance to tolerate. |
| **NFR-2** | **Multi-part questions do not multiply latency.** Parts are answered concurrently, so a multi-part answer costs roughly the slowest part, not the sum of the parts. The fan-out is bounded, and the bound is stated rather than implicit. The concrete ceiling follows from NFR-3 once open question 6 is answered. |
| **NFR-3** | **Latency.** `[ASSUMPTION]` Target is to improve on the current 8–9s; a hard ceiling is required and not yet set. See §9. |
| **NFR-4** | **Data residency — confirmed on-premises.** No reader question, indicator data or published analysis leaves the estate on the SCEAI path. **The model and every index run inside the estate**; hosted model APIs and hosted vector services are therefore excluded, not merely discouraged. |
| **NFR-4a** | **Corrected by the architecture code sweep, 2026-09-14: the engine makes no direct external call at all.** Oxford is reached as another agent on the internal agent platform, on an internal hostname — the same path as the approved-data agent. The residency posture is therefore stronger than first stated: the engine's only outbound call is inside the estate, and whatever egress Oxford involves belongs to that platform, not to this engine. What the engine sends must still be explicit, minimal and recorded (FR-90) — the reader's question plus a deterministic context line, never approved data. |
| **NFR-5** | **Model independence.** The engine's correctness guarantees do not depend on which model is used; swapping the model changes prose quality, never figures. |
| **NFR-6** | **Testability without infrastructure.** Answer logic is exercisable with no database, no service and no model. |
| **NFR-7** | **Data refresh.** The engine reflects republished CMS content without a code change and without a deployment, via FR-108. `[ASSUMPTION]` **Cadence is unspecified** — it reverted to open when the admin panel was deferred. Whatever cadence is chosen, staleness must be visible rather than silent. |
| **NFR-8** | **Graceful degradation.** Loss of the model degrades prose quality only. The engine still answers, from the structured layer. |
| **NFR-9** | **Auditability.** The record in FR-74 is retained long enough to answer a challenge to any answer shown to the Council. `[ASSUMPTION]` **Retention period unspecified** — reverted to open with the admin panel. Record size per answer stays bounded regardless, so that any period later chosen is workable without re-engineering. |
| **NFR-10** | **External isolation.** The Oxford dependency cannot degrade, delay or block the SCEAI answer. It runs on its own budget and its own failure path; a slow or dead external service produces a stated gap, never a stalled or empty answer. |
| **NFR-11** | **Closed-world enforceability.** Compliance with FR-77–FR-81 must be demonstrable by inspection and by test, not asserted. An SCEAI answer whose provenance cannot be reconstructed is a failure regardless of whether it happens to be correct. |

## 7. How we will know it works

Correctness becomes a number, produced continuously, rather than a judgement made by looking at a
screenshot.

| metric | definition | target |
|---|---|---|
| **Bound-query accuracy** | % of corpus questions where the engine binds the *correct* measure, grain, period and country scope — asserted on the bound query, not the prose | the primary metric |
| **Parity** | corpus score of the new engine vs the current system, same runner | floor: no regression on any entry |
| **Rule coverage** | % of agreed rules with continuously-running evidence | 100% before acceptance |
| **Bilingual parity** | difference in corpus score between EN and AR | near zero — a gap is a defect |
| **Grounding** | % of figures traceable to an approved row | 100%, enforced, not measured |
| **Closed-world compliance** | % of SCEAI statements tied to a knowledge-base source | 100%, enforced structurally (FR-81) |
| **Provenance separation** | Combined answers where no figure, unit or claim crossed between SCEAI and Oxford | 100% — a single crossing is a serious defect |

**Counter-metrics** — the ways we could hit the above and still fail:

| counter-metric | watching for |
|---|---|
| **Refusal rate** | buying accuracy by declining to answer. Track **by cause**, and read against the coverage table in §5 — comparison reaching 7.3% of details means refusing comparisons is often correct. A *rising* rate matters; a *high* one may be honest. |
| **Disambiguation / clarification rate** | pushing the resolution problem onto the reader. A clarifying question is a good answer once, and a bad product at volume (FR-93). |
| **Oxford-carries-the-answer rate** | in Combined, the share of questions where SCEAI refused and Oxford answered. A rising number means the closed world is being quietly outsourced, and the approved-data product is hollowing out. |
| **Article-relevance precision** | articles carry no indicator foreign key (FR-101), so a plausible-but-unrelated article is easy to retrieve and hard to spot. Sample and review; a high article-usage rate is fine, a high *irrelevant*-article rate is the failure. |
| **Answer length** | "reasoning" degenerating into padding. F-021 was a *technically correct* answer that gave far more than was asked. |
| **Coverage** | scoring well on a corpus that avoids the hard questions. Corpus composition is reviewed, not just its score. |

`[ASSUMPTION]` Numeric targets for the first four are not yet set — they need the parity baseline
against the current system first, which does not exist yet.

**A stated limit.** Every metric above is objective, and **none of them measures whether the answer
reads as intelligent** — the complaint that started this project. Binding accuracy, grounding and
parity could all be perfect while the answers remain flat, and FR-58 / FR-107 (proportionality) are
likewise unmeasured. This is deliberate: a soft "quality" score would be gamed, and the honest
substitute is periodic human review of sampled answers by the people who made the complaint.
Recording it here so it is a known limit rather than a blind spot.

## 8. Delivery shape

Not a plan — a constraint on how the work is sequenced.

1. **Knowledge transfer precedes code.** The rules in the current system's 151 recorded findings are
   four years of expensive learning. They become agreed rules and executable evidence **before** the
   code that satisfies them is written. Skipping this is the version of this project that fails.
2. **One capability proven end to end** before the rest are built, to prove the shape carries a
   question through every layer.
3. **No capability is done until its evidence is green.** No moving on with a red entry and a promise.
4. **Cut over incrementally, with the old system as the reference**, not all at once. The behaviour
   nobody wrote down always exists, and running both is how it is found.

## 9. Open questions

Triaged at finalize. **Three are phase-blockers** — they would make the PRD unsafe to hand to
architecture, because a wrong guess changes the structure rather than a detail. The rest can ride
alongside the next phase, each with an owner and a point at which it must be answered.

| | items | must be answered by |
|---|---|---|
| **Phase-blocker** | 2 (model endpoint) | before architecture commits |
| **Build-blocker** | 10 (API group layer) | before the affected capability is built |
| **Open but not blocking** | 4 (rule approver) | see FR-72a |
| **Deferred decision** | FR-51 inactive-indicator behaviour | with QC, before build |

**Seven of the original ten are closed.** One genuine blocker remains, and it is the one that needs
someone with system access rather than a decision — so it will not resolve by being thought about.

### Still open

| # | question | why it matters | owner |
|---|---|---|---|
| **2** | **Which model endpoint is available, and does it support constrained output?** | **The one remaining phase-blocker.** FR-2, FR-12 and FR-78 assume a model whose output can be structurally constrained, and FR-81 requires closed-world compliance enforced structurally rather than by prompt. Sharper now that on-premises is confirmed: the model runs inside the estate, so this is a question about a specific locally-deployed model, not a vendor choice. | — |
| **4** | **Who approves the rule catalogue?** | Answered *"doesn't matter"* — FR-72 no longer names anyone, so nothing is blocked. But see **FR-72a**: this is the requirement that answers the founding complaint, and *agree* cannot be delivered by engineering. | — |
| **10** | **Does the live indicator-svc API expose the group layer the export does?** | FR-29/FR-29a read grouping from the published catalogue, where it is complete for all 189 indicators. Finding 67 says the *API* exposed only the category. Cheap to check, and FR-29 depends on it. | — |
| **8** | **Refresh cadence and audit retention — reopened.** | Closed by the admin panel, reopened when it was deferred. Neither blocks the build: FR-108 makes refresh explicit whatever its cadence, and record size stays bounded whatever the retention. But both are now defaults someone picks rather than settings someone controls, so they should be picked deliberately. | — |

### Closed

| # | question | resolution |
|---|---|---|
| 1 | QC assessment against 4.7.0 | **None exists.** The tester workbook is the complete written record — §1.1. |
| 3 | Residency | **On-premises confirmed**, and stronger than first stated — the code sweep found the engine makes no direct external call; Oxford is an agent on the internal platform. NFR-4, NFR-4a. |
| 5 | Oxford integration contract | **Partly answered by the code sweep.** Oxford is an agent on the internal platform returning `{answer, sources, confidence, limitations, chart_id}` — **prose, not structured figures** — which independently confirms FR-88's weaker branch was the right baseline. A percentage band-check on external prose already exists in the current system and is ratified rather than reinvented. |
| 6 | Latency ceiling | Folded into 8. The current 8–9 s stands as the number to beat (NFR-3). |
| 7 | Article vs data precedence | **Published data leads, written content gives it meaning** — FR-104–FR-107, resolved from the tester workbook's own stated expectations. |
| ~~8~~ | Refresh cadence, audit retention | **REOPENED** — see *Still open* above. The admin panel that would have carried them as operator settings is deferred. |
| 9 | Authorship metadata | **None exists beyond the supplied export.** `P04` has no author column and `Articles.AuthorId` resolves to nothing, so attribution is to the publishing body — FR-46, FR-97. |

**Resolved during drafting:** the three agents are in scope as routing behaviour (F10); both lenses
are in scope (FR-59–FR-59d); SCEAI is closed-world over the approved knowledge base (FR-77–FR-81);
clarifying questions are permitted (FR-91–FR-94); articles are first-class members of the knowledge
base (FR-77a, FR-95–FR-103); published data leads and written content gives it meaning
(FR-104–FR-107).

`[NOTE FOR PM]` One decision is deferred rather than open: **FR-51**, the behaviour for the 65
inactive indicators. It affects a third of the catalogue and needs QC, not investigation.

## 10. Appendix — evidence base

All 31 files under `docs/inputs/` were read and measured on 2026-09-14; 33 foreign keys were
verified programmatically, 32 resolving at 100%. Every figure in this PRD is first-hand, not quoted
from the prior documents.

| source | what it gave |
|---|---|
| `docs/inputs/cms/P01–P17` (**20 files**) | the **published** CMS layer — 189 indicators, 289 details, 8,127 datapoints, 1,031 analyses, plus charts, benchmarks, intervals, dashboards and reference tables. `P10` and `P11` are 0-byte files. |
| `docs/inputs/cms/Item_*` (**6 files**) | the **base** CMS layer — 531 indicators, 644 details, 11,303 values, 1,226 analyses. No grain column and no Arabic; used only to establish what exists but is unpublished (FR-38a), and for the interval vocabulary. |
| `docs/inputs/{Articles,Champions,General Entities,Sectors}.csv` | 84 articles (**67 live**), 280 champions, 104 entities, 16 sectors |
| `docs/inputs/AskAI-test (4).xlsx` | tester feedback log — 35 findings (29 Major, 4 Minor, 1 Cosmetic), 16 test ideas, 15–25 Aug 2026. **Predates release 4.7.0** and is the origin of findings 1–24, not a report on them. |
| `FINDINGS-INDEX.md` + `app/` | 151 distinct findings, ~1,120 references across 15 modules — the recorded rule set the rebuild must inherit |
| `ARCHITECTURE.md`, `DESIGN.md`, `REWRITE.md` | prior analysis of the system being replaced. **Reference only** — not treated as binding, per the owner's instruction. |
| `addendum.md` | the measured data contract, the verified relationship map, the seven structural facts, and the design argument that follows from them |
| `reconcile-*.md`, `review-rubric.md` | the finalize record — what was checked, what was found, what was changed |

### Assumptions index

Every `[ASSUMPTION]` in this document, in one place. Each says what changes if it is wrong.

| # | assumption | where | status / if wrong |
|---|---|---|---|
| ~~A1~~ | No QC assessment against 4.7.0 exists | §1.1 | **Confirmed fact.** None exists; the tester workbook is the complete record. |
| A2 | Bilingual EN/AR is mandatory for every capability at equal quality | §2 | still assumed — F6 and the bilingual-parity metric scale back if wrong |
| A3 | Stakes are launch-grade — government, Council audience | §2 | still assumed — much of F8 and F9 could be lighter if wrong |
| A4 | Combined's latency at roughly 2× single-agent is acceptable | FR-89 | still assumed |
| A5 | Target is to improve on the current 8–9 s; no hard ceiling set | NFR-3 | still assumed — the 8–9 s baseline stands as the number to beat |
| ~~A6~~ | On-premises deployment | NFR-4 | **Confirmed fact.** Model and indexes run inside the estate; hosted model and vector services are excluded. |
| A7 | Data refresh cadence unspecified | NFR-7 | **Re-opened.** Was resolved by the admin panel carrying it as an operator setting; the panel is deferred, so the cadence is a default someone must pick — see open question 8. |
| A8 | Audit retention unspecified | NFR-9 | **Re-opened**, for the same reason. Record size stays bounded regardless, so any period later chosen is workable. |
| A9 | Numeric metric targets pending the parity baseline | §7 | still assumed — targets set once the baseline exists |

**Two of nine resolved** — A1 and A6, both confirmed as fact. A7 and A8 were resolved and then
re-opened when the operator surface was deferred, which is the honest state rather than a tidy one.
Of the five still open, A2, A3 and A5 are safe in the conservative direction: each assumes *more*
rigour than might be required, so being wrong means the engine is over-built rather than under-built.
