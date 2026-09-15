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
