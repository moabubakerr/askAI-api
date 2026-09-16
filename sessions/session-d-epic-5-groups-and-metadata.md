# Session D — Epic 5: groups, metadata and the overview

**Read `AGENTS.md` first.** This brief carries only what is specific to you.

## You own

`src/askai/assemble/meta/` · `corpus/epic-5.yaml` · new files under `src/askai/rules/data/` ·
new test files. You may add read-model **queries** under `src/askai/adapters/readmodel/` in new
modules if the group layer needs them — but **do not alter the DDL or `SCHEMA_VERSION`**; if a
column is genuinely missing, stop and report it.

**Do not put a composer directly in `assemble/`.** Sessions B and C are adding composers too.

## Already done — read before writing

- **1.8** ingest — the catalogue, details, datapoints and reference tables are materialised. It also
  measured **22 distinct entity groups**, with all 189 indicators resolving to one, across
  `Sectors.csv` and `General Entities.csv`.
- **1.13/1.14** the single `Formatter`, and `Placement` with the lens mapping in
  `rules/data/answer-roles.yaml` — `scope` appears in **both** lenses deliberately, and removing it
  is the one edit to refuse.
- **1.15** `narrate/package.py` holds the only `AnswerPackage` constructor, and it carries a
  `chartable` block already stubbed as unavailable — Story 5.10 fills it.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **5.1 + 5.2** | Make the group layer queryable; distinguish a group from a classification. One query path. PRD Q10 marks 5.1 a build-blocker for *live refresh*, but the CSV export under `data/cms/` already carries the group layer — the query path is not blocked. |
| **2** | 5.7 + 5.8 + 5.9 | What an indicator means, what it is made of, and naming the residual honestly. One metadata composer. |
| **3** | 5.5 + 5.6 | The executive overview from the published curated set, and "what can you do" answered from the data actually held. **These are the two most demo-visible answers in the project.** |
| **4** | 5.3 + 5.4 + 5.10 | Questions about the data itself, who owns a group, and whether an answer can be charted. |

## Constraints specific to you

- **"What can you do" must be answered from the data actually held**, not from a written list of
  capabilities. A hand-maintained list drifts from the truth the moment an indicator is added; a
  question answered by counting the read model cannot.
- **Name the residual honestly.** If a curated set covers 60% of something, say what the other 40%
  is — an overview that silently omits is the failure mode Story 5.9 exists to prevent.
- **`Operation` has no member for an ownership lookup.** Story 5.4 ("who owns the tourism sector")
  has no good fit — `list` is the closest and it is wrong. The enum is in `domain/spec.py` and is
  frozen domain vocabulary. **Report this rather than forcing it**; adding a member is a domain
  change and needs a human.
- **Nothing unpublished may reach an answer.** `ports/unpublished_catalogue.py` exposes names and
  existence only, and a test asserts no type from it crosses into an `Answer`. Metadata questions
  are exactly where that boundary gets tested.
- **No published indicator is marked Confidential** — the type exists in
  `P13_Ref_IndicatorPriorityTypes` but the export has 105 `Priority`, 84 blank and **zero**
  confidential. A capability answer must not claim to be filtering something that is not there.
- **28 details publish no datapoints at all.** A count or a list that includes them without saying
  so is misleading.

## Testing without the ladder

Session A is building resolution. Construct the `QuerySpec` directly in tests; add corpus entries to
`corpus/epic-5.yaml` for when the ladder lands.
