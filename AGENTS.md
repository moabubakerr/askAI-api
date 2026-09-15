<!-- bmad:context -->
<!-- Verified 2026-09-15 against 117070d. Managed by bmad-project-context; edits inside this
     block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## askai-api

Ask AI answer engine — questions about Qatar's national indicator data, in English and Arabic,
answered only from approved published data. Python 3.13, FastAPI, on-premises. The repository
holds the planning documents the build is made from, the reviewed CMS export it inherits, and —
since Story 1.1 — the `src/askai/` package tree and its quality gates.

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
- Application code is in `src/askai/`, tests in `tests/`, the question corpus in `corpus/`.
  Every package under `src/askai/` declares its purity class in its module docstring, taken from
  the layer table in `docs/ARCHITECTURE-SPINE.md`; `tests/test_scaffold.py` enforces that.

## Running and verifying

- **`uv` is the package manager** and `uv.lock` is the committed pin. Setup, from a clean
  checkout: `uv sync --locked --all-extras` (it installs CPython 3.13 itself if missing).
- If `uv` is not on `PATH`, install it (`python -m pip install --user uv`) and add the user scripts
  directory — on Windows `%APPDATA%\Python\Python3xx\Scripts` — to `PATH`. Nothing here needs admin
  rights or the `astral.sh` install script.
- Run `python`, not `python3` — `python3` is the Microsoft Store stub and exits without running.
  Inside the project prefer `uv run python`, which uses the pinned 3.13 rather than the system
  3.11.
- **The gates. CI (`.github/workflows/ci.yml`) runs exactly these, in this order, and any one of
  them failing fails the build:**

  ```
  uv run lint-imports                 # AD-2 dependency contracts
  uv run mypy --strict src/askai tests
  uv run ruff check .
  uv run pytest
  uv run python tests/corpus_runner.py
  ```

- `tests/test_dependency_contracts.py` runs `lint-imports` as a subprocess, planting a violating
  module under `src/askai/` and removing it again. If a run is killed part-way, check for a stray
  `src/askai/*/_violation.py` before trusting a red gate.

<!-- /bmad:context -->
