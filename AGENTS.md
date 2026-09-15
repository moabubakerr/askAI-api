<!-- bmad:context -->
<!-- Verified 2026-09-15 against 117070d. Managed by bmad-project-context; edits inside this
     block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## askai-api

Ask AI answer engine — questions about Qatar's national indicator data, in English and Arabic,
answered only from approved published data. Python (3.11 locally, 3.13 targeted), FastAPI,
on-premises. **No application code yet** — this repository holds the planning documents the build
is made from and the reviewed CMS export it inherits.

## Policy

- Never edit `../abubaker/askai-src-snapshot-20260913/` — a read-only reference copy of the system
  being replaced. Consult it as evidence; never copy its implementation.
- Never check in a generated or derived file. `data/` is the source; regenerating is the ingest
  path (FR-108) being exercised.
- Contradicting an architecture decision in `docs/ARCHITECTURE-SPINE.md` is a spine change, not a
  local call — raise it before building.

## Where things are

- Planning documents, in reading order: `docs/PRD.md`, `docs/ARCHITECTURE-SPINE.md`,
  `docs/DATA-CONTRACT.md`, `docs/RULES.md`, `docs/FINDINGS-TRIAGE.md`.
- Epics and stories: `_bmad-output/planning-artifacts/epics.md`. `_bmad-output/` is gitignored.
- The 151 recorded findings and the predecessor's source sit outside this repo, in
  `../abubaker/askai-src-snapshot-20260913/` — `FINDINGS-INDEX.md` and `app/`. Both are needed to
  close `docs/RULES.md` §4.2.
- Application code goes in `src/askai/`, tests in `tests/`; both are declared in `pyproject.toml`
  and neither exists yet.

## Running and verifying

- Run `python`, not `python3` — `python3` is the Microsoft Store stub and exits without running.
- Run BMAD skill scripts as `python <script>`; `uv` is not installed, so the `uv run ...`
  invocations the skills print will fail.
- Install the dev tooling before the first test run — `ruff` and `mypy` are declared in
  `pyproject.toml`, neither is installed, and there is no virtualenv:
  `python -m pip install -e ".[dev]"`.
- TODO once code exists: record the verified test, lint, typecheck and `import-linter`
  invocations here, with any caveat the config cannot state.

<!-- /bmad:context -->
