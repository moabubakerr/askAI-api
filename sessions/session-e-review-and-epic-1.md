# Session E — finish Epic 1, and review what shipped without it

**Read `AGENTS.md` first.** This brief carries only what is specific to you.

You are the quality session. The other four are producing code faster than it is being reviewed;
your job is to close that gap and to lock the architecture's promises before eighty more stories
can erode them.

## You own

`tests/` — new review-driven test files · `src/askai/` **only to apply fixes you have justified** ·
new files under `src/askai/rules/data/`

You are the one session permitted to touch another session's source, and only to fix a defect you
have demonstrated. **Announce it, and never fix something that is merely in flight.** If a gate is
red because another session is mid-write, leave it.

## Why this session exists

Stories 1.1 and 1.2 went through a three-layer adversarial review — one reviewer hunting what is
missing, one tracing edge conditions, one checking whether the tests can actually fail. It found
defects that every gate had already passed:

- `Percent - Percent` returning `Percent`. Fully typed, fully tested, and **wrong** — the difference
  between two percentages is percentage points.
- A period parser accepting Arabic-Indic digits, so `Period("٢٠٢٥") != Period("2025")` while both
  claimed to be 2025.
- A deny-list asserted to work that had never been driven red.
- `.gitignore` naming a cache directory that does not exist, leaving the real one committable.

**Eighteen of the twenty stories since have had no such pass.** The risk is not that the code is
broken; the gates are real. The risk is the specific class of defect where *the test and the code
share the same wrong assumption* — which is exactly what `Percent - Percent` was.

## Work, in order

### 1. Story 1.18 — the bucket-A foreclosure tests

The highest-leverage thing you can do. These assert the architecture's promises structurally so
later epics cannot quietly undo them. Where a decision only ships in a later epic, assert the
structural property now — an absent conversion function, a missing constructor — and let that epic
add the behavioural half. **A foreclosure test that cannot be written is an architecture finding,
not something to work around.**

### 2. Review passes over the domain-logic stories

Only where a wrong answer could reach a reader. In rough priority:

`execute/` (latest resolution, exact-key fetch) · `assemble/format.py` (rounding, units,
Percent/pp) · `compile/binder.py` and `periods.py` (binding precedence, period expressions) ·
`adapters/readmodel/ingest.py` (the national marker, key collisions) · `domain/text.py` (the
published-text predicate, which reconciles to 652/379 and must keep doing so) ·
`observability/record.py` (the audit record's completeness)

Run three independent reviewers per target, in parallel, each with no prior context: one for what is
missing, one for edge conditions, one for whether the tests bite. Then verify each finding yourself
against the code before acting — **reviewers are wrong often enough that acting on an unverified
finding costs more than it saves.**

### 3. Story 1.7, when the VM is available

Database connectivity and durability on the target machine. Blocked until someone runs it there.
Every test so far has run on a Windows laptop against temporary SQLite.

### 4. The three documents that disagree with the code

Not yours to rewrite — `docs/` is the architect's and the analyst's — but worth a precise report:

- The spine's response `spec` block lacks `spec_version`, which the API now returns.
- `R-174`'s Arabic plural rule says "11+ → singular accusative". Correct to 99, **wrong from 100** —
  the last two digits decide, so 103 is *few* and 111 is *many*. The code implements the full rule.
- AD-13 says vectors live in the read-model database; AD-20 and Story 2.1 say a separate file
  swapped by reference. The separate file is what was built.

## How to judge a finding

Verify the claim at the cited line before acting on it. Ask whether the bad outcome actually
happens, not whether the fix sounds plausible. Code that loudly fails on a situation nobody showed
it can reach is correct behaviour, not a defect. A vague "this is messy" with no named harm is not a
finding.

Fix what is real and small. Record what is real and large. Reject what is not real, **with the
refutation written down** — `_bmad-output/implementation-artifacts/deferred-work.md` is the ledger.
