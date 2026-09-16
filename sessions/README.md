# Parallel session briefs

Five Claude Code sessions, each owning one epic and one package. The fences below are what make
that safe — two sessions editing the same file is the only failure mode that actually costs time.

Start each one in its own terminal:

```bash
cd c:\projects\askAI\askai-api
claude
```

Then: **"Read `AGENTS.md` and `sessions/<your-brief>.md`, then begin."**

`AGENTS.md` carries the house rules, the VM facts and the build state. Each brief below carries only
what is specific to that session. Read both.

## The split

| Session | Brief | Epic | Owns exclusively |
|---|---|---|---|
| **A** | `session-a-epic-2-resolution.md` | 2 — resolution and refusal | `compile/resolve/`, `adapters/index/` |
| **B** | `session-b-epic-3-series-and-change.md` | 3 — series, change, targets | `assemble/change/` |
| **C** | `session-c-epic-4-countries.md` | 4 — comparisons, ranks, spread | `assemble/compare/` |
| **D** | `session-d-epic-5-groups-and-metadata.md` | 5 — groups, metadata, overview | `assemble/meta/` |
| **E** | `session-e-review-and-epic-1.md` | 1 — finish and review | `tests/` review additions |

**Session A is the one that matters most.** Epics 3, 4 and 5 can build composers, but until the
resolution ladder lands nobody can ask them a real question — retrieval gets 21.4% recall@1 on
paraphrased questions today. If you only run one session, run A.

## The fences — these are not suggestions

- **Nobody edits `pyproject.toml` or `uv.lock`.** A four-way lockfile conflict costs more than any
  dependency saves. A session needing one stops and asks the human.
- **Nobody edits another session's package**, and nobody edits an existing test file. New test file
  per story, named for the story.
- **Epics 3, 4 and 5 all add composers to `assemble/`.** That is the one real collision point, and
  the subpackages above are how it is avoided. Do not put a composer directly in `assemble/`.
- **Shared, append-only, one new file each — never edit another's:** `src/askai/rules/data/*.yaml`
  (one new file per concern), `corpus/epic-N.yaml` (your epic's file only).
- **`src/askai/messages/data/en.yaml` and `ar.yaml` are genuinely shared.** Adding a message id
  means editing both, and two sessions doing that at once will conflict. Add ids in one batch at the
  end of a story rather than as you go, and expect to reconcile. Both files must carry identical ids
  or startup fails.

## Committing

Commit each story as it lands, **explicit paths only** — never `git add -A` while other sessions are
writing. Pull before you commit. All five gates green before any commit:

```
uv run lint-imports
uv run mypy --strict src/askai tests
uv run ruff check .
uv run pytest
uv run python tests/corpus_runner.py
```

If a gate fails in a file you do not own, it belongs to another session. Do not fix it. Say so.

## Before you start: generate your epic context

Story 1.1's epic context file made Epic 1's first wave fast, because agents stopped re-deriving the
same background. Each session should generate its own first:

> Read `_bmad-output/planning-artifacts/epics.md` for Epic N and `docs/`, and write
> `_bmad-output/implementation-artifacts/epic-N-context.md` — goal, stories, requirements,
> technical decisions, cross-story dependencies. 800–1500 tokens. Follow the shape of
> `epic-1-context.md`.

Then hand that file to every agent you spawn instead of the raw planning documents.

## Decisions blocking work — escalate, do not guess

- **Analyst prose has no table.** Blocks all 14 stories of Epic 6. Story 1.8 says load the 1,031
  analyses; Story 1.6 creates no table for them. Needs a DDL change and a schema-version bump.
- **`agreed_by` is unrecorded.** All 187 non-rejected rules are agreed as of 2026-09-16, but nobody
  is named. Blocks Story 10.2.
- **Story 2.12** is decision-gated on FR-51 and has no option-specific criteria. Do not start it.
- **Story 1.7** needs the target VM.
