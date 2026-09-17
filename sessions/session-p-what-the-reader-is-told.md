# Session P — stop showing readers identifiers, and make a clarification choosable

Read `AGENTS.md` first (house rules, VM facts, deployment order, build state). This brief adds only
what is specific.

**Measured on the deployed VM, 2026-09-17**, after the ladder was wired (`b33a831`) and the
execution shapes landed (`3c945e6`). Everything below is a quote from a real response.

## 1. Detail ids are reaching readers, in four composers

```
What does inflation mean?
 -> e4293295-fb43-46b0-7ac5-08dec461c23d: The increase in the general level of prices...

What is Qatar's obesity rate?
 -> No definition is published for 6825244a-5e9b-428e-85cf-08ddb7179f3f.

How much did Qatar's Real GDP grow in 2025 compared with 2024?
 -> Which period do you mean for fc6dccb5-e101-48bd-6a30-08dea2389ab1?

What is the sector contribution to GDP?          (ladder off, fallback path)
 -> Which indicator do you mean: 1d19eeb1-..., 70e23b54-..., 89f1f...?
```

This is **one defect, not four**: a message is rendered with `detail=` given the detail *id* where
the published *name* belongs. `assemble/meta/definitions.py:131` and `:141` pass `detail_name`, and
the caller hands them an id. The clarification path is `compile/binder.py:232` ->
`narrate/structured.py:_candidates`, whose fallback returns the `Unbound` particulars -- which are
ids by construction.

The house rule is already written down and holds here: ids belong in the record and the corpus,
never in a sentence a reader reads. **Keep them in the particulars and in the spec block on the
wire** -- the corpus and the record want them. It is only the composed sentence that must not
carry one.

Start by finding where `detail_name` is resolved. One fix probably closes all four.

## 2. A clarification a reader cannot act on

With the ladder on, the clarification names real surfaces rather than ids -- and they are identical:

```
Which indicator do you mean: Sector Exports, Sector Exports, Sector Exports?
```

Measured against the real export: **20 published names are shared by more than one detail**;
`sector contribution to gdp` is shared by **8**, `sector exports` by 4, `number of jobs in the
sector` by 3. The codebase puts the general figure at 257 of 320. Three details named identically
once normalised:

```
342a4e73...  en='Number of Jobs in the Sector'
dc8a5197...  en='Number of Jobs in the sector'
f623f0e1...  en='Number of Jobs in the Sector'
```

So the commonest thing this engine says is a question the reader cannot answer. **Offering the name
is not enough; the options need a discriminator** -- the sector, the owning entity, the unit,
whatever actually separates them in the export. `CataloguePort` is deliberately narrow and holds
none of that, so decide where it comes from and say why in the module docstring:

- `ports/resolution.py`'s `CandidateFacts` already carries structural facts for stage 2. If the
  discriminating fact is there, the clarification is a rendering change.
- `ports/groups.py` (`ReadModelGroups`) knows sector and owner. Reaching it from `narrate/` is a
  larger decision -- take it deliberately, not by reflex.

Whatever you choose, the sentence a reader reads must let them pick one. `clarify.which_indicator`
takes `{options}`; what goes in it is this session's real question.

## 3. `clarify.which_period` has the same shape

```
Which period do you mean for fc6dccb5-...?
```

Same id problem, and it appears on `e3-005`, `e3-006` and `e3-013` -- comparison questions that
should be answered, not clarified. **The period clarification itself may be Session L's bug**
rather than yours; fix the wording here and leave the binding to L. Say in your report which of the
two you think it is.

## Verify like this, not with the suite

The suite is green -- 2,382 passing -- and sees none of the above, because nothing asserts on the
composed sentence. Assert on element text and on `reason`, and add a guard that no reader-facing
string in any response matches a UUID pattern. That guard is the durable part of this session.

## Own

`assemble/meta/definitions.py` · `narrate/structured.py` (the clarification and definition
composers) · `narrate/clarify.py` · `messages/data/en.yaml` and `ar.yaml` (both, batched at the end,
Arabic reviewed by a native speaker) · `tests/test_reader_facing_text.py` (new, all your tests)

Not `pyproject.toml`, `uv.lock`, any existing test file, `execute/` (Session L), `compile/binder.py`
beyond line 232, or `adapters/index/`.

All five gates must pass; see `AGENTS.md`.
