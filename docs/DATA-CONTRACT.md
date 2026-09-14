# Addendum — Ask AI rebuild

Technical depth gathered during Discovery. This is downstream material: it feeds
`DATA-CONTRACT.md` (REWRITE.md Phase A.3), the architecture document, and the corpus design.
It is **not** the PRD.

All figures below were measured directly from `docs/inputs/` on 2026-09-14, not quoted from
`REWRITE.md`. Where a measurement contradicts an existing document, that is called out.

---

## 1. The data contract as it actually is

### 1.0 There are two layers in this export, not one

The 17 CMS files are not one dataset. They are **two layers of the same CMS**, and the distinction
is the single most important structural fact about the export:

| | `Item_*` — the **base** layer | `P*` — the **published** layer |
|---|---|---|
| what it is | the full CMS working set, including drafts and retired content | the approved subset that reached readers |
| indicators | 531 | **189** (35.6%) |
| details | 644 | **289** (44.9%) |
| values | 11,303 | **8,127** (71.9%) |
| analyses | 1,226 | **1,031** (84.1%) |
| grain / interval | **absent — no interval column exists** | present on every row |
| Arabic analysis | **absent — English only** | present (`SummaryAR`, `DetailedAnalysisAR`, …) |
| unit, polarity, format, source, target | absent or partial | complete |

**The published layer is the only answerable one**, and not by policy alone — the base layer
physically cannot answer the questions this engine is for. It has no grain column, so FACT 1 is
unresolvable in it; it has no Arabic analysis, so half the bilingual requirement is unmeetable;
it has no unit or format, so no figure can be rendered correctly.

The two layers join cleanly and completely, which makes the base layer useful for exactly one
thing — knowing what exists but is **not** approved (§1.4):

```
Item_2_Indicators_Catalog.Id   ←──  P01.SourceIndicatorId        189 / 189  ✓
Item_4_IndicatorDetails.…Id    ←──  P02.SourceIndicatorDetailId  289 / 289  ✓
Item_1_Values.DataPointId      ←──  Item_1_DataPointAnalysis     1226 /1226 ✓
Item_1_Values.IndicatorDetailId ──► Item_4.IndicatorDetailId     11303/11303 ✓
P16 / P17                            the base→published key maps, 189 / 289
```

### 1.1 The spine: four tables, one chain — *the published layer*

```
P01_Published_Indicators          189 rows   the catalogue — what the reader can name
   │ PublishedIndicatorId
   ▼
P02_Published_IndicatorDetails    289 rows   the measurable — unit, polarity, format, source
   │                                         189 are IsMain=True (1 per indicator)
   │                                         details per indicator: median 1, max 10
   │ PublishedIndicatorDetailId
   ▼
P03_Published_DataPoints        8,127 rows   the numbers — (detail × interval × period × country)
   │ PublishedDataPointId
   ▼
P04_Published_DataPointAnalysis 1,031 rows   what an analyst WROTE about one datapoint
```

Referential integrity is clean: **0 orphan analyses**. But coverage is not uniform, and the
gaps are where the failures live:

| gap | measured | consequence |
|---|---|---|
| indicators with **no datapoints at all** | 28 of 189 | 15% of the catalogue is nameable but unanswerable. Must be a distinct refusal, not "no data". |
| details with no datapoints | 28 of 289 | same |
| datapoints with **any** analysis | 1,031 of 8,127 (12.7%) | — |
| datapoints with a **substantive** EN summary | 652 of 8,127 (**8.0%**) | **92% of numbers have no "why" behind them.** |
| indicators with ≥1 substantive analysis | 121 of 189 | 68 indicators can never answer a "why" question |

> The single most important number in this table is **8.0%**. Any design that treats "explain
> this movement" as a generally-available capability is designing against the data.

### 1.2 Supporting tables

| file | rows | what it settles |
|---|---|---|
| `P05_BenchmarkCountries` | 209 | **Only 21 of 289 details (7.3%) have a declared benchmark country set.** Cross-country comparison is a minority capability, not a default. |
| `P06_Intervals_ActualTarget` | 638 | Declares which grains each detail publishes at, split `Actual` (420) / `Target` (218). This is the frequency contract. |
| `P07_Charts` + `P07a/P07b` | 189 / 113 / 242 | Chart type, default view, alternate views (MoM/YoY/QoQ), sub-indicator membership, footnotes |
| `P08_AdditionalCharts` + `P08a` | 37 / 342 | Geo maps and extra benchmark chart configs |
| `P09_Dashboards` | 378 | **The group/ownership layer** — 189 indicators × 2 dashboards (Executive, Leadership), carrying `EntityClassification` + `EntityId` |
| `P12_Ref_Lookups_Common` | 142 | 10 lookup types — units, aggregation, polarity, value type, input method, … |
| `P13_Ref_IndicatorPriorityTypes` | 3 | Non-Priority / Priority / **Confidential** — the confidentiality gate |
| `P14_Ref_Countries` | 235 | country reference incl. lat/long |
| `P15_Ref_AlternateViews` | 10 | the 10 named derived views, each bound to an interval |
| `P16_Base_Indicators_MappingTargets` | 189 | base→published indicator identity mapping |
| `P17_Base_IndicatorDetails_KeyMap` | 289 | base→published detail identity mapping, plus `DwhIndicatorName` |
| **`P10_Published_Mappings`** | **0 — EMPTY FILE** | **no indicator-to-indicator relationships exist.** Causal/scenario answers have no substrate. |
| **`P11_Published_ValidationChecks`** | **0 — EMPTY FILE** | no published validation rules |

