"""Story 1.17 -- typed degradations, counted and carried on the result (AD-15).

Four claims are under test, and each is asserted as a structural property rather than as
a happy path:

1. the taxonomy is **closed** -- every kind produced anywhere under ``src/askai/`` is a
   declared member, proven by scanning the tree rather than by listing them here;
2. a degradation **travels on the result value** -- ``assemble/`` can be exercised with
   no shared mutable state, and nothing under ``src/askai/`` holds a collector;
3. each kind is **counted**, and the count of a chain equals the sum of its parts;
4. a failure is **distinguishable from absence** -- ``Failed`` and ``Absent`` are
   different types and a match over them cannot silently conflate the two.
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path
from typing import Final

import pytest

from askai.assemble.provenance import Layer, ProvenanceFailure, admit, admit_all
from askai.domain.degradation import Degradation
from askai.domain.element import Element, ElementClass
from askai.observability.degradations import (
    NO_DEGRADATIONS,
    Absent,
    Carried,
    DegradationKind,
    Failed,
    Found,
    Outcome,
    Tally,
    UnknownDegradationKind,
    classify,
    degradations_of,
    degrade,
    gather,
    is_known_kind,
)
from askai.ports.provenance_source import SourceCatalogue

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"


# ------------------------------------------------------------------ the closed set


def test_the_taxonomy_is_a_closed_set_of_distinct_values() -> None:
    values = [kind.value for kind in DegradationKind]
    assert len(set(values)) == len(values)
    assert all(value == value.lower() and " " not in value for value in values), (
        "kinds are machine identifiers, not prose; a kind with a capital or a space is "
        "a message that wandered into the taxonomy"
    )
    assert all(is_known_kind(value) for value in values)


def test_the_kind_assemble_already_produces_is_a_member() -> None:
    """The existing producer keeps working; its kind was not left outside the set."""
    assert is_known_kind(ProvenanceFailure.UNRESOLVED_SOURCE_REF.value)
    assert (
        classify(ProvenanceFailure.UNRESOLVED_SOURCE_REF.value)
        is DegradationKind.UNRESOLVED_SOURCE_REF
    )


def test_classify_rejects_a_kind_nobody_declared() -> None:
    """The set is closed by refusal, not by an `other` bucket that lets it drift open."""
    with pytest.raises(UnknownDegradationKind, match="closed"):
        classify("something_went_wrong")


def test_classify_returns_the_member_for_a_declared_kind() -> None:
    assert classify("unresolved_source_ref") is DegradationKind.UNRESOLVED_SOURCE_REF


def _degradation_kinds_constructed_under_src() -> list[tuple[str, int, str]]:
    """Every literal ``kind=`` a ``Degradation(...)`` or ``degrade(...)`` is built with.

    An AST scan rather than a grep: a string spelled in a comment or a docstring is not
    a construction, and a scan that could not tell the difference would either miss a
    producer or fail on prose.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (
                callee.id
                if isinstance(callee, ast.Name)
                else callee.attr
                if isinstance(callee, ast.Attribute)
                else ""
            )
            if name not in {"Degradation", "degrade"}:
                continue
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            for value in _kind_arguments(node):
                found.append((relative, node.lineno, value))
    return found


def _kind_arguments(node: ast.Call) -> list[str]:
    """The kind a construction names, resolved through the two spellings in use.

    ``Degradation(kind=X)`` and ``degrade(DegradationKind.X, ...)`` and the enum-valued
    ``kind=SomeEnum.MEMBER.value`` all resolve to a string; anything dynamic resolves to
    nothing and is skipped, because the scan asserts about what a reviewer can read.
    """
    candidates: list[ast.expr] = [
        keyword.value for keyword in node.keywords if keyword.arg == "kind"
    ]
    if node.args:
        candidates.append(node.args[0])
    values: list[str] = []
    for candidate in candidates:
        expression = candidate
        # `SomeEnum.MEMBER.value` -> `SomeEnum.MEMBER`
        if isinstance(expression, ast.Attribute) and expression.attr == "value":
            expression = expression.value
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            values.append(expression.value)
        elif isinstance(expression, ast.Attribute):
            member = getattr(DegradationKind, expression.attr, None)
            # An enum member of *any* enum resolves by name here, which is the point:
            # assemble's local ProvenanceFailure.UNRESOLVED_SOURCE_REF must correspond
            # to a DegradationKind member of the same name, or this reports it.
            values.append(member.value if member is not None else f"<{expression.attr}>")
    return values


