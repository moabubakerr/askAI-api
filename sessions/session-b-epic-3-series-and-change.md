# Session B — Epic 3: series, change and targets

**Read `AGENTS.md` first.** This brief carries only what is specific to you.

## You own

`src/askai/assemble/change/` · `corpus/epic-3.yaml` · new files under `src/askai/rules/data/` ·
new test files

**Do not put a composer directly in `assemble/`.** Sessions C and D are adding composers too, and
the subpackage is the only thing keeping you out of each other's way.

Do not touch `compile/`, `execute/`, `adapters/`, or another session's tests.

## Already done — read before writing

- **3.1** `compile/periods.py` — every period expression in both languages, including closed and
  open spans binding to `Range`. It deliberately leaves an **open-start span** (`"up to 2025"`)
  binding as `Exact`, because `PeriodSpec` has no open-start member and there is no anchor that
  would not be invented. If your series work needs one, that is a domain change, not a local fix.
- **1.12** `execute/` — `Outcome[Figure]` (`Found | Absent | Failed`) and `PeriodResolution`, which
  records what a deferred field resolved to and every reading for `LastN(n)`. That is your series.
- **1.13** `assemble/format.py` — the single `Formatter`. **No composer may build a numeric string
  by any other route**, and a scan enforces it. It returns numeral and unit as separate fields and
  never joins them, because joining is per-language editorial text.
- **1.14** `assemble/roles.py` — `Placement.mode_for(role)` chooses the `FormatMode`. Never name a
  `FormatMode` member in a composer; a scan fails the build on it.

## Stories, batched

| Batch | Stories | Notes |
|---|---|---|
| **1** | **3.2 + 3.3** | A series over a range, and stating the gaps rather than skipping them. One composer; a gap is content, not an omission. |
| **2** | 3.4 + 3.5 + 3.6 | Select the published change column, name the basis and periods, percent is never percentage points. One change composer. |
| **3** | 3.7 | Compare the same indicator at two named periods. Note 3.1 binds `"between X and Y"` as a *comparison*, not a span — it is already `Unbound` with a reason, waiting for you. |
| **4** | 3.8 | Answer from published targets and baselines. |

## Constraints specific to you

- **Never recompute a change that is published.** AD-4: change values are *selected* from the
  published column matching `(grain × basis)`. Compute only when no published column exists, and
  mark the result `Derived` with its inputs stated. The read model already carries the change
  columns by basis — `adapters/readmodel/schema.py`.
- **`Percent` and `PercentagePoints` are distinct types with no conversion.** `Percent - Percent`
  returns `PercentagePoints` — the difference between two percentages is percentage points, and
  getting this wrong is the F-005/F-029 defect class. A review caught it returning `Percent` once
  already.
- **`datapoint.baseline` is NULL on all 8,127 rows.** The export publishes a baseline per *detail*,
  on `P02`, not per datapoint — Story 1.8 deliberately did not copy it down, because that would make
  one declared value look like 8,127 measured ones. Story 3.8 reads it from the detail.
- **A gap is stated, never skipped.** A series missing 2023 says so. Use the `Absent` element class
  — it carries content, it is not a missing element.
- **21 details publish text, not numbers** (`"Tier 1"`, `"ناشئة"` — 126 rows). They currently answer
  absent. A series over one of them is not a series; refuse it clearly.

## Testing without the ladder

Session A is building resolution. Until it lands you cannot ask a real question and get your
composer — so **construct the `QuerySpec` directly** in tests and drive the composer from it. That
is also the better unit test. Add corpus entries to `corpus/epic-3.yaml` for when the ladder arrives.