### 1.3 The non-CMS inputs

| file | rows | role |
|---|---|---|
| `Articles.csv` | 84 (**67 live**) | Bilingual HTML articles + audio URIs. **No foreign key to any indicator.** `AuthorId` is **unresolvable** — see below. |
| `Champions.csv` | 280 | Owning organisations (`IsMinistry` flag). **Not a grouping table** — it is the *owner of* a group, reached via `Sectors.ChampionId` (16/16) and `General Entities.ChampionId` (56/56). |
| `General Entities.csv` | 104 | Named entities under the non-Sector classifications — **one of the two group-name sources**. Descriptions are **base64-encoded HTML** in many rows; must be decoded on ingest. |
| `Sectors.csv` | 16 | The other group-name source. Note `Health and Social Services` exists **twice** (one is `| Leadership View`, `IsActive=0`). |

#### Three dangling references with no lookup table in the export

| reference | distinct values | resolves? |
|---|---|---|
| **`Articles.AuthorId`** | **32** | **No. There is no authors table anywhere in the export.** Does not resolve into Champions, General Entities or Sectors. |
| `Articles.SourceId` | 1 non-null GUID | No. |
| `General Entities.StageOfMonitoringId` | 4 | No lookup table in the export. |
| `General Entities.StatusId` | 4 | No lookup table in the export. |
| `General Entities.EntityClassification` | 6 | No lookup table in the export (the names appear denormalised in `P01`/`P09` instead). |

**`Articles.AuthorId` is the one that matters.** The PRD requires article content to be attributed
by **title, author and date** (FR-97). Title and date are present; **the author name is not
obtainable from this export**. Either an authors table is exported alongside, or the attribution
requirement has to be met with title and date only. This is a blocking data question, not a
design choice — raised as PRD open question 9.

### 1.4 The base layer file by file — and what each is good for

| file | rows | role | verdict |
|---|---|---|---|
| `Item_2_Indicators_Catalog` | 531 | every indicator the CMS holds. `IsActive=True` and `IsDeleted=False` on **all 531** — these flags carry no signal here. 61 rows have a **blank `NameEN`**. | **the refusal surface** — see below |
| `Item_4_IndicatorDetails` | 644 | every detail, with `DefinitionEN/AR`, `Format`, baseline and target. 61 rows point at an `IndicatorId` **not present in `Item_2`** — genuine orphans, and none of them is published. | definitions only |
| `Item_1_IndicatorValues_ByCountry` | 11,303 | every value. `DataPointId`, `IndicatorDetailId`, `Period`, `Country`, `Actual`, `Target`. **No interval column.** | not answerable |
| `Item_1_DataPointAnalysis` | 1,226 | analyst text keyed by datapoint. **`Summary_EN` and `DetailedAnalysis_EN` only — no Arabic.** Substantive on 793 / 681. | English-only; superseded |
| `Item_1_Intervals` | 3 | Monthly / Quarterly / Yearly, with the GUIDs used throughout `P03`, `P06`, `P15`. | **the grain vocabulary** |
| `Item_6_Countries` | 235 | `Id`, `NameEN`, `NameAR`. | **redundant** — `P14` has the identical 235 rows and adds `UniqueId`, `Code`, latitude, longitude |

**`Item_1_Intervals` is small and load-bearing.** Three rows define the entire grain vocabulary —
`monthly` / `quarterly` / `yearly`, bilingual, with the GUIDs that `P03.IntervalId`,
`P06.IntervalId` and `P15.IntervalId` all reference. FACT 1 is built on these three rows.

**`Item_6_Countries` is fully subsumed by `P14_Ref_Countries`** — same 235 ids, same 235 names,
zero divergence. Ingest `P14` and ignore `Item_6`.

#### The refusal surface: 342 indicators that exist but are not approved

| | count |
|---|---|
| indicators in the CMS catalogue | 531 |
| of those, **published** | 189 |
| of those, **not published** | **342** |
| of the unpublished, carrying a real EN name | **281** |
| details in base but not published | 355 of 644 |
| values in base but not published | 3,176 of 11,303 |
| analyses in base but not published | 195 of 1,226 |