def test_every_kind_produced_under_src_is_in_the_taxonomy() -> None:
    """The closure test. A new producer adds its member or fails the build."""
    produced = _degradation_kinds_constructed_under_src()
    assert produced, "the scan found no degradation producers; it has stopped working"
    offenders = [
        f"{path}:{line} kind={value!r}"
        for path, line, value in produced
        if not is_known_kind(value)
    ]
    assert not offenders, (
        "kinds outside DegradationKind: "
        + ", ".join(offenders)
        + " -- add the member to askai.observability.degradations, where a reviewer sees it"
    )


def test_degrade_builds_a_member_kinded_degradation() -> None:
    degradation = degrade(DegradationKind.MODEL_UNAVAILABLE, "narrate", "budget exceeded")
    assert degradation == Degradation(
        kind="model_unavailable", where="narrate", detail="budget exceeded"
    )
    assert classify(degradation.kind) is DegradationKind.MODEL_UNAVAILABLE


@pytest.mark.parametrize(("where", "detail"), [("", "d"), ("  ", "d"), ("execute", " ")])
def test_a_degradation_without_an_address_or_a_detail_is_refused(where: str, detail: str) -> None:
    """AD-15 wants an address and enough detail to reconstruct the decision."""
    with pytest.raises(ValueError, match="degradation"):
        degrade(DegradationKind.RULE_UNAVAILABLE, where, detail)


# ------------------------------------------------------------------- the counting


def test_a_tally_counts_each_kind() -> None:
    tally = Tally.of(
        [
            degrade(DegradationKind.GUARD_DISCARD, "narrate", "unparseable"),
            degrade(DegradationKind.GUARD_DISCARD, "narrate", "off-source figure"),
            degrade(DegradationKind.ANALYSIS_ABSENT, "execute", "no P04 row"),
        ]
    )
    assert tally.count(DegradationKind.GUARD_DISCARD) == 2
    assert tally.count(DegradationKind.ANALYSIS_ABSENT) == 1
    assert tally.count(DegradationKind.MODEL_UNAVAILABLE) == 0
    assert tally.total == 3
    assert tally.kinds == (DegradationKind.ANALYSIS_ABSENT, DegradationKind.GUARD_DISCARD)


def test_a_tally_of_nothing_is_empty_and_falsey() -> None:
    assert Tally.of([]) == NO_DEGRADATIONS
    assert not NO_DEGRADATIONS
    assert NO_DEGRADATIONS.total == 0
    assert NO_DEGRADATIONS.as_mapping() == {}


def test_a_kind_that_did_not_happen_is_absent_rather_than_zero() -> None:
    """The tally says what happened; the enum already says what could."""
    tally = Tally.of([degrade(DegradationKind.INGEST_REJECTION, "refresh", "bad period")])
    assert DegradationKind.MODEL_UNAVAILABLE not in tally.as_mapping()
    assert tally.count(DegradationKind.MODEL_UNAVAILABLE) == 0


def test_tallies_add_without_anything_shared() -> None:
    left = Tally.of([degrade(DegradationKind.GUARD_DISCARD, "narrate", "a")])
    right = Tally.of(
        [
            degrade(DegradationKind.GUARD_DISCARD, "narrate", "b"),
            degrade(DegradationKind.MODEL_UNAVAILABLE, "narrate", "c"),
        ]
    )
    combined = left + right
    assert combined.count(DegradationKind.GUARD_DISCARD) == 2
    assert combined.count(DegradationKind.MODEL_UNAVAILABLE) == 1
    assert combined.total == left.total + right.total
    # The operands are untouched -- addition produces a value, it does not accumulate.
    assert left.total == 1
    assert right.total == 2


def test_two_tallies_of_the_same_failures_are_equal_however_they_were_ordered() -> None:
    first = Tally.of(
        [
            degrade(DegradationKind.GUARD_DISCARD, "narrate", "a"),
            degrade(DegradationKind.ANALYSIS_ABSENT, "execute", "b"),
        ]
    )
    second = Tally.of(
        [
            degrade(DegradationKind.ANALYSIS_ABSENT, "execute", "b"),
            degrade(DegradationKind.GUARD_DISCARD, "narrate", "a"),
        ]
    )
    assert first == second
    assert hash(first) == hash(second)


def test_a_tally_refuses_a_kind_outside_the_taxonomy() -> None:
    with pytest.raises(UnknownDegradationKind):
        Tally.of([Degradation(kind="mystery", where="execute", detail="?")])


@pytest.mark.parametrize(
    "counts",
    [
        ((DegradationKind.GUARD_DISCARD, 0),),
        ((DegradationKind.GUARD_DISCARD, 1), (DegradationKind.ANALYSIS_ABSENT, 1)),
        ((DegradationKind.GUARD_DISCARD, 1), (DegradationKind.GUARD_DISCARD, 1)),
    ],
    ids=["zero count", "out of order", "repeated kind"],
)
def test_a_malformed_tally_cannot_be_built(counts: tuple[tuple[DegradationKind, int], ...]) -> None:
    with pytest.raises(ValueError, match="tally|absent"):
        Tally(counts=counts)


