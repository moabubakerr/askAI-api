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

## Where the build is — handoff, 2026-09-16

20 stories, 22 commits, 1,399 tests, all five gates green at every commit. Epic 1 is 16 of 18;
Epic 2 has 2.1, 2.2 and 2.13; Epic 3 has 3.1; Epic 4 has 4.1. Nothing is in flight.

`POST /api/ask` works end to end: a question naming an indicator exactly returns a real figure with
its unit, period, scope and source reference, in English or Arabic, plus one audit record. No model
is involved anywhere yet.

### The house rules that trip every new agent

All of these are enforced by tests that scan the whole tree. They fail the build, and they are
load-bearing rather than stylistic:

- **One `normalise()`**, in `domain/`. The names `norm`, `normalise`, `normalize`, `normalise_text`,
  `normalize_text`, `_normalise`, `_normalize`, `fold_text`, `normal_form` are banned anywhere under
  `src/askai/` — a second implementation is finding 121's Arabic half returning.
- **The home country's name is a banned literal** anywhere under `src/askai/`, docstrings and
  comments included. National scope is the *absence* of a country. `domain/scope.py` has the
  phrasing to copy; `rules/countries.py` has a fieldless `HomeCountry` that cannot become a filter.
- **No `os.environ` / `os.getenv` outside `src/askai/config/`.**
- **No module-level mutable collector** anywhere — no list, dict, set, `defaultdict`, `deque` or
  `Counter` at module scope. Degradations travel on the result value.
- **No reader-affecting constant as a code literal** in `compile/`, `execute/` or `assemble/`. Use
  `rules().value(...)`. An AST scan watches those three packages.
- **No reader-facing string outside `messages/`**, and no Arabic-script literal over one character
  outside the message YAML.
- **No composer builds a numeric string** except through `assemble/format.py`, and no module in
  `assemble/`, `narrate/` or `respond/` may name a `FormatMode` — use `Placement.mode_for(role)`.
- **A module writes only tables it owns** per `TABLE_OWNERS` in `adapters/store/provision.py`.
- **A model-client import on the answer path fails a scan.** Reach the model through `ModelPort`.
- ruff has `BLE`/`E722` on, broad-except permitted only under `adapters/**`.

### How the work has been running, and it works

One agent per story, launched in parallel, each **fenced to its own files** — its own package and
its own new test file, never an existing one. No agent may touch `pyproject.toml` or `uv.lock`; a
four-way lockfile conflict costs more than it saves, so an agent needing a dependency stops and
asks. Stories are taken straight from `_bmad-output/planning-artifacts/epics.md` — the acceptance
criteria are the spec, with no separate spec file. Commit each story as it lands, explicit paths
only, never `git add -A` while other agents are writing.

### Next, in priority order

1. **Stories 2.3 + 2.4 + 2.5 batched** — the resolution ladder. Story 2.13 measured trigram
   retrieval at **21.4% recall@1 on paraphrases**, and found that where a wrong candidate outranked
   the right one its median score was 0.831 against a derived floor of 0.838. No threshold separates
   right from wrong, so the discriminator is demonstrated necessary rather than assumed.
2. **1.18** foreclosure tests.
3. **A review pass** — 18 of the 20 stories shipped without the adversarial review that caught
   `Percent - Percent` returning the wrong unit on a fully tested, fully typed function.
4. Breadth: Epics 3, 4, 5.

### Open decisions that need a person

- **`agreed_by` is UNRECORDED.** All 187 non-rejected rules are agreed as of 2026-09-16, but no
  approver was named. Story 10.2 has nothing to record until someone is.
- **Analyst prose has no table.** Ingest counts 1,031 analyses and stores none, because Story 1.8
  says load them and Story 1.6 creates no table for them. Epic 6 cannot start.
- **21 details publish text, not numbers** (`"Tier 1"`, `"ناشئة"`). They answer *absent* today.
  `detail.value_type_id` is the natural fix.
- **Three documents disagree with the code** — the spine's response `spec` block lacks
  `spec_version`, R-174's Arabic plural rule is wrong from 100 upward, and AD-13 says vectors live
  in the read model while AD-20 and Story 2.1 say a separate file.
- **`docs/RULES.md`** still shows `proposed` on every rule and argues the pre-agreement position;
  §5 carries a dated note saying so. It needs the catalogue's owner, not a find-and-replace.

`_bmad-output/implementation-artifacts/deferred-work.md` carries the longer ledger.

### Deployed and verified on the VM — 2026-09-16

It runs there. `POST /api/ask` returned `Inflation was 2.6 % in April 2026.` with a
resolving `source_ref`, `resolved_period` 2026-04 against a `today` of 2026-09-16 — so
FR-8's "most recent actual at or before today" is working on real data, not the most
recent row — and `stale: false` after a refresh of 8,985 rows in 0.65s.

**The preflight passes on that filesystem**: WAL active with both sidecars, a reader
unblocked by a writer, an index file retired while its generation was still served, and a
row surviving a full close and reopen. The atomic-refresh design holds where it will run.

The sequence, which is also the deployment order:

```
export RUNTIME_NETWORK=kap_shared_network      # where vllm lives
export ASKAI_EXPORT_DIR=~/askAI-api/data       # the export ROOT, not data/cms
docker compose run --rm askai-api python -m askai.adapters.store provision
docker compose run --rm askai-api python -m askai.refresh /data
docker compose up -d askai-api                 # localhost:17900
```

Three bugs surfaced in the first hour there, none of them visible from a developer
machine: no operator-facing way to create the estate, a compose mount that would have
silently dropped the loose export files, and a serving entry point that did not exist.
Deploy early on anything else built here.
