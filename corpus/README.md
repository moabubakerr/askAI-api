# The question corpus

Each `corpus/*.yaml` file holds a **list of mappings**; each mapping is one corpus entry. The
runner is `tests/corpus_runner.py` — run it directly (`uv run python tests/corpus_runner.py`) or
let `pytest` exercise it.

## `spec_version` — the one real field

Story 1.2 gives the entry shape its first field that is a contract rather than a placeholder:

```yaml
- spec_version: 1
  # …everything else is still provisional
```

`spec_version` is a monotonic integer identifying the shape of the serialised spec, starting at
`1`. The runner **rejects an entry whose `spec_version` it does not recognise**, naming the file,
the entry index and both versions. That is the point of the field: when the spec shape changes,
entries written against the old shape fail loudly instead of being asserted against a shape that
no longer exists and reported as content failures.

**What exists today**, as of Story 1.2: the field on the in-memory `QuerySpec`
(`askai.domain.spec.SPEC_VERSION`) and this runner's check against
`SUPPORTED_SPEC_VERSIONS`. Nothing serialises a spec yet, so the field reaches no wire format.
It is designed to be carried on the response `spec` block, which arrives with the `POST /api/ask`
contract in Story 1.15, and on the answer record, which arrives in Story 1.16. Until then the
corpus entry is its only written form.

The field is currently **optional**, because the rest of the entry shape is not settled yet and
an entry without one is not yet wrong. It becomes required when 1.11 gives entries something to
assert. A `spec_version` that is present and unrecognised — or not an integer — is a failure
today.

## The rest of the entry shape is still provisional

**Nothing else here is a contract yet.** Nothing compiles to a `QuerySpec` until Story 1.11, so
there is nothing more for an entry to assert against. Until then the runner checks two things —
that every file parses to a list of mappings, and that any declared `spec_version` is one it
knows — and reports how many entries it collected.

Do not read the placeholder file as a schema. The real entry shape arrives with 1.11 (the
`QuerySpec` assertion) and 1.13 (typed elements), at which point this README states it. Per the
spine's testing convention, entries will assert on the `QuerySpec` and the typed elements, and
never on prose.

`scaffold.yaml` is deliberately empty: it proves the loader runs green against a valid corpus with
zero entries, so later epics add entries rather than infrastructure.

---

## Note added with the first seeded entries

**One file per epic — `epic-1.yaml` … `epic-10.yaml`.** Never one shared file: entries are added
per epic, often in parallel, and a shared file is a merge conflict on every story.

The seed entries were written against the measured data (`data/cms/`, read 2026-09-15) and carry
only the fields the provisional shape supports. Nothing here is a schema; 1.11 and 1.13 settle it.

| field | what it is |
|---|---|
| `id` | stable handle, `e<epic>-<nnn>`, so an entry can be cited from a story or a failure |
| `spec_version` | the one real field (above) |
| `question.en` / `question.ar` | the reader's words; `ar` wherever the question is natural in Arabic |
| `today` | pinned explicitly — spec determinism depends on it (AD-17), so it is never a clock read |
| `operation` / `measure` | **only** members of `askai.domain.spec.Operation` and `Measure` |
| `why` | what the entry is evidence for: an epic/story, or a recorded failure (F-001, F-003, …) |
| `expected: refusal` + `refusal_reason` | where the honest answer is a refusal rather than a figure |
| `history` | prior turns, on Epic 7 follow-ups only; history is an input to compile, never a store |
| `source` | the provenance contract, on Epic 9 entries only |

`measure: null` means **no `Measure` member applies** — the question asks for nothing numeric
(a definition, a count of indicators, a capability question). It is not a new enum value, and it
is not the same as an unbound measure.

**Deliberately absent: an assertion surface.** No expected value, period, unit, detail id or
`QuerySpec` fragment appears on any entry, because nothing compiles a question to a `QuerySpec`
yet and a field invented now is a field 1.11 has to rework. The figures that ground each entry
live in its `why`, as prose evidence that the question is answerable from real published data —
not as something the runner checks.

**Every entry is grounded in `data/cms/`.** An entry naming an indicator that does not exist is
worse than no entry. One gap is recorded rather than faked: `P13_Ref_IndicatorPriorityTypes`
defines a `Confidential` priority type, but **no published indicator carries it** (105 `Priority`,
84 blank), so there is no confidential-indicator refusal to ground — `epic-5.yaml` e5-009 asks
about it and expects a refusal that says exactly that.
