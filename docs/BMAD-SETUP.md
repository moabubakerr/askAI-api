# Using BMAD in this repository

BMAD 6.12.0 is installed in the reference tree. **Install it here rather than copying it** —
`_bmad/config.toml` is installer-managed, carries `project_name`, and is regenerated on every
install, so a copied folder would both misname this project and be overwritten.

## 1. Install

Run the BMAD installer with this repository as the project root. Your previous answers are
remembered as defaults, so most of it is confirmation.

| Answer | Value |
|---|---|
| project name | `askai-api` |
| user name | `Mammohamed` |
| communication / document language | English |
| output folder | `_bmad-output` (default) |

**Modules to install:**

| Module | Install? | Why |
|---|---|---|
| **core** | yes | required |
| **bmm** | yes | PM, analyst, architect, dev, PRD, epics, stories, sprint planning |
| **tea** | **yes — heavily used here** | Murat owns the corpus, the retrieval evaluation, ATDD, CI gates and traceability |
| bmb | optional | only if you build custom skills |
| cis | skip | creative-ideation agents; nothing in this plan needs them |

Nothing from the old `_bmad-output/` should be carried over. The artifacts worth keeping are
already in `docs/`.

## 2. The configuration that matters most

BMAD skills read `persistent_facts` from per-skill override files, and those files are **never
touched by the installer**. This is how you make every agent automatically aware of the spine and
the rules instead of hoping each one reads them.

Create these under `_bmad/custom/`:

```toml
# _bmad/custom/bmad-architecture.toml
[workflow]
persistent_facts = [
  "file:{project-root}/docs/ARCHITECTURE-SPINE.md",
  "The spine's ADs are binding. Contradicting one is a spine change, not a local decision.",
]
```

```toml
# _bmad/custom/bmad-create-epics-and-stories.toml
[workflow]
persistent_facts = [
  "file:{project-root}/docs/ARCHITECTURE-SPINE.md",
  "file:{project-root}/docs/RULES.md",
  "Acceptance criteria come from RULES.md. A story whose behaviour no rule covers is a gap to raise, not a decision to make.",
]
```

```toml
# _bmad/custom/bmad-build.toml
[workflow]
persistent_facts = [
  "file:{project-root}/docs/ARCHITECTURE-SPINE.md",
  "Every figure traces to an approved published row, or it does not appear.",
  "Corpus entries assert on the bound query, never on prose.",
  "import-linter runs in CI from the first commit; a dependency violation fails the build.",
]
```

Same pattern for `bmad-testarch-*` skills, pointing at `RULES.md` and `PRD.md` §7.

**Do not** put the whole document set into every skill — `persistent_facts` is loaded on every
activation, so point each skill at what it actually needs.

## 3. `AGENTS.md`

Run `bmad-project-context` once the repo has code. It writes an `AGENTS.md` block that **every**
skill sees automatically, without per-skill configuration — the right home for facts like "run
`python`, not `python3`" and "the CSV export in `data/` is the source of truth."

Until there is code, `README.md` carries that job.

## 4. Where things land

| Path | Contents |
|---|---|
| `_bmad-output/planning-artifacts/` | PRDs, architecture runs, epics, stories, sprint status |
| `_bmad-output/implementation-artifacts/` | build records |
| `_bmad-output/test-artifacts/` | test design, reviews, traceability |
| `docs/` | the durable documents — kept in the repo, read by humans and agents |

Keep the distinction: `_bmad-output/` is **working state** for a run; `docs/` is what the project
stands on. When a run produces something durable, copy it into `docs/`, as was done for the
PRD, the spine and the rules.

## 5. Which agents this project actually uses

| Agent | Role here |
|---|---|
| **Murat** (`bmad-tea`) | the most-used agent on this project — corpus, retrieval evaluation, ATDD, CI, traceability, NFR evidence |
| **Mary** (`bmad-agent-analyst`) | the rule catalogue: close its gaps, add status, take it to whoever agrees it |
| **John** (`bmad-agent-pm`) | epics and stories, and holding scope across the capability groups |
| **Amelia** (`bmad-agent-dev`) | implementation, story by story |
| **Winston** (`bmad-agent-architect`) | **not needed now.** The spine is final; he returns only to change an AD |
| **Sally** (`bmad-agent-ux-designer`) | not needed — the SPA is out of scope |

`bmad-correct-course` if scope moves materially. `bmad-retrospective` per epic.

## 6. One caveat about this machine

`uv` is not installed, so the `uv run ...` invocations in the skills fail. `python` (3.11) works and
the scripts run fine under it. Either install `uv`, or expect each skill to fall back — which they
all do, but it costs a failed call every time. **Installing `uv` is the cheaper fix.**