# -------------------------------------------------------------------- the carrying


def test_a_carried_result_holds_its_value_and_its_failures_together() -> None:
    carried = Carried(value=7, degradations=(degrade(DegradationKind.ANALYSIS_ABSENT, "x", "y"),))
    assert carried.value == 7
    assert not carried.clean
    assert carried.tally.count(DegradationKind.ANALYSIS_ABSENT) == 1


def test_a_clean_result_carries_nothing() -> None:
    carried: Carried[str] = Carried(value="ok")
    assert carried.clean
    assert carried.tally == NO_DEGRADATIONS


def test_a_chain_accumulates_by_returning_rather_than_by_collecting() -> None:
    """The shape AD-15 asks for: each step hands its failures to its caller."""

    def first(value: int) -> Carried[int]:
        missing = degrade(DegradationKind.RULE_UNAVAILABLE, "validate", "R-X missing")
        return Carried(value=value * 2, degradations=(missing,))

    def second(value: int) -> Carried[str]:
        return Carried(
            value=str(value),
            degradations=(degrade(DegradationKind.GUARD_DISCARD, "narrate", "off-source"),),
        )

    result = Carried(value=3).then(first).then(second)
    assert result.value == "6"
    assert result.tally.total == 2
    assert result.tally.kinds == (DegradationKind.GUARD_DISCARD, DegradationKind.RULE_UNAVAILABLE)


def test_map_keeps_the_failures_collected_so_far() -> None:
    carried = Carried(value=2, degradations=(degrade(DegradationKind.GUARD_DISCARD, "n", "d"),))
    assert carried.map(lambda value: value + 1).value == 3
    assert carried.map(lambda value: value + 1).tally.total == 1


def test_also_adds_without_mutating_the_original() -> None:
    original: Carried[int] = Carried(value=1)
    extended = original.also(degrade(DegradationKind.ADAPTER_UNAVAILABLE, "adapters", "timeout"))
    assert original.clean
    assert extended.tally.count(DegradationKind.ADAPTER_UNAVAILABLE) == 1


def test_gathering_many_results_loses_no_failure() -> None:
    parts = [
        Carried(
            value=index,
            degradations=(
                degrade(DegradationKind.INGEST_REJECTION, "refresh", f"row {index}"),
            ),
        )
        for index in range(5)
    ]
    gathered = gather(parts)
    assert gathered.value == (0, 1, 2, 3, 4)
    assert gathered.tally.total == sum(part.tally.total for part in parts) == 5


def test_a_carried_result_refuses_a_kind_outside_the_taxonomy() -> None:
    with pytest.raises(UnknownDegradationKind):
        Carried(value=1, degradations=(Degradation(kind="oops", where="x", detail="y"),))


# ----------------------------------------------------- failure is not absence


def test_absence_and_failure_are_different_types() -> None:
    """Findings 23, 128 and 150: an error must never render as `no approved figures`."""
    absent = Absent(reason="no approved figure for that period")
    failed = Failed(degradations=(degrade(DegradationKind.ADAPTER_UNAVAILABLE, "adapters", "io"),))
    assert not isinstance(absent, Failed)
    assert not isinstance(failed, Absent)
    assert degradations_of(absent) == ()
    assert degradations_of(failed) == failed.degradations
    assert failed.tally.count(DegradationKind.ADAPTER_UNAVAILABLE) == 1


def test_a_failure_cannot_be_built_without_a_degradation() -> None:
    """Otherwise it would be an absence wearing a different name."""
    with pytest.raises(ValueError, match="at least one degradation"):
        Failed(degradations=())


def test_an_absence_must_state_why_it_is_empty() -> None:
    with pytest.raises(ValueError, match="absence"):
        Absent(reason="   ")


def test_a_match_over_an_outcome_must_name_all_three_states() -> None:
    """Exhaustiveness is what forecloses the conflation; this drives all three arms."""

    def render(outcome: Outcome[str]) -> str:
        match outcome:
            case Found(value=value):
                return value
            case Absent(reason=reason):
                return f"none: {reason}"
            case Failed(degradations=degradations):
                return f"failed: {len(degradations)}"

    assert render(Found(value="2.5%")) == "2.5%"
    assert render(Absent(reason="not published")) == "none: not published"
    assert (
        render(Failed(degradations=(degrade(DegradationKind.MODEL_UNAVAILABLE, "narrate", "d"),)))
        == "failed: 1"
    )


# -------------------------------------------- no ambient collector, no shared state