The unpublished names are not junk. They include *"Private Investment as a Share of Total
Investment"*, *"International Programme for Student Assessment (PISA) Test Average Score"*,
*"Classified Hotels (%)"*, *"The Rate of Volunteer Work"*. A reader can and will ask about these.

**This creates a refusal state the PRD did not previously distinguish.** The engine currently has
to separate *"no such indicator"* from *"exists but has no data"* (28 of 189). The base layer adds
a third: ***"this exists in the CMS but is not approved for publication."*** That is a materially
better answer than "I don't know about that" — it tells the reader the question was sensible and
the gap is editorial, not a failure of understanding.

Whether to use the base layer for this is a genuine design decision with a cost: it means loading
531 names purely to give better refusals, and it risks a reader concluding that unapproved data
exists and can be obtained. **Recommended:** use it, but only to shape the refusal wording — never
to surface a value, a period or a definition from an unpublished row.

---

### 1.5 Verified relationship map

Every relation below was tested programmatically on 2026-09-14. **31 of 31 files on disk are
accounted for.** 33 foreign keys tested; **32 resolve at 100%**, one is partial and explained.

```
                      ┌──────────────────────── the published KB ────────────────────────┐

  P16 ──189/189──► I2                     P12_Ref_Lookups_Common (142, 10 types)
  P17 ──289/289──► I4                       ├─ Units(41) ◄── P02.UnitId            289/289
   ▲                ▲                       ├─ DataSources(52) ◄── P02.DataSourceId 289/289
   │                │                       ├─ Polarities(2) ◄── P02.PolarityId     289/289
   │ 189/189        │ 289/289               ├─ ValueTypes(2) ◄── P02.ValueTypeId    289/289
   │                │                       ├─ AggregationTypes(4) ◄── P02          289/289
  P01 ◄──289/289─── P02 ◄──8127/8127─── P03 ─┤ InputMethods(3) ◄── P02             289/289
   │                 │                    │  ├─ ChartTypes(19) ◄── P07.ChartTypeId  189/189
   │                 │                    │  ├─ IndicatorTypes(9)
   │                 │                    │  └─ ValidationChecks(7)  ← P11 is EMPTY
   │                 │                    │
   │                 │                    └──1031/1031──► P04  (analysis per datapoint)
   │                 │                    │
   │                 │                    └──2864/2864──► P14_Ref_Countries (235)
   │                 │                                      ▲            ▲
   │                 ├──209/209──► P05_BenchmarkCountries ──┘            │
   │                 ├──638/638──► P06_Intervals_ActualTarget            │
   │                 └───37/37───► P08_AdditionalCharts ──342/342──► P08a┘
   │
   ├──189/189──► P07_Charts ──┬──113/113──► P07a_SubIndicators ──113/113──► P02
   │                          └──242/242──► P07b_AlternateViews ─242/242──► P15_Ref(10)
   │
   ├──378/378──► P09_Dashboards   (Executive | Leadership)
   │
   ├─ IndicatorPriorityTypeId ──105/105──► P13_Ref (Non-Priority|Priority|Confidential)
   │
   └─ IndicatorEntityTypeId ──189/189──► Sectors.csv(16) ∪ General Entities.csv(104)
                                              │                    │
                                              └─16/16─┐  ┌─56/56───┘
                                                      ▼  ▼
                                                 Champions.csv (280)   ← owner, not a group

  Item_1_Intervals (3) ◄── P03.IntervalId 8127/8127, P06 638/638, P08 37/37,
                           P15 10/10, P07.DefaultView 189/189

                      └──────────────── the base layer (reference only) ────────────────┘
  I2 (531) ◄──583/644── I4 (644) ◄──11303/11303── I1v (11303) ◄──1226/1226── I1a (1226)
                 ▲ 61 orphans: details whose IndicatorId is absent from I2. None published.

  UNRESOLVABLE: Articles.AuthorId (32 distinct) · Articles.SourceId · GeneralEntities
                StageOfMonitoringId / StatusId / EntityClassification
  REDUNDANT:    Item_6_Countries ≡ P14 (identical 235 rows; P14 adds Code/UniqueId/lat/long)
  EMPTY:        P10_Published_Mappings (0 bytes) · P11_Published_ValidationChecks (0 bytes)
```

**Internal consistency check:** for all 8,127 datapoints, `P03.PublishedIndicatorId` agrees with the
`PublishedIndicatorId` that `P02` records for the same detail — **0 disagreements**. The denormalised
indicator id on `P03` is safe to trust.

**Note:** `P12` contains a `ValidationChecks` lookup with 7 entries, while
`P11_Published_ValidationChecks` is a 0-byte file. The vocabulary for validation rules exists; no
rules were published against it.

---

## 2. The seven structural facts that explain the QC failures

Each is a measured property of the data that the current implementation does not model.
These are the rules the rebuild must encode as data, not prose.

### FACT 1 — Grain is a first-class attribute, and 90 details are multi-grain

Declared `Actual` interval sets across the 261 details that carry data:

