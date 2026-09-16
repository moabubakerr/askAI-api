"""Story 1.18 -- one test per failure class the architecture claims to foreclose.

Bucket A of ``docs/FINDINGS-TRIAGE.md`` is 40 recorded failures the spine says are
*unrepresentable* rather than merely forbidden. A claim like that is worth exactly what
a test of it is worth, so each class below is asserted here, once, citing the AD that
makes the claim. These are not instance tests -- ``tests/test_execute.py`` and its
neighbours assert that the shipped behaviour is right. These assert that the *shape of
the code* leaves no room for the failure, and they are written as scans and type
assertions so they keep biting as eighty more stories land.

**Where a class's behaviour ships in a later epic** (AD-10's external view, AD-28's
narration guard), the structural half is asserted now -- the absent conversion function,
the missing constructor, the type that cannot be built -- and the epic that ships the
behaviour adds the behavioural half. That split is the story's own instruction, and each
such test says which half it is.

**One class could not be fully foreclosed, and it is recorded rather than worked
around**: see ``test_a_card_has_only_one_place_to_state_its_period`` and the finding it
cites in ``_bmad-output/implementation-artifacts/deferred-work.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest

from askai.assemble.provenance import Provenance
from askai.assemble.roles import Lens, Placed, Placement, Role
from askai.compile.binding import Binding, BoundBy, CompiledQuestion, Precedence, SpecField
from askai.compile.question import Question
from askai.domain.element import Element, ElementClass
from askai.domain.period import Grain, Period
from askai.domain.scope import CountryScope, National
from askai.domain.spec import (
    Bound,
    Exact,
    Measure,
    Operation,
    PeriodSpec,
    QuerySpec,
    Unbound,
    period_field,
)
from askai.execute.value import Execution, FigureCause, execute_value
from askai.narrate.package import AnswerPackage, PackageKind, PackageSource
from askai.observability.degradations import Absent, Failed, Found
from askai.observability.record import AnswerRecord
from askai.ports.datapoints import DatapointRow, DatapointsPort
from askai.ports.model import Budget, CallSite, ModelCall, ModelPort
from askai.rules import RuleSet, load_rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"

#: Everything a request passes through between the HTTP surface and the response. A
#: package is on this list because a reader-visible defect can originate in it.
ANSWER_PATH = ("api", "compile", "validate", "execute", "assemble", "narrate", "respond")


# --------------------------------------------------------------------------- scanning


def _modules(*packages: str) -> list[Path]:
    return sorted(path for package in packages for path in (PACKAGE_ROOT / package).rglob("*.py"))


def _all_modules() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _where(path: Path, line: int) -> str:
    return f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line}"


def _calls_to(tree: ast.Module, name: str) -> list[int]:
    """Every line constructing *name* -- ``Name(...)`` and ``module.Name(...)`` alike.

    Both spellings, because matching only the bare name would miss the import style that
    a second call site is most likely to be written in.
    """
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        bare = isinstance(callee, ast.Name) and callee.id == name
        qualified = isinstance(callee, ast.Attribute) and callee.attr == name
        if bare or qualified:
            found.append(node.lineno)
    return found


def _construction_sites(name: str, *, within: list[Path] | None = None) -> list[str]:
    return [
        _where(path, line)
        for path in (_all_modules() if within is None else within)
        for line in _calls_to(_parse(path), name)
    ]


def _dataclass_replacements(tree: ast.Module) -> list[int]:
    """Every line calling ``dataclasses.replace``, in both spellings and neither more.

    ``str.replace`` is a different function that happens to share a name, so the bare
    call counts only in a module that imported the dataclass one -- otherwise the scan
    would go red on text handling and be narrowed by whoever hit it first.
    """
    imported_bare = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dataclasses"
        and any(alias.name == "replace" for alias in node.names)
        for node in ast.walk(tree)
    )
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "replace":
            if isinstance(callee.value, ast.Name) and callee.value.id == "dataclasses":
                found.append(node.lineno)
        elif isinstance(callee, ast.Name) and callee.id == "replace" and imported_bare:
            found.append(node.lineno)
    return found


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _annotation(node: ast.expr | None) -> str:
    return "" if node is None else ast.unparse(node)


def _parameter_annotations(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    arguments = function.args
    every = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ]
    return [_annotation(argument.annotation) for argument in every]


# ------------------------------------------------------------------------- fixtures


TODAY = Period("2025").start  # any date; the fetch below never reaches a calendar


class _PublishesNothing:
    """A read model that answers every question with a well-founded nothing.

    Not a mock: the point of the AD-2 test below is that *every* declared operation
    reaches a typed outcome, and a port that raises or returns a sentinel would be
    asserting something about the double rather than about the engine.
    """

    def publishes(self, detail_id: str) -> bool:
        return False

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        return ()

    def row(self, detail_id: str, period: Period, country_id: str | None) -> DatapointRow | None:
        return None


def _bindings(spec: QuerySpec) -> tuple[Binding, ...]:
    made: list[Binding] = []
    for field in SpecField:
        state = getattr(spec, field.value)
        unbound = isinstance(state, Unbound)
        made.append(
            Binding(
                field=field,
                precedence=Precedence.UNBOUND if unbound else Precedence.NAMED_IN_QUESTION,
                bound_by=None if unbound else BoundBy.READER,
            )
        )
    return tuple(made)


def _spec(
    *,
    operation: Operation = Operation.VALUE,
    measure: Measure = Measure.ACTUAL,
    period: PeriodSpec | None = None,
    scope: CountryScope | None = None,
) -> QuerySpec:
    return QuerySpec(
        detail=Bound("detail-1"),
        period=period_field(Exact(Period("2025")) if period is None else period),
        country_scope=Bound(National() if scope is None else scope),
        measure=Bound(measure),
        operation=Bound(operation),
        today=TODAY,
    )


def _provenance(period: str = "2025") -> Provenance:
    return Provenance(
        detail_id="detail-1", period=Period(period), country=None, source_id="source-1"
    )


def _an_element() -> Element:
    return Element(
        content="3.1%",
        element_class=ElementClass.MEASURED,
        source_ref=_provenance().source_ref,
    )


def _question(spec: QuerySpec) -> CompiledQuestion:
    """A compiled question built directly, so a state the corpus does not happen to
    produce -- an unbound detail, an operation nothing fetches -- can still be put in
    front of the fetch."""
    return CompiledQuestion(spec=spec, bindings=_bindings(spec))


# ============================================================================
# Class 1 (AD-1) -- two components deciding the same thing
#
# "A frozen QuerySpec is produced exactly once per answerable question, before any
# data access. No layer past compile/ may set, widen or reinterpret a field."
# The defect behind three periods on one card and four independent row selections.
# ============================================================================


def test_only_compile_can_construct_a_query_spec() -> None:
    """AD-1: *exactly once*, and the "once" is a property of the tree, not of a habit."""
    sites = _construction_sites("QuerySpec")
    outside = [site for site in sites if not site.startswith("compile/")]
    assert sites, "the scan found no QuerySpec construction at all, so it proves nothing"
    assert not outside, (
        "a second component choosing its own spec is the failure AD-1 exists to "
        "foreclose; constructed outside compile/ at:\n  " + "\n  ".join(outside)
    )


def test_a_bound_spec_field_cannot_be_reinterpreted_downstream() -> None:
    """AD-1's second half: no layer past ``compile/`` may set or widen a field."""
    spec = _spec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.period = period_field(Exact(Period("2024")))  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.detail = Bound("detail-2")  # type: ignore[misc]


