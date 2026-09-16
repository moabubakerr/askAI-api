# Session C — Epic 4: comparisons, ranks and spread

**Read `AGENTS.md` first.** This brief carries only what is specific to you.

## You own

`src/askai/assemble/compare/` · `corpus/epic-4.yaml` · new files under `src/askai/rules/data/` ·
new test files

**Do not put a composer directly in `assemble/`.** Sessions B and D are adding composers too.

Do not touch `compile/`, `execute/`, `adapters/`, or another session's tests.

## Already done — read before writing

- **4.1** `rules/countries.py` and `rules/data/country-aliases.yaml` — 30 groups, 81 surface forms,
  every ISO code the published datapoints and the 21 declared benchmark sets carry. `resolve()`
  returns a closed `Country | HomeCountry`, and **`HomeCountry` is fieldless**, so
  `filter_values()` structurally cannot emit it. `filter_values()` is the handle you want.
- **1.8** ingest calls `extended_with()` with the reference rows, so the home country resolves in
  both languages at runtime even though its Latin name appears nowhere in the tree.
- **1.13/1.14** the single `Formatter` and `Placement.mode_for(role)`. Never build a numeric string
  any other way; never name a `FormatMode`.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **4.2 + 4.3** | Named countries filter the benchmark set and never expand it; "not a declared benchmark" is a different answer from "no rows". Start here — 4.3 is the distinction the whole epic rests on. |
| **2** | 4.4 + 4.5 | Compare countries at a stated common period; compare indicators each at its own period. |
| **3** | 4.6 + 4.7 + 4.8 | Superlatives that name what carries them, ranks as ordinals, spread between extrema. One extrema composer. |

## Constraints specific to you

- **The home country is an absence, not a value.** The benchmark config names it in all 21 declared
  sets; the data names it in **none of its 8,127 rows**. So a comparison that looks countries up by
  name retrieves every benchmark and silently drops the home country from its own comparison. That
  is FR-11b and it is the defect this epic exists to prevent. The literal is banned anywhere under
  `src/askai/` — use `HomeCountry`, never a string comparison.
- **A cross-country answer is the union of a national selection and a benchmark selection**,
  assembled in one place (AD-5). It is never one widened filter.
- **"Declared but no data" ≠ "not a benchmark."** `Total Population` is the only one of the 21
  declared sets with **zero** country rows — it is your worked example, and there is already a
  corpus entry pinning it.
- **Named countries filter, never expand.** If a reader names a country outside the declared set,
  the answer says so; it does not quietly add it.
- **Ranks are ordinals.** `rules/data/display-units.yaml` already carries
  `R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL` and `R-DISPLAY-RANK-UNIT-SPELLINGS`. Read them; do not
  restate them in code.
- **A superlative must name what carries it** — "highest" is not an answer without the country and
  the period that make it true.
- `Korea` and `South Korea` share code `KR` in the export, so either spelling reaches all 95 rows.
  Keying by code collapses them by data rather than by opinion. Do not "fix" it.

## Testing without the ladder

Session A is building resolution. Construct the `QuerySpec` directly in tests and drive the composer
from it; add corpus entries to `corpus/epic-4.yaml` for when the ladder lands.