| declared grains | details |
|---|---|
| yearly only | 163 |
| quarterly + yearly | 49 |
| **monthly + quarterly + yearly** | 41 |
| quarterly only | 25 |
| monthly only | 11 |

**90 details publish at more than one grain.** For every one of them, "the latest value" has
more than one correct answer, and they differ:

```
latest ACTUAL period, system-wide, by grain:
  monthly    2026-04
  quarterly  2026-Q1
  yearly     2025
```

Declared grain and observed grain agree on 259 of 261 details (2 exceptions), so `P06` is a
**trustworthy contract** — the frequency rule can be driven from it rather than inferred from
the rows.

*Explains:* F-006 (returned quarterly when monthly existed), F-022/F-023 (QoQ when YoY was
asked), F-024/F-025 (quarterly chosen for an indicator whose natural grain is monthly),
F-029 (Q1-2026 presented as "latest" alongside an Apr-2026 figure — both true, different grains,
mixed in one answer).

**Rule implied:** `grain = from_question → else detail's declared default → never the data's last row.`
Inflation proves the point: it publishes 612 monthly, 202 quarterly, 49 yearly rows. Monthly is
available back to 2019-01. Choosing quarterly was a rule defect, never a data gap.

### FACT 2 — Change and growth are PUBLISHED, not computed

`P03` carries ten precomputed change columns:

| column | populated |
|---|---|
| `MonthlyMoMPercent` / `MonthlyMoMpp` | 1,574 / 658 |
| `MonthlyYoYPercent` / `MonthlyYoYpp` | 1,106 / 561 |
| `QuarterlyQoQPercent` / `QuarterlyQoQpp` | 1,615 / 357 |
| `QuarterlyYoYPercent` / `QuarterlyYoYpp` | 1,347 / 309 |
| `YearlyYoYPercent` / `YearlyYoYpp` | 990 / 725 |

Two distinct flavours — **`Percent` (%)** and **`pp` (percentage points)** — and conflating them
is a category error on any indicator already measured in %. Inflation is measured in `%`; its
change is in `pp`.

*Explains:* F-005 (system computed its own growth between two arbitrary datapoints instead of
using the published YoY), F-029 (unlabelled growth — "must label exactly which growth rate").

**Rule implied:** the system selects a published change column matching (grain × basis); it
computes a delta itself only where no published column exists, and says so when it does.

### FACT 3 — Qatar is the absent country *(refined by the base layer)*

- 5,263 of 8,127 published datapoints have **no country** → these are Qatar/national.
- 2,864 carry a country → these are benchmark rows.
- **`Qatar` never appears as a `CountryEN` value in `P03`.** Nor in the base layer.
- Only 30 distinct countries appear in published data, of 235 in the reference table.
- Only **21 details** have a declared benchmark set in `P05`.

**The base layer confirms this is deliberate, and names the convention.** In
`Item_1_IndicatorValues_ByCountry`, the national scope is an explicit country value:

> **`National / Overall` — 7,354 of 11,303 base rows (65.1%)**

Every base row carries a country; **none is blank**. Publication converts `National / Overall` into
an empty `CountryEN` (7,354 base → 5,263 published; 3,949 benchmark rows → 2,864).

So the empty country in `P03` is not missing data and not an oversight — it is the published
encoding of a value the CMS states explicitly. That is worth knowing before someone "fixes" the
blanks during ingest, which would silently merge the national series into the benchmark set and
reproduce F-001 at the data layer.

#### The trap: the config tables name Qatar, the data table never does

| table | rows naming `Qatar` |
|---|---|
| `P05_Published_BenchmarkCountries` | **21** — Qatar is in **all 21** declared benchmark sets |
| `P08a_AdditionalCharts_Countries` | **37** |
| **`P03_Published_DataPoints`** | **0 of 8,127** |

The configuration declares *"Qatar is one of the benchmark countries for this indicator."* The data
table never carries that label. **The obvious implementation — read the declared benchmark list,
look up each country's value — therefore succeeds for every country except Qatar.**

Concretely, Inflation at `2026-Q1`:

```
   P05 declares : Bahrain, KSA, Kuwait, Norway, Oman, Qatar, Singapore, Switzerland, UAE
   P03 provides : Bahrain 0.95  KSA 1.78  Kuwait 1.99  Oman 2.35  Singapore 1.48
                  (BLANK) 2.98   ← Qatar, unreachable by name
```

This is very likely the mechanism behind **F-001** — asked *Qatar vs Singapore*, the card showed six
countries. If `Qatar` cannot be resolved as a filter value, the two-country scope the reader asked
for cannot be constructed, and the system falls back to emitting the declared set.

**Design consequence:** national scope is a **distinct query shape**, not a country filter value.
Every cross-country answer is a union of two queries — `country IS NULL` for Qatar and
`country IN (…)` for the benchmarks — and the domain model should make that structural rather than
leaving it to each call site to remember. The old system had four independent row selections on one
card (finding 1); this is exactly the kind of rule that must be bound once.

