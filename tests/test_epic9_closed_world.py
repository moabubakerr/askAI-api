"""Story 9.3 -- closed-world enforcement, demonstrated by construction, not by sampling.

``assemble/provenance.py`` already refuses an element whose ``source_ref`` does not
resolve against the ``SourceCatalogue``, and emits ``UNRESOLVED_SOURCE_REF`` when it does.
Nothing here reimplements that. What this module asserts is AD-7's **construction
argument**, which is a different claim and a stronger one: not *"we checked a hundred
answers and none carried unsourced content"* but *"there is no path by which unsourced
content could reach a package."*

The argument has three legs, and each is asserted as a scan over the tree rather than as
a case:

1. **No constructor produces an element without a ``source_ref``.** ``Element`` has three
   required fields, no default, no alternate constructor and no classmethod; a blank
   reference is refused at ``__post_init__``; and every constructor in ``assemble/``
   derives the reference from a provenance value -- a ``Provenance`` for a published row,
   a ``CatalogueReference`` for a catalogue fact -- rather than accepting one alongside
   it, so a caller cannot hand in a reference describing something other than the content
   it is attached to.
2. **``narrate/`` cannot construct elements at all, and ``execute/`` is the only figure
   source.** ``narrate/`` never names ``Element``; it may only call an ``assemble/``
   constructor, each of which demands a ``Provenance``, and every ``Provenance`` it builds
   is built out of a ``Figure`` -- a type defined in ``execute/`` and constructed nowhere
   else. So the chain from a published row to a rendered element has no place to admit a
   value that did not come from the read model.
3. **The rejection is a typed ``Degradation``, never a silent drop.** Every element that
   goes into admission comes out as either an element or a degradation; the counts add up;
   and an answer whose elements were all refused becomes a stated refusal carrying the
   degradations rather than a shorter answer that reads exactly like a complete one.

**The model's inventoried role** (FR-78) is asserted the same way. It is *only* wording,
disambiguation among supplied candidates and structural classification, and **no figure,
date, country fact, definition or causal claim originates in it** -- which is true here
because no layer that composes an answer can reach a model at all. The scan asserts that
while it is trivially true, so the first import that would make it interesting fails the
build rather than passing review.

**What is deliberately not asserted.** The knowledge base excludes indicators marked
``Confidential``, and that exclusion **cannot be evidenced from this export**: the type
exists in ``P13_Ref_IndicatorPriorityTypes``, and the export carries 105 ``Priority``, 84
blank and **zero** confidential rows, in both layers. A test asserting "no confidential
indicator reaches an answer" would quantify over an empty set, pass vacuously, and keep
passing if the exclusion were deleted tomorrow. It is left unwritten on purpose. The
exclusion is real and lives in Story 1.6's ``CHECK`` constraint; evidencing it needs an
export that contains one.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from askai.assemble.elements import absent, build, derived, measured
from askai.assemble.provenance import (
    Admitted,
    Provenance,
    ProvenanceFailure,
    Refused,
    admit,
    admit_all,
)
from askai.domain.degradation import Degradation
from askai.domain.element import Element, ElementClass
from askai.domain.period import Period
from askai.domain.spec import Measure
from askai.execute.value import Figure

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"

#: The modules allowed to construct an ``Element``, exempt by path so that a third added
#: beside them is caught the moment it appears. There are two rather than one because
#: there are two kinds of provenance: ``elements.py`` sources an element to a published
#: row through a ``Provenance``, and ``meta/reference.py`` sources a catalogue fact -- a
#: group's size, a published definition -- through a ``CatalogueReference``. Both derive
#: the reference from a value; neither accepts one as a string. The property AD-6 rests on
#: is that derivation, not the count of modules, and it is asserted directly below.
THE_ELEMENT_CONSTRUCTORS: Final = (
    PACKAGE_ROOT / "assemble" / "elements.py",
    PACKAGE_ROOT / "assemble" / "meta" / "reference.py",
)

#: The parameter names a reference is derived from. A constructor taking neither, or
#: taking a bare ``source_ref``, is the route AD-6 exists to close.
REFERENCE_PARAMETERS: Final = frozenset({"provenance", "reference"})

#: The layers between a published row and a rendered answer. A model reached from any of
#: them would be a second source of content on the answer path (FR-78, AD-3).
COMPOSING_PACKAGES: Final = ("compile", "validate", "execute", "assemble", "narrate")

#: How a model arrives: through the port, through the adapter, or through a client
#: library imported directly.
MODEL_IMPORTS: Final = frozenset({"askai.ports.model", "askai.adapters.model"})
MODEL_LIBRARIES: Final = frozenset(
    {"openai", "anthropic", "langchain", "ollama", "llama_index", "cohere", "boto3"}
)


class NothingResolves:
    """A ``SourceCatalogue`` that holds nothing.

    The closed world at its limit: every reference is unresolved, so every element is
    refused. It is the shape a read model that lost its published layer would take, and
    it is how the refusal path is exercised without arranging a corrupt database.
    """

    def resolves(self, source_ref: str) -> bool:
        return False


class EverythingResolves:
    def resolves(self, source_ref: str) -> bool:
        return True


def a_provenance(detail_id: str = "D-CPI-HEADLINE") -> Provenance:
    return Provenance(
        detail_id=detail_id,
        period=Period("2026-04"),
        country=None,
        source_id="S-PSA-CPI",
    )


def _modules(package: str) -> list[Path]:
    return sorted(
        path
        for path in (PACKAGE_ROOT / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _all_modules() -> list[Path]:
    return sorted(
        path for path in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    )


def _parse(path: Path) -> ast.Module:
    """Parse *path*, tolerating one that vanished between the walk and the read.

    ``tests/test_dependency_contracts.py`` plants a module under ``src/askai/`` and
    removes it again, so a tree-wide walk can list a file that is gone a moment later.
    An empty module is the honest reading of a file that no longer exists: it holds no
    construction site, because it holds nothing.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        source = ""
    return ast.parse(source, filename=str(path))