def test_nothing_under_src_rebuilds_a_spec_through_dataclasses_replace() -> None:
    """``replace()`` is the one route a frozen dataclass leaves open, so it is closed.

    A widened copy is a second binder wearing the first one's name -- and it would pass
    the frozen-assignment test above without either binder noticing.
    """
    offences = [
        _where(path, line)
        for path in _all_modules()
        for line in _dataclass_replacements(_parse(path))
    ]
    assert not offences, (
        "dataclasses.replace on a frozen spec is a second binding with a first "
        "binder's provenance (AD-1):\n  " + "\n  ".join(offences)
    )


def test_the_replacement_scan_would_catch_either_spelling() -> None:
    qualified = ast.parse("import dataclasses\ndef widen(s):\n    return dataclasses.replace(s)\n")
    assert _dataclass_replacements(qualified) == [3]
    bare = ast.parse("from dataclasses import replace\ndef widen(s):\n    return replace(s)\n")
    assert _dataclass_replacements(bare) == [3]
    innocent = ast.parse('def clean(s):\n    return s.replace("a", "b")\n')
    assert _dataclass_replacements(innocent) == []


def test_the_construction_scan_would_catch_a_second_site() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse("def widen(spec):\n    return QuerySpec(detail=spec.detail)\n")
    assert _calls_to(tree, "QuerySpec") == [2]
    qualified = ast.parse("def widen(s):\n    return domain.spec.QuerySpec(detail=s.detail)\n")
    assert _calls_to(qualified, "QuerySpec") == [2]


# ============================================================================
# Class 2 (AD-2) -- declared but unwired
#
# The story names this one explicitly: "every operation produces a plan and every
# planned block has a composer" -- the failure behind five intents whose composers
# did not exist. Eleven operations are declared; one is wired. The foreclosure is
# not that all eleven answer, it is that none of the other ten falls through.
# ============================================================================