*Explains:* F-001 (asked Qatar vs Singapore, got 6 countries — the system emitted the detail's
whole declared benchmark set instead of the two countries named), F-027 ("which country had the
lowest inflation" answered with one country's historical low — no country dimension was engaged
at all).

**Rule implied:** country scope is `named-in-question → else declared benchmark set → else
national-only`. Named countries **filter** the benchmark set; they never expand it. Inflation's
declared set is Bahrain, KSA, Kuwait, Norway, Oman, Qatar, Singapore, Switzerland, UAE — but only
Bahrain, KSA, Kuwait, Oman, Singapore, UAE actually carry rows. Both facts must be modelled:
"declared but no data" is a different answer from "not a benchmark".

### FACT 4 — The group layer is in the published catalogue, and `P01` is the authoritative source

> **Corrected 2026-09-14 after FK verification.** An earlier draft of this section said the group
> layer exists only in `P09` and that the catalogue does not expose it. That is wrong for this
> export: `P01` carries **both** `EntityClassificationName` and `IndicatorEntityTypeId`, and it is
> *more complete* than `P09`.

| source | completeness |
|---|---|
| `P01.IndicatorEntityTypeId` | **189 / 189 populated, 100% resolvable** |
| `P09.EntityId` | 338 / 378 populated — **blank on 40 rows (20 indicators)** |
| agreement where both are present | **338 / 338 identical**, and both `EntityClassificationName` columns agree 338/338 |

The 40 blank `P09` rows are entirely `DiversificationTargets` (24) and `NationalIndicators` (16) —
classifications that carry no sub-entity.

**Use `P01` for grouping. `P09` adds one thing `P01` lacks: dashboard membership** (Executive vs
Leadership), which is a presentation concern, not a grouping one.

The group entity **names** do not live in the CMS tables at all. `IndicatorEntityTypeId` resolves
across two of the loose CSVs, and you need both:

| resolves into | `P01` | `P09` |
|---|---|---|
| `Sectors.csv` (16 rows) | 105 | 210 |
| `General Entities.csv` (104 rows) | 84 | 128 |
| `Champions.csv` | **0** | **0** |

**`Champions.csv` is not a grouping table.** It is reached indirectly — `Sectors.ChampionId` (16/16)
and `General Entities.ChampionId` (56/56) both resolve into it, so a champion is the *owner of a
group*, never a group itself. An earlier draft listed Champions alongside Sectors as a group source;
that was wrong.

The classification level:

| classification | indicators |
|---|---|
| Sectors | 105 |
| SpecialEntities | 29 |
| SpecialProjects | 14 |
| **DiversificationTargets** | **12** |
| Enablers | 11 |
| Drivers | 10 |
| NationalIndicators | 8 |

Below classification sit **20 named entities**, sized 1–23 indicators (median 7), named from
`Sectors.csv` ∪ `General Entities.csv`.

*Explains:* F-032 — *"how many indicators in diversification target"*, QC expected **12**.
The data says exactly 12, and it says so in `P01` directly. This question was answerable all along.
Same root for F-033 (education sector indicator names) and F-034 (list indicators in Sectors). This
is finding 67/71 — "THE GROUP, NOT THE CATEGORY".

**Note on finding 67.** That finding says the group level was missing from the catalogue the old
system consumed — `sector` off `/indicators` was the *category*, not the group. That is a statement
about the **indicator-svc API**, not about this export. In this export the group level is present
and complete. The rebuild should read grouping from the published catalogue rather than
reconstructing it, and should confirm that the live API exposes what the export does.

### FACT 5 — 4% of rows are in the future, and 42 of them carry an `Actual`

322 datapoints have a period ending after 2026-09 (out to 2030). 289 of those are Targets —
legitimate. But **42 future-dated rows carry an `Actual` value**, most of them `0`.

A naive `max(Period)` for "latest" lands in the future, on a placeholder zero.

*Explains:* the QC instruction sheet's own known item — *"2029 zeros for Import/Export Time are a
known client-data issue"* — and contributes to F-024's skipped periods.

**Rule implied:** "latest" means *latest actual at or before today, with a non-placeholder value*.
Target rows and future rows are a separate, explicitly-labelled series.

### FACT 6 — Names are massively ambiguous; lexical matching cannot work

Across indicator names, detail names and labels (EN): **767 strings, 320 distinct, 257 of them
ambiguous** (the same string appears on more than one row).

Worst offenders: `Non-Hydrocarbon` (7), `Others` (7), `Sector Contribution To GDP` (6),
`Sector Exports` (6), `Number of Jobs in the Sector` (5).

- **15 details contain the substring "GDP"** — including *"Value of VC deals directed to
  Qatar-based start-ups (as a % of GDP)"*.
- **Exactly 1 detail is named "Inflation".**