def test_nothing_under_src_holds_a_degradation_collector() -> None:
    """AD-15's negative claim, re-asserted from this story's side.

    ``tests/test_domain_invariants.py`` scans for module-level mutable state in general;
    this one is narrower and about naming -- a module-level object that *sounds* like a
    place degradations go is the shape the rule exists to prevent, whether or not it is
    a list literal.
    """
    suspicious: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                lowered = target.id.lower()
                if "degradation" not in lowered and "tally" not in lowered:
                    continue
                if isinstance(node, ast.Assign | ast.AnnAssign) and _is_collector(node.value):
                    relative = path.relative_to(PROJECT_ROOT).as_posix()
                    suspicious.append(f"{relative}:{node.lineno} {target.id}")
    assert not suspicious, "ambient degradation collector: " + ", ".join(suspicious)


def _is_collector(value: ast.expr | None) -> bool:
    if isinstance(value, ast.List | ast.Dict | ast.Set):
        return True
    if isinstance(value, ast.Call):
        callee = value.func
        name = (
            callee.id
            if isinstance(callee, ast.Name)
            else callee.attr
            if isinstance(callee, ast.Attribute)
            else ""
        )
        return name in {"list", "dict", "set", "defaultdict", "Counter", "deque"}
    return False


def test_the_collector_scan_would_catch_one() -> None:
    """A scan nobody has seen fail proves nothing."""
    assert _is_collector(ast.parse("x = []").body[0].value)  # type: ignore[attr-defined]
    assert _is_collector(ast.parse("x = collections.Counter()").body[0].value)  # type: ignore[attr-defined]
    assert not _is_collector(ast.parse("x = ()").body[0].value)  # type: ignore[attr-defined]


class _Sources:
    """A catalogue that resolves exactly the refs it was handed. No IO, no state shared."""

    def __init__(self, known: frozenset[str]) -> None:
        self._known = known

    def resolves(self, source_ref: str) -> bool:
        return source_ref in self._known


def test_assemble_is_exercisable_in_isolation_with_no_shared_mutable_state() -> None:
    """AC: the module's degradations come back on the result, twice, identically.

    Two runs over the same input in the same process produce the same result. With an
    ambient collector the second run would see the first's failures; that this holds is
    the isolation claim, asserted rather than asserted-about.
    """
    sources: SourceCatalogue = _Sources(frozenset({"datapoint:known"}))
    elements = (
        Element("2.5%", ElementClass.MEASURED, "datapoint:known"),
        Element("3.1%", ElementClass.MEASURED, "datapoint:missing"),
    )

    first = admit_all(elements, sources)
    second = admit_all(elements, sources)

    assert first == second
    assert len(first.elements) == 1
    assert Tally.of(first.degradations).count(DegradationKind.UNRESOLVED_SOURCE_REF) == 1
    assert Tally.of(second.degradations).count(DegradationKind.UNRESOLVED_SOURCE_REF) == 1
    assert len(first.elements) + len(first.degradations) == len(elements)


def test_the_degradation_assemble_produces_carries_its_layer_and_a_member_kind() -> None:
    sources: SourceCatalogue = _Sources(frozenset())
    outcome = admit(Element("2.5%", ElementClass.MEASURED, "datapoint:gone"), sources)
    degradation = getattr(outcome, "degradation", None)
    assert isinstance(degradation, Degradation)
    assert classify(degradation.kind) is DegradationKind.UNRESOLVED_SOURCE_REF
    assert degradation.where == Layer.ASSEMBLE.value
    assert "datapoint:gone" in degradation.detail


def test_assemble_imports_no_contextvar_and_no_module_state() -> None:
    module = importlib.import_module("askai.assemble.provenance")
    source = Path(str(module.__file__)).read_text(encoding="utf-8")
    assert "contextvars" not in source
    assert "global " not in source


# ---------------------------------------------- the lint rule AD-15 asks for


def test_broad_exception_handling_is_enforced_by_lint() -> None:
    """AC: *no bare broad exception handling outside adapter boundaries, by lint*.

    Asserted against the configuration rather than by running ruff, so the gate is that
    the rule is *selected* -- a rule that is on and passing and a rule that was never
    selected look identical in a green build otherwise.
    """
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]
    selected = set(lint["extend-select"])
    assert {"BLE", "E722"} <= selected, (
        "AD-15's `no bare except Exception` is enforced by ruff BLE and E722; "
        f"selected rules are {sorted(selected)}"
    )
    ignores = lint["per-file-ignores"]
    assert list(ignores) == ["src/askai/adapters/**/*.py"], (
        "the broad-handling exemption is scoped to adapter boundaries and nowhere else; "
        f"exempted paths are {sorted(ignores)}"
    )
    assert ignores["src/askai/adapters/**/*.py"] == ["BLE001"]
