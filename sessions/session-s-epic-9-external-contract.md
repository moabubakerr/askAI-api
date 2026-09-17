# Session S — settle the external contract, and clear Epic 9's four failures

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**This is now reader-visible.** It was a suite failure; as of the 2026-09-17 deployment it is
something the frontend renders. A real response from the VM, to a request with
`sources: ["approved","external"]`:

```
packages[0]  provenance: approved   kind: clarification
packages[1]  provenance: external   kind: refusal
             "The external source could not be reached, so nothing from it is included here."
             degradation: "no external agent is configured in this build"
```

No external agent is configured, so every Combined request appends a second package saying so.
**Interim workaround for the frontend, not a fix:** send `sources: ["approved"]` until this lands.

## The defect: two models of the external answer are live at once

**The old model** — the third party's answer is an `AnswerPackage` beside the approved one.
`api/ask.py:_packages()` appends `external_package(...)` whenever the admission includes `EXTERNAL`;
`PACKAGE_ORDER` expects it in the list.

**The new model (Story 9.7)** — it is a parallel type. `Answered` says so outright, *"two answers,
in two fields of two types"*, and `ExternalAnswer` deliberately has no `to_package`, `as_package` or
`merge`, with a test at `tests/test_epic9_external_agent.py:604` asserting those conversions do not
exist.

9.7 added the new model and never removed the old one, so external content is emitted **twice**:
once inside `packages`, once in the `external` block. Three of the four failures are this one
defect:

| Test | File:line |
| --- | --- |
| `test_an_unwired_deployment_states_the_gap_rather_than_narrowing_the_selection` | `test_epic9_external_agent.py:423` |
| `test_combined_returns_two_answers_approved_first_each_with_its_own_provenance` | `:628` |
| `test_the_external_answer_never_stands_in_for_an_approved_refusal` | `:647` |

And two test files demand opposite contracts for `BOTH`:

- `test_epic9_external_agent.py:628` — `packages == [APPROVED]` (**failing**)
- `test_epic9_admission.py:295` — `packages[1].source is EXTERNAL` (**passing**)

`test_epic9_admission.py` is believed to be the stale one, written before 9.7.

## The decision that blocks it — make this first, and out loud

Composing the approved half only was attempted and **reverted**: it takes the suite from 4 failures
to 19, because it collides with a second deliberate invariant.

- `domain/admission.py:92` — `EXTERNAL_ONLY` means *"Nothing approved is composed"*, so `packages`
  is empty.
- `respond/response.py:47` — *"a response carries at least one package; an empty list says nothing
  about what the engine decided, and every request reaches a decision."*

Under the two-types model both cannot hold for `EXTERNAL_ONLY`. Once the external answer leaves the
package list, nothing is left in it to carry the decision, and every `EXTERNAL_ONLY` path raises.

Two resolutions. **Neither has been chosen.**

1. **Relax the `Response` invariant** so an empty package list is legal exactly when the admission
   excluded `APPROVED`. The decision still travels, in the `external` block, so the invariant's
   reasoning survives — it only has to admit the decision can live outside `packages`. No new
   user-facing text, no bilingual parity work.
2. **Compose an approved-side refusal** for `EXTERNAL_ONLY`, saying the approved layer was not
   consulted by the reader's own selection. Leaves `Response` untouched, but contradicts
   `admission.py`'s *"nothing approved is composed"* and needs a new message id in **both**
   `en.yaml` and `ar.yaml` plus the Epic 10 parity gate.

Record which you chose and why in the commit message. A future session reading `admission.py` and
`response.py` will find them still in tension unless the resolution is written down.

## The fourth failure is separate — and not root-caused

`test_a_dead_third_party_does_not_delay_or_block_the_approved_answer` (`:411`) asserts the whole
request returns in under 3s against a third party that never answers. It measured **20.0026s**.

What is known: `_ExternalCall` reads correctly on inspection — submitted at t=0, `collect()` waits
only the remaining budget, `__exit__` calls `shutdown(wait=False, cancel_futures=True)`; the test
uses a 0.05s budget. The suspiciously exact 20.0026s suggests a 20s timeout somewhere that was
never located. **Do not assume the fault is in `_ExternalCall` on the strength of this note.**

## Own

`api/ask.py` · `respond/` · `domain/admission.py` · `narrate/structured.py:830` (`external_package`)
· `tests/test_epic9_external_agent.py` and `tests/test_epic9_admission.py` — **you may edit both**,
unusually, because settling the contract means one of them is wrong · `corpus/epic-9.yaml`

Not `pyproject.toml`, `uv.lock`, any other existing test file, `execute/` (Session L), `compile/`,
`adapters/index/` (Sessions M and R).

All five gates must pass; see `AGENTS.md`.