@pytest.mark.parametrize("operation", list(Operation))
def test_every_declared_operation_reaches_a_typed_outcome(operation: Operation) -> None:
    """AD-2: a declared operation with no implementation is *stated*, never a hole.

    A `KeyError`, a `None`, or an empty package would each be the declared-but-unwired
    defect. Every one of the eleven comes back as an ``Execution`` carrying a named
    ``FigureCause``, which is what a later epic replaces with a composer.
    """
    port: DatapointsPort = _PublishesNothing()
    question = _question(_spec(operation=operation))
    execution = execute_value(question, port)
    assert isinstance(execution, Execution)
    assert execution.figure is None, "the port publishes nothing, so no figure is available"
    assert execution.cause is not None, (
        f"{operation.value} produced neither a figure nor a stated cause; a declared "
        "operation that falls through is AD-2's declared-but-unwired defect"
    )
    assert execution.cause in set(FigureCause), "the cause must be a member of the closed set"


def test_the_unwired_operations_are_refused_as_unwired_rather_than_as_missing_data() -> None:
    """The distinction that makes the class test above worth having (AD-15).

    ``SERIES`` is declared and not yet fetched; that must not read to a reader, or to an
    operator reading the record, as "the published data has nothing".
    """
    port: DatapointsPort = _PublishesNothing()
    unwired = execute_value(_question(_spec(operation=Operation.SERIES)), port)
    wired = execute_value(_question(_spec(operation=Operation.VALUE)), port)
    # mypy rejects comparing these two members for identity, which is the foreclosure
    # arriving one layer earlier than the assertion: they are provably distinct.
    assert unwired.cause is FigureCause.OPERATION_IS_NOT_A_VALUE
    assert wired.cause is FigureCause.DETAIL_PUBLISHES_NOTHING


def test_every_declared_role_is_placed_in_a_lens_and_given_a_mode() -> None:
    """The composer half of AD-2's class: a block that is planned and never shown.

    A role the engine declares but the tables do not place would be composed, admitted,
    and then displayed by nothing -- the same defect one layer later.
    """
    placement = Placement(rule_set=load_rules())
    for role in Role:
        lenses = placement.lenses_for(role)
        assert lenses, f"{role.value} is shown by no lens"
        assert lenses <= set(Lens)
        if placement.carries_a_figure(role):
            assert placement.mode_for(role) is not None


# ============================================================================
# Class 3 (AD-18) -- a figure escaping the display policy
#
# "One formatter owns value-to-string, with an explicit mode. No composer may build
# a numeric string by any other route." F-004: two composers rendering the same row
# differently on one card.
#
# tests/test_assemble.py scans assemble/, narrate/ and respond/. This widens the
# class to the rest of the answer path -- api/ and execute/ are both on it and
# neither was covered.
# ============================================================================


#: The shapes a second value-to-string route takes. Spelled here rather than imported
#: from the story that introduced them, so this class test cannot be silently narrowed
#: by an edit to another session's file.
NUMBER_TO_STRING_CALLS = frozenset({"round", "format", "format_number", "format_value"})
NUMBER_TO_STRING_METHODS = frozenset({"quantize"})
NUMBER_TO_STRING_IMPORTS = frozenset({"askai.messages.numbers", "format_number", "format_value"})


