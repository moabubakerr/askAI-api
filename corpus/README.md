# The question corpus

Each `corpus/*.yaml` file holds a **list of mappings**; each mapping is one corpus entry. The
runner is `tests/corpus_runner.py` — run it directly (`uv run python tests/corpus_runner.py`) or
let `pytest` exercise it.

## The entry shape is provisional

**Nothing here is a contract yet.** `QuerySpec` does not exist until Story 1.11, so there is
nothing for an entry to assert against. Until then the runner checks one thing only — that every
file parses to a list of mappings — and reports how many entries it collected.

Do not read the placeholder file as a schema. The real entry shape arrives with 1.11 (the
`QuerySpec` assertion) and 1.13 (typed elements), at which point this README states it. Per the
spine's testing convention, entries will assert on the `QuerySpec` and the typed elements, and
never on prose.

`scaffold.yaml` is deliberately empty: it proves the loader runs green against a valid corpus with
zero entries, so later epics add entries rather than infrastructure.