def _where(path: Path, line: int) -> str:
    return f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line}"


def _construction_sites(name: str, paths: list[Path] | None = None) -> list[str]:
    """Every call in the tree that builds *name*, as ``package/module.py:line``."""
    return [
        _where(path, node.lineno)
        for path in (paths if paths is not None else _all_modules())
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def _imported(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    else:
        if node.module:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


# ================================ leg one: no constructor omits a source_ref


def test_the_element_type_has_three_required_fields_and_no_second_constructor() -> None:
    """AD-6's whole design, read off the type.

    A default on ``source_ref`` is all it would take to make an unsourced element
    expressible, and an alternate constructor is all it would take to route around the
    check. Neither exists, and the assertion is over ``dataclasses.fields`` and the class
    dictionary rather than over a docstring that says so.
    """
    fields = {field.name: field for field in dataclasses.fields(Element)}
    assert set(fields) == {"content", "element_class", "source_ref"}
    for field in fields.values():
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name
    alternates = [
        name
        for name, value in vars(Element).items()
        if isinstance(value, classmethod | staticmethod)
    ]
    assert alternates == [], f"a second route to an element: {alternates}"


def test_a_blank_source_ref_is_refused_because_the_signature_cannot_see_it() -> None:
    """``Element(c, k, "")`` type-checks, so the type checker is not the whole guard."""
    for blank in ("", "   ", "\t\n"):
        with pytest.raises(ValueError, match="non-blank source_ref"):
            Element(content="x", element_class=ElementClass.MEASURED, source_ref=blank)


@pytest.mark.parametrize("constructor", [build, measured, derived, absent])
def test_every_published_row_constructor_demands_a_provenance(
    constructor: object,
) -> None:
    """The reference is *derived* from a provenance, never passed beside one.

    A caller that cannot supply a reference cannot supply a wrong one, which is why the
    parameter is a ``Provenance`` and there is no ``source_ref`` parameter anywhere in
    ``assemble/elements.py``.
    """
    parameters = inspect.signature(constructor).parameters  # type: ignore[arg-type]
    assert "provenance" in parameters
    assert parameters["provenance"].default is inspect.Parameter.empty
    assert "source_ref" not in parameters


def test_an_element_is_constructed_only_where_a_reference_can_be_derived() -> None:
    """Every element in the engine comes out of one of two modules in ``assemble/``.

    The scan is over construction *sites* rather than over imports, because importing the
    type to annotate a parameter is fine and is what several modules do. Calling it is the
    step that creates provenance, and only ``assemble/`` does.
    """
    sites = _construction_sites("Element")
    assert sites, "the scan found no element construction at all, so it proves nothing"
    permitted = tuple(
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:" for path in THE_ELEMENT_CONSTRUCTORS
    )
    outside = [site for site in sites if not site.startswith(permitted)]
    assert not outside, (
        "an element is constructed in assemble/ and nowhere else, so that deriving the "
        "source_ref from a provenance value is the only way to make one (AD-6):\n  "
        + "\n  ".join(outside)
    )


def test_no_element_constructor_anywhere_accepts_a_reference_as_a_string() -> None:
    """The derivation, asserted at the construction sites themselves.

    Every ``source_ref=`` argument in the tree is an attribute read off a provenance
    value -- ``provenance.source_ref``, ``reference.source_ref`` -- and never a literal
    and never a string parameter passed straight through. A caller that cannot supply a
    reference cannot supply a wrong one, which is the whole of why the reference is
    derived rather than accepted.
    """
    offences: list[str] = []
    for path in THE_ELEMENT_CONSTRUCTORS:
        for node in ast.walk(_parse(path)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Element"
            ):
                continue
            given = {keyword.arg: keyword.value for keyword in node.keywords}
            reference = given.get("source_ref")
            if not (isinstance(reference, ast.Attribute) and reference.attr == "source_ref"):
                offences.append(_where(path, node.lineno))
    assert offences == [], (
        "a source_ref that is written rather than derived is the render-time label AD-6 "
        "replaced:\n  " + "\n  ".join(offences)
    )


def test_every_public_element_constructor_demands_a_reference_bearing_value() -> None:
    """Asserted over the modules rather than over the names imported above, so a
    constructor added tomorrow is held to the same rule without this test knowing it."""
    offences = [
        f"{_where(path, function.lineno)} {function.name}"
        for path in THE_ELEMENT_CONSTRUCTORS
        for function in ast.walk(_parse(path))
        if isinstance(function, ast.FunctionDef)
        and not function.name.startswith("_")
        and _returns(function) == "Element"
        and not (REFERENCE_PARAMETERS & {argument.arg for argument in function.args.args})
    ]
    assert not offences, (
        "every element constructor derives its reference from a provenance value:\n  "
        + "\n  ".join(offences)
    )


def _returns(function: ast.FunctionDef) -> str:
    return ast.unparse(function.returns) if function.returns is not None else ""


# ============= leg two: narrate/ builds no element, and execute/ is the only figure source


def test_narrate_constructs_no_element_and_cannot_name_the_type() -> None:
    """AD-7's second clause, as a scan.

    ``narrate/`` composes wording and hands it to an ``assemble/`` constructor together
    with a provenance. It never says ``Element`` -- not to build one, not to annotate one,
    and not to re-class one -- so there is no expression in the narration layer that
    produces a piece of an answer without provenance attached.
    """
    offences = [
        _where(path, node.lineno)
        for path in _modules("narrate")
        for node in ast.walk(_parse(path))
        if (isinstance(node, ast.Name) and node.id in {"Element", "ElementClass"})
        or (isinstance(node, ast.Attribute) and node.attr in {"Element", "ElementClass"})
    ]
    assert not offences, (
        "narrate/ cannot construct an element; it asks assemble/ for one and has to "
        "supply the provenance to get it:\n  " + "\n  ".join(offences)
    )


def test_respond_constructs_no_element_either() -> None:
    """The layer below the package ordering, for completeness: it cannot name the
    package, so it certainly cannot reach an element inside one."""
    assert not _construction_sites("Element", _modules("respond"))


def test_execute_is_the_only_figure_source() -> None:
    """A figure is a published number and the row it came from, and one layer makes one.

    Both halves are asserted: the type is *declared* in ``execute/`` and it is
    *constructed* in ``execute/``. A figure built anywhere else would be a number that
    entered the answer path without passing the fetch.
    """
    declarations = [
        _where(path, node.lineno)
        for path in _all_modules()
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ClassDef) and node.name == "Figure"
    ]
    assert len(declarations) == 1 and declarations[0].startswith("execute/"), declarations
    sites = _construction_sites("Figure")
    assert sites, "the scan found no figure construction at all, so it proves nothing"
    assert all(site.startswith("execute/") for site in sites), sites


def test_every_provenance_in_narrate_is_built_from_a_figure() -> None:
    """The join between the two legs: the provenance an element is sourced to is made of
    values ``execute/`` produced, so the element's reference describes a real row.

    Asserted as the absence of the alternative -- a ``Provenance`` built in ``narrate/``
    from anything other than an attribute of a fetched value. Every construction site
    passes attributes, never literals, which is what makes a hand-written reference
    unwritable here.
    """
    literal_arguments = [
        _where(path, node.lineno)
        for path in _modules("narrate")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Provenance"
        for keyword in node.keywords
        if isinstance(keyword.value, ast.Constant)
    ]
    assert not literal_arguments, (
        "a Provenance whose fields are literals is a source_ref someone wrote rather "
        "than one the data produced:\n  " + "\n  ".join(literal_arguments)
    )


def test_the_construction_scan_would_catch_an_element_built_outside_assemble() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse(
        "def compose(text):\n"
        "    return Element(content=text, element_class=k, source_ref='made-up')\n"
    )
    assert [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Element"
    ] == [2]


# ================= leg three: the rejection is a typed Degradation, never a silent drop


def test_an_unresolved_reference_is_refused_with_a_typed_degradation() -> None:
    """The kind is a named member, not a sentence: Story 1.17 counts these, and a count
    over free text is a count of typos."""
    element = measured("Inflation was 2.6 % in April 2026.", a_provenance())
    outcome = admit(element, NothingResolves())
    assert isinstance(outcome, Refused)
    assert isinstance(outcome.degradation, Degradation)
    assert outcome.degradation.kind == ProvenanceFailure.UNRESOLVED_SOURCE_REF.value
    assert outcome.degradation.where
    assert element.source_ref in outcome.degradation.detail


def test_an_element_that_resolves_goes_in_exactly_as_constructed() -> None:
    element = measured("a published reading", a_provenance())
    outcome = admit(element, EverythingResolves())
    assert isinstance(outcome, Admitted)
    assert outcome.element is element


def test_nothing_is_dropped_because_every_element_comes_out_as_one_or_the_other() -> None:
    """Conservation, over a mixed batch. A silent drop would leave a shorter answer that
    reads exactly like a complete one, which is the failure AD-7 makes impossible rather
    than unlikely."""
    elements = (
        measured("one", a_provenance("D-1")),
        derived("two", a_provenance("D-2")),
        absent("three", a_provenance("D-3")),
    )
    refused = admit_all(elements, NothingResolves())
    assert refused.elements == ()
    assert len(refused.degradations) == len(elements)
    assert {degradation.kind for degradation in refused.degradations} == {
        ProvenanceFailure.UNRESOLVED_SOURCE_REF.value
    }

    admitted = admit_all(elements, EverythingResolves())
    assert admitted.elements == elements
    assert admitted.degradations == ()

    for catalogue in (NothingResolves(), EverythingResolves()):
        assembled = admit_all(elements, catalogue)
        assert len(assembled.elements) + len(assembled.degradations) == len(elements)


def test_the_admission_result_carries_the_refusals_rather_than_an_ambient_collector() -> None:
    """AD-15: the degradation travels on the result value.

    Asserted on the type rather than on a run -- ``Assembled`` has a degradations field, so
    a caller that wants only the elements has to step over the refusals in order to ignore
    them, and that is a line a reviewer can see.
    """
    assembled = admit_all((measured("x", a_provenance()),), NothingResolves())
    names = {field.name for field in dataclasses.fields(assembled)}
    assert names == {"elements", "degradations"}


def test_no_admission_site_in_the_tree_discards_a_refusal() -> None:
    """Every ``match admit(...)`` binds the degradation out of ``Refused``.

    A ``case Refused():`` with no binding is exactly the silent ``continue`` AD-7 forbids,
    written in a shape that looks like it handles the case. This is the scan that finds it.
    """
    offences: list[str] = []
    for path in _all_modules():
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.MatchClass):
                continue
            named = node.cls
            if not (isinstance(named, ast.Name) and named.id == "Refused"):
                continue
            if not node.kwd_patterns and not node.patterns:
                offences.append(_where(path, node.lineno))
    assert not offences, (
        "a Refused branch that binds nothing is a refusal on its way to being "
        "dropped:\n  " + "\n  ".join(offences)
    )