def _imported_names(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    else:
        if node.module:
            yield node.module
        for alias in node.names:
            yield alias.name


def _second_formatting_routes(tree: ast.Module) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for name in _imported_names(node):
                if name in NUMBER_TO_STRING_IMPORTS:
                    found.append((f"imports {name}", node.lineno))
        elif isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id in NUMBER_TO_STRING_CALLS:
                found.append((f"calls {callee.id}()", node.lineno))
            elif isinstance(callee, ast.Attribute) and callee.attr in NUMBER_TO_STRING_METHODS:
                found.append((f"calls .{callee.attr}()", node.lineno))
    return found


def test_no_module_on_the_answer_path_writes_a_figure_by_a_second_route() -> None:
    """AD-18, widened to the whole answer path rather than the composing third of it.

    ``assemble/format.py`` is the single exemption and is exempt by path. ``compile/``
    is scanned too: it cannot hold a figure (AD-3), so a number-to-string call there
    would be a figure arriving before ``execute/`` ever ran.
    """
    formatter = PACKAGE_ROOT / "assemble" / "format.py"
    offences = [
        f"{_where(path, line)} {what}"
        for path in _modules(*ANSWER_PATH)
        if path != formatter
        for what, line in _second_formatting_routes(_parse(path))
    ]
    assert not offences, (
        "a figure becomes a string through assemble.Formatter and nowhere else "
        "(AD-18, FR-47):\n  " + "\n  ".join(offences)
    )


def test_only_execute_can_see_a_published_row_at_all() -> None:
    """AD-3, the half of the class that precedes formatting: figures originate once.

    Scanned as visibility rather than as arithmetic. A ``Decimal(...)`` is not by itself
    a defect -- ``assemble/`` builds one for a rounding exponent and for an ordinal
    position, neither of which is a published value. What would be a defect is a second
    module holding the *row*, because that is the only thing a published figure can be
    read out of. Nothing but ``execute/`` and the adapter that feeds it can name the
    type, so *"a number that cannot be traced to a row does not exist"* is a fact about
    what is in scope rather than a rule about what to write.
    """
    permitted = {"execute", "ports", "adapters"}
    offences = [
        _where(path, node.lineno)
        for path in _all_modules()
        if path.relative_to(PACKAGE_ROOT).parts[0] not in permitted
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if name in {"askai.ports.datapoints", "DatapointRow", "DatapointsPort"}
    ]
    assert not offences, (
        "only execute/ may produce a numeric value, and only by exact key lookup "
        "(AD-3):\n  " + "\n  ".join(offences)
    )


def test_the_second_route_scan_would_catch_one() -> None:
    tree = ast.parse("def show(v):\n    return str(round(v, 2))\n")
    assert _second_formatting_routes(tree) == [("calls round()", 2)]


# ============================================================================
# Class 4 (AD-6) -- provenance as an afterthought
#
# "There is no constructor that produces an element without a source_ref."
# Provenance stops being a render-time label brevity can drop.
# ============================================================================


def test_no_element_can_be_built_without_a_source_ref() -> None:
    """AD-6 at runtime; ``tests/test_type_invariants.py`` asserts the same under mypy.

    Both halves are needed: the type fixture catches the omitted argument, this catches
    the blank one, and the blank one type-checks.
    """
    assert [field.name for field in dataclasses.fields(Element)] == [
        "content",
        "element_class",
        "source_ref",
    ]
    assert all(
        field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
        for field in dataclasses.fields(Element)
    ), "a default on any field is a constructor that omits it"
    with pytest.raises(ValueError, match="source_ref"):
        Element(content="3.1%", element_class=ElementClass.MEASURED, source_ref="   ")


def test_element_offers_no_second_constructor() -> None:
    """An alternate constructor is a second route, and the guarantee is that none exists."""
    alternates = [
        name
        for name, member in inspect.getmembers(Element)
        if not name.startswith("__")
        and (inspect.isfunction(member) or inspect.ismethod(member))
    ]
    assert not alternates, (
        "Element has no classmethod, staticmethod or builder; each would be a second "
        f"route to an element (AD-6). Found: {alternates}"
    )


def test_every_element_builder_is_handed_a_reference_value_never_a_loose_string() -> None:
    """The class, not the type: a builder taking a bare ``str`` would defeat AD-6.

    ``Provenance.source_ref`` is derived from its five fields, so an element built from
    one cannot carry a reference that disagrees with the row it claims. A builder that
    accepted the string instead would take back exactly that: the reference and the
    thing it describes could then disagree, which is the render-time label AD-6 replaced.

    There is deliberately more than one reference *type* -- a published row has a
    ``Provenance``, a fact about the loaded catalogue has no row and carries its own --
    so what is asserted is the shape common to all of them, not one name.
    """
    #: What a builder is allowed to take besides the reference. Everything else in a
    #: signature is the reference, and it must not be a string.
    NOT_A_REFERENCE = frozenset({"str", "ElementClass", "Lang", "int", "bool"})
    builders = [
        (path, function)
        for path in _all_modules()
        for function in _functions(_parse(path))
        if _annotation(function.returns) == "Element"
    ]
    assert builders, "no element builder was found, so this scan proves nothing"
    offences = [
        _where(path, function.lineno)
        for path, function in builders
        if not (set(_parameter_annotations(function)) - NOT_A_REFERENCE)
    ]
    assert not offences, (
        "an element is built from a reference value that derives its own source_ref, "
        "never from a loose string (AD-6):\n  " + "\n  ".join(offences)
    )


# ============================================================================
# Class 5 (AD-8) -- the model producing more than it may
#
# "The parser-plus-validator is the floor, and correctness never depends on more."
# There is to be no way to receive model text without having declared what would
# make it acceptable.
# ============================================================================


def test_a_model_call_cannot_be_made_without_a_validator_and_a_budget() -> None:
    """AD-8 and AD-9 as a signature: neither field has a default, so neither is optional."""
    required = {
        field.name
        for field in dataclasses.fields(ModelCall)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    }
    assert {"validate", "budget"} <= required, (
        "a default validator is one nobody tested, and a default budget is a call "
        "nobody bounded (AD-8, AD-9)"
    )


def test_the_port_returns_an_outcome_rather_than_model_text() -> None:
    """The validated value or a typed failure -- never the text, and never a retry loop."""
    verbs = [name for name in vars(ModelPort) if not name.startswith("_")]
    assert verbs == ["complete"], (
        f"a port with more verbs is one a caller can build a loop out of (AD-22): {verbs}"
    )
    signature = inspect.signature(ModelPort.complete)
    assert "Outcome" in str(signature.return_annotation)


def test_nothing_outside_the_model_adapter_speaks_the_model_protocol() -> None:
    """AD-9: *no module outside adapters/ knows either protocol.*"""
    permitted = PACKAGE_ROOT / "adapters" / "model"
    offences = [
        _where(path, node.lineno)
        for path in _all_modules()
        if permitted not in path.parents
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if name.split(".")[0] in {"httpx", "openai", "anthropic", "requests", "urllib3"}
    ]
    assert not offences, (
        "the model is reached through ModelPort; a client import elsewhere is direct "
        "coupling (AD-9):\n  " + "\n  ".join(offences)
    )


# ============================================================================
# Class 6 (AD-28) -- guard holes
#
# The narration guard lands in Epic 8. What is foreclosed *now* is the shape the
# guard could otherwise be written in: a partial edit, a repair, or prose that
# becomes an element. "Any failure discards the whole prose -- never a partial
# edit, never a repair."
# ============================================================================


def test_narrate_cannot_construct_an_element_so_prose_can_never_become_one() -> None:
    """AD-28's structural half. The behavioural half arrives with Epic 8's guard.

    If prose cannot be turned into an element, a guard that "mostly" accepted something
    would still leave the deterministic answer standing -- there is nowhere for the
    kept fragment to go.
    """
    offences = _construction_sites("Element", within=_modules("narrate"))
    assert not offences, (
        "narrate/ composes packages out of elements assemble/ built; constructing one "
        "here is prose acquiring provenance (AD-6, AD-28):\n  " + "\n  ".join(offences)
    )


def test_a_package_offers_no_route_to_a_partial_edit() -> None:
    """*"Never a partial edit, never a repair."* -- asserted as an absent method.

    A guard that could return a repaired package would be written as one. The type
    offers no mutator and no copy-with, so discard is the only expressible outcome.
    """
    mutators = [
        name
        for name, member in inspect.getmembers(AnswerPackage)
        if not name.startswith("_") and callable(member)
    ]
    assert not mutators, (
        "AnswerPackage has no add_element, with_caveat, merge or repair; each would "
        f"make a partial edit expressible (AD-10, AD-28). Found: {mutators}"
    )
    assert all(
        field.type.startswith("tuple") or "tuple" not in field.type
        for field in dataclasses.fields(AnswerPackage)
    )


def test_a_package_that_claims_to_be_an_answer_must_carry_elements() -> None:
    """The discard default, at the one place it is already expressible.

    An empty answer is what a guard that discarded everything and then kept going would
    produce, so the type refuses it: the result is a refusal, which states its reason.
    """
    with pytest.raises(ValueError, match="an answer is its elements"):
        AnswerPackage(
            source=PackageSource.APPROVED,
            kind=PackageKind.ANSWER,
            spec=_spec(),
            bindings=_bindings(_spec()),
            elements=(),
        )


# ============================================================================
# Class 7 (AD-10) -- approved and external blurring
#
# "ExternalAnswer is a distinct type from Answer with no conversion between them
# and no function taking both and returning one -- the merge is impossible at the
# type level, not forbidden by discipline."
# ============================================================================


def test_no_function_anywhere_takes_two_packages_and_returns_one() -> None:
    """AD-10's load-bearing sentence, asserted over the whole tree.

    The reconciliation AD-10 forbids has exactly one shape: something that consumes an
    approved package and an external one and emits a single package. Nothing has that
    signature, and this is what keeps it that way.
    """
    offences = [
        _where(path, function.lineno)
        for path in _all_modules()
        for function in _functions(_parse(path))
        if _annotation(function.returns) == "AnswerPackage"
        and sum(
            1
            for annotation in _parameter_annotations(function)
            if annotation == "AnswerPackage"
        )
        >= 2
    ]
    assert not offences, (
        "Combined shows two answers side by side so a reader can weigh them; merging "
        "them is the one thing AD-10 forbids:\n  " + "\n  ".join(offences)
    )


def test_only_narrate_constructs_a_package() -> None:
    """*"narrate/ is the only thing that may construct an AnswerPackage."*"""
    sites = _construction_sites("AnswerPackage")
    outside = [site for site in sites if not site.startswith("narrate/")]
    assert sites, "the scan found no package construction at all, so it proves nothing"
    assert not outside, (
        "the response layer orders packages and never builds one (AD-10):\n  "
        + "\n  ".join(outside)
    )


def test_an_external_package_cannot_exist_without_its_caveat() -> None:
    """FR-84, FR-88: unconditional, so the reader can never read external as approved."""
    with pytest.raises(ValueError, match="caveat"):
        AnswerPackage(
            source=PackageSource.EXTERNAL,
            kind=PackageKind.ANSWER,
            spec=_spec(),
            bindings=_bindings(_spec()),
            elements=(Placed(element=_an_element(), role=Role.HEADLINE),),
            caveat=None,
        )


def test_the_response_layer_cannot_name_the_type_it_orders() -> None:
    """The structural reason the merge above is unwritable, not just unwritten.

    ``import-linter`` forbids ``respond/`` importing ``narrate`` or ``assemble``. A layer
    that cannot say ``AnswerPackage`` cannot read a field off one, rebuild one, or merge
    two -- which is why ``respond/order.py`` is generic in an opaque ``T``.
    """
    offences = [
        _where(path, node.lineno)
        for path in _modules("respond")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if name.startswith(("askai.narrate", "askai.assemble"))
    ]
    assert not offences, "respond/ orders opaque packages (AD-10):\n  " + "\n  ".join(offences)


# ============================================================================
# Class 8 (AD-9) -- unbounded or serial IO
#
# "Every call on either port is budgeted and abandonable." Story 2.6 cites this
# test by name. The engine makes no call outside the estate on the ModelPort.
# ============================================================================


@pytest.mark.parametrize(
    "tokens,connect,read",
    [(0, 2.0, 20.0), (-1, 2.0, 20.0), (64, 0.0, 20.0), (64, 2.0, 0.0), (64, -1.0, 20.0)],
)
def test_a_budget_that_bounds_nothing_cannot_be_constructed(
    tokens: int, connect: float, read: float
) -> None:
    """AD-9: a non-positive timeout is not "wait forever", it is an unbounded call."""
    with pytest.raises(ValueError):
        Budget(max_output_tokens=tokens, connect_seconds=connect, read_seconds=read)


def test_every_call_site_the_architecture_declares_is_budgeted_at_the_type_level() -> None:
    """The four sites AD-22 permits, each reachable only through a budgeted call."""
    assert len(list(CallSite)) == 4, (
        "AD-22 names four bounded model call-sites; a fifth is a spine change, not a "
        f"new enum member. Found: {[site.value for site in CallSite]}"
    )
    for site in CallSite:
        call = ModelCall(
            site=site,
            instruction="choose one id",
            input_text="a question",
            validate=lambda text: Found(text),
            budget=Budget(max_output_tokens=16, connect_seconds=2.0, read_seconds=20.0),
        )
        assert call.budget.read_seconds > 0.0


def test_nothing_under_src_sleeps_or_polls() -> None:
    """AD-9's *"abandonable"*, and AD-22's *"no component may loop"*.

    A poll interval is a latency floor on every request -- the specific thing AD-9 says
    changes about the inherited job API.
    """
    offences = [
        _where(path, node.lineno)
        for path in _all_modules()
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sleep"
    ]
    assert not offences, (
        "a sleep on the answer path is a poll loop's other half (AD-9, AD-22):\n  "
        + "\n  ".join(offences)
    )


# ============================================================================
# Class 9 (AD-15) -- failure indistinguishable from absence
#
# "The except Exception density that made a rule which stopped firing
# indistinguishable from one never reached."
# ============================================================================


def test_absence_and_failure_are_separate_types_that_cannot_be_confused() -> None:
    """AD-15: three states, so a component that broke is never read as one that found
    nothing. ``mypy --strict`` refuses an inexhaustive match, which is the foreclosure."""
    # Three separate types, not one with a flag. ``mypy --strict`` refuses an
    # inexhaustive match over the union, which is the foreclosure; asserting the
    # distinctness here would be comparing two literals mypy already proved differ.
    assert len({Found, Absent, Failed}) == 3
    with pytest.raises(ValueError, match="absence states why"):
        Absent(reason="  ")
    with pytest.raises(ValueError, match="at least one degradation"):
        Failed(degradations=())


def test_the_causes_of_an_absent_figure_name_which_one_happened() -> None:
    """A closed set, never a sentence: the record keeps the code, ``narrate/`` says it.

    Exactly one cause is a failure of the store rather than a fact about the data, and
    it is spelled distinctly -- the whole of AD-15 in one enum.
    """
    causes = {cause.value for cause in FigureCause}
    assert len(causes) == len(list(FigureCause)), "two causes share a code"
    assert FigureCause.LOOKUP_FAILED.value not in {
        FigureCause.DETAIL_PUBLISHES_NOTHING.value,
        FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD.value,
        FigureCause.VALUE_IS_NOT_A_FIGURE.value,
    }


def test_broad_exception_handling_exists_only_at_an_adapter_boundary() -> None:
    """AD-15: *no bare ``except Exception`` outside adapter boundaries.*

    ruff's BLE/E722 enforce this as lint with a per-directory ignore; asserted here too
    because the class test must not depend on a per-file-ignore staying where it is.
    """
    offences: list[str] = []
    for path in _all_modules():
        if path.relative_to(PACKAGE_ROOT).parts[0] == "adapters":
            continue
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = node.type
            if caught is None:
                offences.append(f"{_where(path, node.lineno)} bare except:")
            elif isinstance(caught, ast.Name) and caught.id in {"Exception", "BaseException"}:
                offences.append(f"{_where(path, node.lineno)} except {caught.id}")
    assert not offences, (
        "a soft failure is a typed Degradation, not a swallowed exception "
        "(AD-15):\n  " + "\n  ".join(offences)
    )


# ============================================================================
# Class 10 (AD-1, AD-17) -- a card contradicting itself
#
# Three periods on one card. The foreclosure: an answer has exactly one place to
# state its period, its grain and its scope, and it is the package's own spec.
#
# ARCHITECTURE FINDING, recorded rather than worked around. The half below is
# foreclosed. The other half is not: AnswerPackage does not check that its
# elements' source_refs name the spec it carries, so agreement rests on every
# composer deriving its Provenance from the one figure. See deferred-work.md,
# "AD-1: a package does not check its elements against its own spec".
# ============================================================================


def test_a_card_has_only_one_place_to_state_its_period() -> None:
    """AD-1: nothing but the package's spec says what period the answer is about.

    An element carries content, a class and a reference -- no period, no grain, no
    scope. So two composers cannot each state a period, because neither has a field to
    state one in. The three-periods-on-one-card defect needs a second field to exist.
    """
    element_fields = {field.name for field in dataclasses.fields(Element)}
    assert not element_fields & {"period", "grain", "country", "scope", "spec"}, (
        f"an element states no period of its own (AD-1); it carries {element_fields}"
    )
    placed_fields = {field.name for field in dataclasses.fields(Placed)}
    assert placed_fields == {"element", "role"}, (
        f"Placed pairs an element with its job and adds no scope of its own: {placed_fields}"
    )
    package_fields = [field.name for field in dataclasses.fields(AnswerPackage)]
    assert package_fields.count("spec") == 1
    assert "period" not in package_fields and "grain" not in package_fields, (
        "the package reads its period off its spec; a second field is a second answer"
    )


def test_the_grain_is_read_off_the_period_and_never_stored_beside_it() -> None:
    """AD-1's ERD note and AD-19: grain is not a spec field, ``Period`` carries it.

    A stored grain is a grain that can disagree with the period it labels -- which is
    how a monthly figure comes to be captioned as a yearly one.
    """
    assert "grain" not in {field.name for field in dataclasses.fields(QuerySpec)}
    assert "grain" not in {field.name for field in dataclasses.fields(Provenance)}
    assert isinstance(Provenance.grain, property)
    assert _provenance("2025").grain is Period("2025").grain is Grain.YEARLY


def test_the_same_question_and_the_same_today_are_one_spec() -> None:
    """AD-17: spec determinism is a hard gate, and equality is what makes it one.

    ``QuerySpec`` compares and hashes by value, so *"the same question compiles to the
    same spec"* is an assertion a test can make rather than a property of an object id.
    """
    assert _spec() == _spec()
    assert hash(_spec()) == hash(_spec())
    assert _spec(period=Exact(Period("2024"))) != _spec()
    assert Question.parse("what is inflation").words == Question.parse("what is inflation").words


def test_today_is_carried_on_the_spec_so_a_resolution_cannot_outlive_its_date() -> None:
    """AD-17: ``today`` is an explicit field and part of every key derived from it."""
    assert "today" in {field.name for field in dataclasses.fields(QuerySpec)}
    yesterday = QuerySpec(
        detail=Bound("detail-1"),
        period=period_field(Exact(Period("2025"))),
        country_scope=Bound(National()),
        measure=Bound(Measure.ACTUAL),
        operation=Bound(Operation.VALUE),
        today=Period("2024").start,
    )
    assert yesterday != _spec(), "two dates must not compile to one spec (AD-17)"


# ============================================================================
# Class 11 (AD-11, AD-25, AD-26) -- a component trusting an upstream that did not
# deliver
#
# A rule read that silently defaults, an index and a query folding text
# differently, a fetch handed an unbound field and guessing at it.
# ============================================================================


def test_a_missing_rule_is_raised_rather_than_defaulted() -> None:
    """AD-11: rules are loaded data and the service fails without them.

    A default here is business logic that cannot be enumerated -- the founding defect.
    """
    rule_set: RuleSet = load_rules()
    with pytest.raises(LookupError):
        rule_set.value("R-DOES-NOT-EXIST", "anything")
    with pytest.raises(LookupError):
        rule_set.value("R-ROLE-LENS-MAPPING", "a_clause_that_is_not_there")


def test_a_missing_rule_directory_fails_to_load_rather_than_loading_empty() -> None:
    """*"The service fails to start on an invalid or missing file."*"""
    with pytest.raises(Exception, match="(?i)rule|file|director"):
        load_rules(PROJECT_ROOT / "no" / "such" / "directory")


def test_the_index_and_the_query_fold_text_through_one_function_object() -> None:
    """AD-26: finding 121's Arabic half. Asserted as identity, not as equal behaviour."""
    from askai.domain.normalise import normalise

    #: One module from each side of AD-26's sentence. ``tests/test_normalise.py`` walks
    #: the whole tree; what this asserts is that both *sides* are actually reached, so
    #: the whole-tree scan is not passing because one of them stopped folding at all.
    index_path = ("askai.adapters.index.lexical", "askai.adapters.index.names")
    query_path = ("askai.compile.question", "askai.compile.catalogue")
    for name in (*index_path, *query_path):
        module = importlib.import_module(name)
        folder = getattr(module, "normalise", None)
        assert folder is normalise, (
            f"{name} does not fold through the engine's one normalise(); an index and a "
            "query that fold differently is finding 121's Arabic half (AD-26)"
        )


def test_an_unbound_field_reaches_the_fetch_as_a_stated_cause_not_a_guess() -> None:
    """AD-25 and AD-1: ``execute/`` is handed a field the reader never named.

    It does not default it, widen it, or search for a near match -- it names which field
    was unbound. A fetch that guessed would be the substituted indicator FR-39 forbids.
    """
    port: DatapointsPort = _PublishesNothing()
    spec = QuerySpec(
        detail=Unbound(reason="the question named no indicator"),
        period=period_field(Exact(Period("2025"))),
        country_scope=Bound(National()),
        measure=Bound(Measure.ACTUAL),
        operation=Bound(Operation.VALUE),
        today=TODAY,
    )
    execution = execute_value(_question(spec), port)
    assert execution.cause is FigureCause.DETAIL_NOT_BOUND
    assert execution.figure is None


# ============================================================================
# Class 12 (AD-16) -- the evidence package built once and kept
#
# "Partial records assembled from several call sites, and an unreconstructable
# answer." One recorder, writing once, from the finished package.
# ============================================================================


def test_the_answer_record_is_built_at_exactly_one_site() -> None:
    """AD-16: a record assembled at several call sites is a partial record."""
    sites = _construction_sites("AnswerRecord")
    assert len(sites) == 1, (
        "one record per request means one place that builds one; found "
        f"{len(sites)}:\n  " + "\n  ".join(sites)
    )


def test_the_record_is_built_from_the_finished_response_rather_than_accumulated() -> None:
    """*"After the package is final."* -- readable off the builder's own signature.

    A builder that took loose pieces could be called before the answer was finished; one
    that takes the finished ``Response`` cannot be.
    """
    builders = [
        (path, function)
        for path in _all_modules()
        for function in _functions(_parse(path))
        if _annotation(function.returns) == "AnswerRecord"
    ]
    assert len(builders) == 1, f"expected one record builder, found {len(builders)}"
    _, builder = builders[0]
    annotations = _parameter_annotations(builder)
    assert any("Response" in annotation for annotation in annotations), (
        "the record is built from the finished response (AD-16); this builder takes "
        f"{annotations}"
    )


def test_a_record_cannot_be_written_that_does_not_say_how_every_field_was_bound() -> None:
    """AD-16's completeness clause, as a construction-time refusal.

    An answer whose record omits a field's binding mechanism is an answer that cannot be
    reconstructed -- which is the whole point of keeping one.
    """
    required = {
        field.name
        for field in dataclasses.fields(AnswerRecord)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    }
    assert {"record_id", "recorded_at", "identity", "question", "spec", "bindings"} <= required


def test_no_module_but_observability_writes_a_record() -> None:
    """AD-16: *"no other module writes to the record store."*

    Asserted as an import scan: a module that cannot reach ``RecordPort`` or the store
    adapter cannot write one, whatever it intends.
    """
    permitted = {"observability", "adapters", "api", "ports"}
    offences = [
        _where(path, node.lineno)
        for path in _all_modules()
        if path.relative_to(PACKAGE_ROOT).parts[0] not in permitted
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if "record" in name.lower()
    ]
    assert not offences, (
        "one recorder, writing once (AD-16):\n  " + "\n  ".join(offences)
    )