*Explains:* F-003 precisely — *"give me a chart of Qatar's GDP"* resolved to the VC-deals
indicator and warned it was inactive. A substring match on "GDP" has 15 candidates and no
tie-break. F-014 (*"tourists"* found nothing because only the exact string *"Number of
international visitors"* matched) is the same defect from the other side.

**Rule implied:** resolution needs a semantic layer plus a disambiguation step that is allowed to
ask. It also needs group-scoped disambiguation — `Sector Contribution To GDP` is only meaningful
once you know *which sector*, and that lives in `P09`.

---

### FACT 7 — Country identity is not clean, in either layer

`Korea` and `South Korea` **both exist as country values, in the published layer as well as the
base layer** — 2 rows against 1 detail for `Korea`, 93 rows against 3 details for `South Korea`.
They are almost certainly the same country entered twice.

Seven further countries appear in the base layer but never survive publication: Algeria, Canada,
Poland, Russia, South Africa, Sri Lanka, USA. Nothing is published-only.

*Consequence:* a reader asking about South Korea must reach both spellings, and a benchmark set
containing both must not present the country twice. Country resolution needs an alias map, and the
alias map needs to be **data, reviewable by QC** — not a hard-coded dictionary, because this
duplicate will not be the last one.

---

## 3. Two data facts that settle open QC disputes

**`PublishingStatusName` is `Amended` on all 189 published indicators — 100%.**
F-005 asked *"what does status amended mean? this breeds confusion and lack of trust."* The
answer is that it carries zero information in this export. It should never be shown to a reader.

**`IsActive=False` on 65 of 189 published indicators (34%).**
An "inactive" indicator is still published and still has data. F-003's inactive warning was fired
on the *wrong* indicator, but the warning mechanism itself is load-bearing for a third of the
catalogue and needs a designed behaviour, not an interstitial prompt.

---

## 4. Implications for the build

### 4.1 Index and storage — what is embedded and what is not

The decisive measurement: **the numeric layer is 8,127 rows and the semantic layer is ~2,800
short strings.** This is a small-data problem wearing a big-data costume.

| layer | contents | size | store | why |
|---|---|---|---|---|
| **Numbers** | `P03` datapoints, joined to `P02`/`P01` | 8,127 rows | **Relational. SQL/table lookup. NEVER embedded.** | Every QC failure about a wrong number came from retrieval imprecision. Values must be fetched by exact key `(detail, grain, period, country)`, never by similarity. |
| **Resolution index** | indicator + detail names + labels, EN & AR | ~1,534 strings | small vector index + lexical index, **in-memory** | This is what embeddings are genuinely for — Arabic morphology (finding 42) and paraphrase (F-014). Sub-second at this size. |
| **Analyst index** | `P04` substantive summaries + detailed analyses, EN & AR | ~1,300 passages | vector index with **mandatory metadata filter** | Each passage carries its `PublishedDataPointId` → and therefore its indicator, grain, period, country. Retrieval must be filtered by those *before* similarity, not ranked by similarity alone. |
| **Article index** | live article content, EN & AR, chunked | **67** docs × 2 langs (~82k EN tokens) | vector index, separate namespace | No FK to indicators — relevance needs a floor, not a nearest neighbour. Publication state must be honoured on ingest (67 live of 84). |
| **Group/catalogue index** | `P01` classification + entity id, resolved through `Sectors` ∪ `General Entities`; `Champions` for ownership | ~400 rows | relational | F-032/33/34 are **SQL counting questions**, not retrieval questions. Group from `P01`, not `P09` — see FACT 4. |

**The load-bearing recommendation:** a dedicated vector database is not warranted by this data
volume. ~2,800 embedded strings fit in process memory; a file-backed index (FAISS / sqlite-vss /
pgvector on the existing DB) is sufficient, and keeps the deployment inside the government estate.
Choosing a hosted vector service here would add an external dependency and a data-residency
question to solve a problem that does not exist at this scale.

**The load-bearing constraint:** metadata filtering must come *before* vector similarity on the
analyst index. F-015 is what happens without it — an analysis for December 2025 retrieved for a
question about May 2025, on a monthly cumulative indicator, with a benchmark that does not exist.
Every one of those is a filter that was never applied.

### 4.2 On "how many agents"

The measured evidence argues for **very few**. The existing `DESIGN.md` already lands on one
supervisor plus a deterministic spine with constrained LLM leaves, and the data supports that
strongly:

- 92% of datapoints have no analyst text → there is little for a "reasoning agent" to reason over.
- `P10_Published_Mappings` is empty → no relationship graph for a "causal agent" to traverse.
- Growth, change, units, polarity, targets and baselines are all **published columns** → an
  "analysis agent" that computes them is re-deriving data that already exists, which is exactly
  the F-005/F-029 failure mode.
- The multi-part question problem (F-029, F-030) is a **decomposition** problem, which is one
  bounded LLM call, not an agent fleet.

The honest framing: the LLM surface should be **one decomposer, two constrained rescue calls
(intent, resolution), one guarded renderer, and one filtered retriever**. Everything that touches
a number stays deterministic. Adding agents adds places for a number to be invented.

### 4.3 Workflow shape

`DESIGN.md`'s `read → plan → fetch → compose → check` holds up against the data. The data adds
three mandatory steps the current implementation lacks, each traceable to a fact above:

1. **Resolve to a detail, not a name** — with disambiguation allowed to ask (FACT 6)
2. **Bind grain and country scope before fetching anything** (FACTS 1, 3)
3. **Prefer published change columns over computed ones** (FACT 2)

---

## 4B. An independent design argument

`REWRITE.md` and `DESIGN.md` are reference material, not a template. This section is what the
measurements argue for on their own terms, including where that departs from those documents.

### 4B.1 The central reframing: this is a query-compilation problem, not a RAG problem

The numeric layer is **8,127 rows**. That is a spreadsheet. Nothing about answering "what was
inflation in April 2026" is hard once you know that the question means
`(detail=Inflation, grain=monthly, period=2026-04, country=∅, measure=actual)`.

**Every single failure in the tester workbook is a failure to form that tuple correctly** — not a
failure to find data. F-003 formed it with the wrong detail. F-006 with the wrong grain. F-001 with
the wrong country set. F-011 never formed it at all. F-015 formed four of them and mixed the
results.

So the architecture should make that tuple — call it the **QuerySpec** — the centre of the system:

```
question + history
      │
      ▼
  RESOLVE ──────────► QuerySpec        every field bound, or explicitly UNBOUND
      │                (frozen, typed, serialisable, loggable, reviewable)
      │
      ├─ unbound field? ─► ASK the reader / REFUSE with the specific cause
      │
      ▼
  VALIDATE ─────────► QuerySpec is checkable against the catalogue BEFORE any IO:
      │                does this detail publish this grain? does this country have rows?
      │                is this period in range? is this indicator confidential?
      ▼
  EXECUTE ──────────► exact-key lookup. Deterministic. No similarity, no model.
      │
      ▼
  ASSEMBLE ─────────► typed result + provenance + any attributed analyst text
      │
      ▼
  NARRATE ──────────► guarded prose. Discardable. Never touches a figure.
```

The QuerySpec is simultaneously: the thing QC reviews, the thing tests assert on, the thing logged
for audit, and the thing shown to the reader when the engine explains what it did (FR-56). One
artifact serving all four is what makes the rules visible.

### 4B.2 Where I depart from `DESIGN.md`

**Depart 1 — the 19-intent enum is the wrong primitive.**

`DESIGN.md` carries a closed vocabulary of ~19 intents, each with a row in a plan table. The
problem is that an "intent" conflates two independent things: *what operation is being asked for*
and *how the scope is bound*. `SERIES`, `COMPARISON`, `SUPERLATIVE`, `SPREAD`, `SORT`, `SET`,
`POLAR` are not seven different questions — they are a handful of operations over different
scopes, and modelling them as seven parallel routes is how you end up with finding 102
(*"the SET route was built, tested, and unreachable"*) and finding 114 (*"the group route found
exactly ONE indicator"*).

I would model it as **operation × scope**, orthogonally:

| axis | values |
|---|---|
| **operation** | `value`, `series`, `change`, `compare`, `extremum`, `rank`, `spread`, `list`, `count`, `define`, `explain` |
| **scope: subject** | one detail · a named set of details · a group (classification or entity) |
| **scope: grain** | monthly · quarterly · yearly |
| **scope: period** | point · range · latest-actual · target/baseline horizon |
| **scope: country** | national (∅) · named set · declared benchmark set |
| **scope: measure** | actual · target · baseline · published change column (grain × basis) |

Eleven operations against five scope axes covers everything in the QC workbook, and the
combinations are *generated*, not hand-written. "Which country had the lowest inflation" is
`extremum × country-scope`. "Highest quarterly GDP" is `extremum × period-scope`. Today those are
two unrelated code paths, which is exactly why one worked and the other did not.

This collapses the rule surface substantially: grain selection is **one rule**, not nineteen
copies of it.

**Depart 2 — disambiguation is a primary outcome, not a rescue rung.**

`DESIGN.md` treats a failed resolution as something to rescue with a model call. With 257 of 320
names ambiguous, and `Sector Contribution To GDP` appearing 6 times, ambiguity is the *normal*
case, not the exception. The engine should be able to return "did you mean X, Y or Z?" as a
first-class answer — and the group layer (§2 FACT 4) is what makes those candidates
distinguishable to a reader.

**Depart 3 — resolution should be a scoped two-stage lookup, not a three-rung ladder.**

Rather than lexical → embeddings → LLM, I would do:

1. **Candidate generation** — union of lexical and semantic matches over the ~1,534 name strings.
   Cheap, high recall, no model call. Take the top ~10.
2. **Candidate discrimination** — score candidates against the *rest* of the question, using the
   scope signals already extracted: a named sector, a named grain, a named country, a period that
   only one candidate covers. Most ambiguity dissolves here **without a model**, because the
   discriminating information is structural.
3. **Ask or escalate** — only what survives both goes to a reader question or a constrained model
   call.

Step 2 is absent from both the current system and `DESIGN.md`, and it is the step the data most
rewards. "A chart of Qatar's GDP from 2022 to 2025" has 15 lexical candidates, but only a few
publish yearly data across 2022–2025 with a GDP-shaped unit. The question already contains the
tie-break.

**Depart 4 — the supervisor/decomposer is not the front door.**

`DESIGN.md` puts an LLM decomposer first, before anything else runs. That makes a model call the
mandatory first step of every request — the latency floor for all traffic, and a
non-deterministic component in front of a deterministic system. Most questions are single-part.

I would **detect** multi-part structurally (cheap, deterministic, high precision) and invoke the
decomposer only when that detection fires or confidence is low. Same capability, but the model is
not on the critical path of the common case, and single-part answers stay fully deterministic
end to end.

**Depart 5 — "business rules as YAML" needs a sharper contract than a folder of files.**

`DESIGN.md`'s `rules/*.yaml` is the right instinct. But four loose YAML files drift from the code
the moment someone adds a branch. The binding constraint should be: **a rule that is not
expressible as data about a QuerySpec is not a rule — it is a code path, and it needs a reason to
exist.** Rules govern *how a QuerySpec is bound and validated*; they do not govern control flow.
That keeps the rule set genuinely enumerable (FR-70) instead of "enumerable except for the parts
in Python".

### 4B.3 The LLM surface, stated exactly

Five call sites, and no agent fleet:

| # | call site | constrained to | if it fails |
|---|---|---|---|
| 1 | **Multi-part decomposition** (only when structurally detected) | a list of sub-questions; no facts, no answer shapes | answer as single-part |
| 2 | **Resolution discrimination** (only when steps 1–2 leave >1 candidate) | a choice among supplied candidate ids | ask the reader |
| 3 | **Operation classification** (only when the rule table is unsure) | the operation enum | refuse with cause |
| 4 | **Narration** | prose, guarded against the structured answer | the structured answer stands alone |
| 5 | **Article summarisation** | prose, guarded against the article body | return the article |

Plus **embeddings** — not a chat model — for candidate generation and analyst-passage retrieval.

Three of the five are conditional, which means **the common case runs with zero chat-model calls on
the answer path**. That is the latency answer and the determinism answer at once.

What is *not* a call site, and must not become one: computing or formatting a number, selecting a
grain, selecting a period, selecting a country set, deciding whether data exists, or stating why
something moved.

### 4B.4 Why "more agents" is the wrong instinct here

The pull toward a multi-agent design comes from the complaint that the answers show "no reasoning".
The measurements say that is not what reasoning would fix:

- **92% of datapoints have no analyst text.** A reasoning agent has nothing to reason from.
- **`P10_Published_Mappings` is empty.** There is no causal graph to traverse.
- **Change, growth, polarity, targets and baselines are published columns.** An agent deriving
  them re-creates the F-005 defect with more machinery.

What the tester actually asked for, read carefully, is *narrower and much more achievable*: answer
the question asked, at the right grain, labelled, proportionate, and say what you did. F-029 spells
out the desired answer in full and it is **three lines of correctly-bound figures**. That is a
binding problem, not an intelligence problem.

The genuine reasoning surface is the 8% of datapoints that *do* carry analyst text, plus 84
articles — and there the correct behaviour is retrieval with attribution, never generation.

---

## 5. A correction to carry into the PRD

`REWRITE.md` §2 states the QC workbook is *"the origin of findings 1–24, not a report on them"*,
and §5 A.2b notes it is dated 15–25 Aug, predating release 4.7.0 (verified 8 Sep). Reading the
workbook confirms this: it is a **tester feedback log**, 35 rows, authored by the tester as they
found things — not a QC verdict on the current build.

Severity distribution as recorded: Blocker 0, **Major 29**, Minor 4, Cosmetic 1, Idea 0.
The `Status` / `Fix version` triage columns are **entirely unfilled**, and the Summary sheet's
status rollups are `#REF!` errors.

Two unnumbered trailing rows carry the sharpest comment in the document, and it is not a defect
report — it is the thesis:

> *"Oxford answers provide reasoning — SCEAI answers are totally unintelligent."*
> *"SCEAI answers are only related to indicators without any reasoning at all."*

That is the same complaint as F-005's *"the chatbot is not able to reason with the available data,
it simply retrieves it."* It is the actual scope driver, and it is a product statement rather than
a bug.

**Open item:** whether a newer QC assessment against 4.7.0 exists. `REWRITE.md` A.2b flags this as
"not yet in hand, and the most important source once it is."