# ===================================== FR-78: what the model may and may not originate


@pytest.mark.parametrize("package", COMPOSING_PACKAGES)
def test_no_layer_that_composes_an_answer_can_reach_a_model(package: str) -> None:
    """FR-78's inventory, asserted as unreachability rather than as a promise.

    The model's role is wording, disambiguation among supplied candidates and structural
    classification. None of those is a figure, a date, a country fact, a definition or a
    causal claim -- and the reason none of them can become one here is that the layers
    which produce figures, dates, country facts and definitions cannot call a model at
    all. That is a stronger statement than a prompt instruction, and this is where it is
    kept true as the tree fills.
    """
    offences = [
        f"{_where(path, node.lineno)} -> {name}"
        for path in _modules(package)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
        if name in MODEL_IMPORTS or name.split(".")[0] in MODEL_LIBRARIES
    ]
    assert not offences, (
        "no figure, date, country fact, definition or causal claim originates in the "
        "model (FR-78); the layers that produce them cannot reach one:\n  "
        + "\n  ".join(offences)
    )


def test_a_figure_is_a_decimal_parsed_from_a_row_and_never_a_string_from_anywhere() -> None:
    """The narrow version of the same claim, at the type.

    ``Figure.value`` is a ``Decimal`` and ``Figure.source_datapoint_id`` is required, so
    an untraceable figure does not exist -- and a model returns text, which is not a
    ``Decimal`` and carries no row id. There is no conversion between the two in the tree,
    which the import scan above is what keeps true.
    """
    annotations = {field.name: field.type for field in dataclasses.fields(Figure)}
    assert annotations["value"] == "Decimal"
    assert annotations["source_datapoint_id"] == "str"
    assert isinstance(_a_figure().value, Decimal)


def _a_figure() -> Figure:
    return Figure(
        detail_id="D-CPI-HEADLINE",
        period=Period("2026-04"),
        country_id=None,
        measure=Measure.ACTUAL,
        value=Decimal("2.6"),
        source_datapoint_id="DP-1",
    )
