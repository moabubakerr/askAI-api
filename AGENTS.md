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

## The target VM — measured 2026-09-16

Kept outside the managed block above so a context refresh does not drop it.

### The model endpoint

- `http://vllm:8000/v1/chat/completions`, OpenAI-compatible, single-model server.
- **The served model name is `qwen72b`. The model is actually `Qwen/Qwen2.5-32B-Instruct`, not a 72B.**
  Every request must send `"model": "qwen72b"` exactly; vLLM rejects a mismatch. Do not "correct"
  this to `qwen32b` — the name is what the server answers to, and the number in it is wrong.
- `max_model_len` is 16384. That is the whole budget: prompt plus completion. It constrains the
  narration prompt (Epic 8) and the candidate list in the resolution tie-break (Story 2.6).
- **The hostname resolves only inside the VM's Docker network** and is not published to the host.
  The engine must run on that network. Nothing here can reach it, so every model-touching story is
  built behind `ModelPort` with a fake, and NFR-6 still holds: the suite passes with no model.

### Hardware, and what is actually scarce

- GPU: one NVIDIA H200, 143,771 MiB. **vLLM holds ~130,473 MiB** (`--gpu-memory-utilization 0.90`),
  leaving **~13 GB free**. VRAM is the constrained resource, not RAM.
- RAM 235 GiB (~220 free), 22 CPU cores. Neither is a constraint.
- A second model process is acceptable. An embedding model at ~2.3 GB fits the free VRAM, and CPU
  inference is also viable for this corpus size — 1,101 surfaces indexed per refresh, one short
  query per question.

### Weights

Live egress works — `https://huggingface.co` returns 200 from the VM — so a runtime pull is
technically possible. **Whether it is the sanctioned route is unconfirmed**, and no evidence was
found of how the existing vLLM weights were staged. Treat a live pull as needing policy sign-off
for a public-sector deployment rather than assuming it is allowed.

### Reaching the runtimes from code — added 2026-09-16

The adapters exist: `src/askai/adapters/model/chat.py` (`ModelPort`) and
`src/askai/adapters/model/embeddings.py` (`VectorSourcePort`). Neither reads the
environment; both take a settings value from `src/askai/config/model.py`.

| Variable | Required | On the confirmed VM |
| --- | --- | --- |
| `ASKAI_MODEL_BASE_URL` | yes | `http://vllm:8000/v1` (the `/v1` root, no path) |
| `ASKAI_MODEL_NAME` | yes | `qwen72b` — **the number is wrong and the name is right** |
| `ASKAI_MODEL_API_KEY` | no | unset; vLLM there is unauthenticated |
| `ASKAI_MODEL_CONNECT_TIMEOUT` / `ASKAI_MODEL_READ_TIMEOUT` | no | 2s / 20s |
| `ASKAI_MODEL_TOKEN_BUDGET` | no | 16384 — `max_model_len`, prompt **plus** completion |
| `ASKAI_EMBEDDING_BASE_URL` | yes | the second process; not yet deployed |
| `ASKAI_EMBEDDING_MODEL` | yes | — |
| `ASKAI_EMBEDDING_DIMENSIONS` | **yes, no default** | it is written into every index file |

- Off the VM, set nothing. Every model-touching test uses
  `adapters/model/fakes.py` (`ScriptedModel`, `no_model()`, `FakeEmbeddingSource`), and
  `tests/test_model_adapter.py` drives the *real* clients through an
  `httpx.MockTransport`. The suite is green with no runtime reachable (NFR-6).
- **Guided decoding is available and is used.** `guided_json`, `guided_choice`,
  `guided_regex` and `response_format` go out as extra body fields. AD-8's
  parser-plus-validator floor still applies to every call: a constrained decoder still
  returns text, and it can still be truncated at the token budget.
- The embedding width is not discovered by probing. It is half of the index identity, so
  a guessed value would be written into an index file and compared at every later load.
