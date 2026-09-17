"""Stories 9.1 and 9.5 -- the source admission set, and the agent every answer declares.

Two properties, each asserted twice: once on the values as they run, and once as a scan
that keeps biting as the tree fills.

1. **The three-way choice is a closed type, not three routing paths** (9.1, AD-10, AD-24,
   FR-82). ``SourceAdmission`` has exactly three inhabitants -- ``{Approved}``,
   ``{External}``, ``{Approved, External}`` -- and no fourth is constructible. One answer
   path serves all three, the approved package is composed by the same call in every case
   that admits it, and the engine's only authorisation is membership of the set. A
   selection outside it is a 4xx, never a silent narrowing to whatever the engine could
   have served: FR-82's *"never silently answered by a source I did not choose"* read from
   the other end.

2. **Every answer declares its agent, visibly** (9.5, FR-83, FR-52, AD-6). The
   declaration is rendered, reader-facing content carried **on the package**, in the
   reader's own language, and it is not an element -- so it has no role, no lens can
   filter it, and the Executive Lens cannot shorten it away. An external element's class
   is ``External``, set at construction and immutable, and third-party content stays its
   own labelled package beside the approved one rather than being merged into it.

**What is deliberately not asserted here.** The knowledge base excludes indicators marked
``Confidential``, and that exclusion cannot be evidenced from this export: the type exists
in ``P13_Ref_IndicatorPriorityTypes`` and the export carries 105 ``Priority``, 84 blank and
**zero** confidential rows in both layers. A test asserting "no confidential indicator is
answered" would pass over an empty set and would keep passing if the exclusion were
deleted. It is left unwritten on purpose; the exclusion is Story 1.6's ``CHECK``, and it
needs an export that contains one before a test of it means anything.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI

from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.readmodel.startup import engine_for
from askai.adapters.store.provision import Databases, provision
from askai.api.app import ASK_ROUTE, AskRequest, create_app
from askai.api.ask import Ask, answer_question
from askai.api.engine import Engine
from askai.api.wire import package_block
from askai.assemble.roles import Lens, Placement, Role
from askai.compile.binder import CompileInput, compile_question
from askai.domain.admission import AdmissionError, PackageSource, SourceAdmission
from askai.domain.element import Element, ElementClass
from askai.messages import Catalogue, Lang, load_catalogue
from askai.narrate.package import AnswerPackage, PackageKind
from askai.narrate.structured import declare_agent, external_package
from askai.rules import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: The moment every request here is answered at. Fixed, because ``today`` is an input to
#: compiling (AD-17) and a test that read the clock would bind a different period daily.
MOMENT: Final = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

#: One detail is named exactly this in the whole catalogue (DATA-CONTRACT FACT 6).
INFLATION: Final = "Inflation"

#: The module that joins the five steps of the answer path. One path, and the scans
#: below assert it stays one.
ASK_MODULE: Final = PACKAGE_ROOT / "api" / "ask.py"


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def databases() -> Iterator[Databases]:
    with provision() as estate:
        ingest_published_layer(estate.read_model, CmsExport.rooted(EXPORT_ROOT))
        yield estate


@pytest.fixture(scope="module")
def state_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("estate") / "refresh_state.json"


@pytest.fixture(scope="module")
def engine(databases: Databases, state_file: Path) -> Engine:
    return engine_for(databases, state_file, now=lambda: MOMENT)


@pytest.fixture(scope="module")
def app(engine: Engine) -> FastAPI:
    return create_app(engine)


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def placement() -> Placement:
    return Placement(rule_set=rules())


def call(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://engine") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(go())


def answered(engine: Engine, admission: SourceAdmission, lang: Lang = Lang.EN) -> AnswerPackage:
    """The first package for a real question under *admission*, through the real path."""
    return packages(engine, admission, lang)[0]


def packages(
    engine: Engine, admission: SourceAdmission, lang: Lang = Lang.EN
) -> tuple[AnswerPackage, ...]:
    result = answer_question(
        engine,
        Ask(question=f"What is {INFLATION} now?", lang=lang, sources=admission),
    )
    return result.response.packages


def _parse(path: Path) -> ast.Module:
    """Parse *path*, tolerating one that vanished between the walk and the read.

    ``tests/test_dependency_contracts.py`` plants a module under ``src/askai/`` and
    removes it again, so a tree-wide walk can list a file that is gone a moment later.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        source = ""
    return ast.parse(source, filename=str(path))


def _modules(package: str) -> list[Path]:
    return sorted(
        path
        for path in (PACKAGE_ROOT / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


# ============================================================ 9.1 -- the admission set


def test_the_admission_set_has_exactly_three_inhabitants() -> None:
    """``{Approved}``, ``{External}``, ``{Approved, External}``, and nothing else.

    Asserted over the *sets* rather than over the member names, because the names are
    spelling and the sets are the contract. Four subsets exist over two sources; the type
    admits three of them, and the one it leaves out is the empty selection.
    """
    assert len(list(SourceAdmission)) == 3
    assert {frozenset(admission.admits) for admission in SourceAdmission} == {
        frozenset({PackageSource.APPROVED}),
        frozenset({PackageSource.EXTERNAL}),
        frozenset({PackageSource.APPROVED, PackageSource.EXTERNAL}),
    }


def test_there_is_no_fourth_inhabitant_to_construct() -> None:
    """The closure is a property of the type, not a check someone remembers to run."""
    with pytest.raises(ValueError):
        SourceAdmission("approved+oxford")
    with pytest.raises(ValueError):
        SourceAdmission("")


def test_selecting_nothing_names_none_of_the_three_and_is_refused() -> None:
    """Selecting no source is not a narrower question; it is no question."""
    with pytest.raises(AdmissionError, match="not one of the three admissions"):
        SourceAdmission.of(())


def test_a_selection_outside_the_set_is_refused_rather_than_narrowed() -> None:
    """FR-82, at the type. Narrowing would be the engine choosing the reader's agent."""
    with pytest.raises(AdmissionError):
        SourceAdmission.of((PackageSource.APPROVED, "oxford"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        ((PackageSource.APPROVED,), SourceAdmission.APPROVED_ONLY),
        ((PackageSource.EXTERNAL,), SourceAdmission.EXTERNAL_ONLY),
        (
            (PackageSource.EXTERNAL, PackageSource.APPROVED),
            SourceAdmission.BOTH,
        ),
        (
            (PackageSource.APPROVED, PackageSource.APPROVED),
            SourceAdmission.APPROVED_ONLY,
        ),
    ],
)
def test_order_and_repetition_are_not_part_of_a_selection_s_identity(
    selected: tuple[PackageSource, ...], expected: SourceAdmission
) -> None:
    assert SourceAdmission.of(selected) is expected


def test_the_request_carries_the_admission_and_never_a_loose_tuple() -> None:
    """``Ask.sources`` is the closed type, so nothing downstream re-validates it."""
    annotations = {field.name: field.type for field in dataclasses.fields(Ask)}
    assert annotations["sources"] == "SourceAdmission"


def test_combined_admits_approved_first(app: FastAPI) -> None:
    """The construction order and the return order agree (FR-84)."""
    assert SourceAdmission.BOTH.admits == (PackageSource.APPROVED, PackageSource.EXTERNAL)
    payload = ask(app, sources=["external", "approved"])
    assert [package["provenance"] for package in payload["packages"]] == [
        "approved",
        "external",
    ]


def ask(app: FastAPI, **body: Any) -> dict[str, Any]:
    response = call(
        app,
        "POST",
        ASK_ROUTE,
        json={"question": f"What is {INFLATION} now?", "lang": "en", **body},
    )
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_the_wire_still_takes_a_list_of_source_names(app: FastAPI) -> None:
    """The client's vocabulary is unchanged; what changed is what it is parsed into."""
    schema = call(app, "GET", "/openapi.json").json()
    published = schema["components"]["schemas"]["AskRequest"]
    assert "sources" in published["properties"]
    assert set(AskRequest.model_fields) == {"question", "lang", "sources", "conversation_id"}
    assert AskRequest(question="x", lang=Lang.EN).admission is SourceAdmission.APPROVED_ONLY


@pytest.mark.parametrize(
    "sources",
    [[], ["oxford"], ["approved", "oxford"], ["approved", ""], ["APPROVED"]],
)
def test_an_unadmissible_selection_is_a_4xx_and_produces_no_answer(
    app: FastAPI, sources: list[str]
) -> None:
    """A 4xx, never a 200 over a narrower set. Both halves matter: the status says the
    request was refused, and the absence of a body says nothing was answered anyway."""
    response = call(
        app,
        "POST",
        ASK_ROUTE,
        json={"question": "x", "lang": "en", "sources": sources},
    )
    assert 400 <= response.status_code < 500, response.text
    assert "packages" not in response.json()


def test_the_approved_package_is_composed_identically_whether_or_not_external_is_admitted(
    engine: Engine,
) -> None:
    """9.1's load-bearing clause: **no Combined-specific composition**.

    Value equality over the whole frozen package -- elements, row ids, rules fired,
    resolution, degradations and the agent declaration. A Combined-specific path would
    have to differ in one of those to be worth having, so equality here is the absence of
    one rather than evidence that the two paths happen to agree today.
    """
    alone = answered(engine, SourceAdmission.APPROVED_ONLY)
    beside_external = answered(engine, SourceAdmission.BOTH)
    assert alone == beside_external
    assert alone.kind is PackageKind.ANSWER


def test_the_external_half_is_the_same_package_whether_or_not_approved_is_admitted(
    engine: Engine,
) -> None:
    """The symmetric half of the same clause, so neither side acquires a special case."""
    alone = answered(engine, SourceAdmission.EXTERNAL_ONLY)
    beside_approved = packages(engine, SourceAdmission.BOTH)[1]
    assert alone == beside_approved
    assert alone.source is PackageSource.EXTERNAL


def test_one_package_per_admitted_source_and_never_more(engine: Engine) -> None:
    for admission in SourceAdmission:
        built = packages(engine, admission)
        assert [package.source for package in built] == list(admission.admits)


def test_the_answer_path_has_no_branch_naming_a_particular_admission() -> None:
    """*"Provenance separation is a type invariant rather than a rule each path must
    remember"* -- asserted as the absence of the paths.

    The predecessor had three routing paths with three sets of guards. A path here would
    show up as ``api/ask.py`` naming an admission member, or as a second call to the
    approved composer. Neither exists: the loop reads ``admits`` and dispatches per
    source, so Combined is the *same* code with a longer tuple.
    """
    tree = _parse(ASK_MODULE)
    named = sorted(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "SourceAdmission"
    )
    assert named == [], f"api/ask.py branches on a particular admission: {named}"
    approved_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_approved"
    ]
    assert len(approved_calls) == 1, (
        "the approved package is composed at exactly one site; a second call is a "
        f"Combined-specific composition waiting to drift: lines {approved_calls}"
    )


def test_the_branch_scan_would_catch_a_combined_special_case() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse(
        "def packages(ask):\n"
        "    if ask.sources is SourceAdmission.BOTH:\n"
        "        return _approved_for_combined(ask)\n"
        "    return _approved(ask)\n"
    )
    assert [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "SourceAdmission"
    ] == ["BOTH"]


def test_the_only_authorisation_the_engine_performs_is_membership() -> None:
    """AD-24. The engine authenticates nothing and owns no per-caller source policy.

    Asserted as the absence of the alternative: nothing under ``api/`` reads the asserted
    caller identity while deciding which sources to answer from. The identity reaches
    ``observability/`` and stops there.
    """
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in _modules("api")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and "source" in node.name
        for inner in ast.walk(node)
        if isinstance(inner, ast.Attribute) and "identity" in inner.attr
    ]
    assert not offences, (
        "the engine's only authorisation is that `sources` is within the closed set "
        "(AD-24); a source decision that reads a caller is an access decision the "
        "surrounding platform already made:\n  " + "\n  ".join(offences)
    )


# ====================================================== 9.5 -- every answer declares its agent


@pytest.mark.parametrize("lang", list(Lang))
@pytest.mark.parametrize("admission", list(SourceAdmission))
def test_every_package_declares_its_agent_in_the_readers_language(
    engine: Engine, catalogue: Catalogue, admission: SourceAdmission, lang: Lang
) -> None:
    """FR-83, over every admission and both languages, with no exception for a refusal."""
    for package in packages(engine, admission, lang):
        assert package.agent.strip()
        assert package.agent == declare_agent(catalogue, lang, package.source)


def test_the_two_languages_declare_the_agent_in_their_own_words(
    catalogue: Catalogue,
) -> None:
    """Authored in each half of the catalogue (FR-63), never one translated from the
    other -- and never the same string served to both readers."""
    for source in PackageSource:
        english = declare_agent(catalogue, Lang.EN, source)
        arabic = declare_agent(catalogue, Lang.AR, source)
        assert english and arabic and english != arabic


def test_the_approved_and_external_declarations_are_not_interchangeable(
    catalogue: Catalogue,
) -> None:
    """A reader is told *which* agent, not merely that there was one."""
    for lang in Lang:
        assert declare_agent(catalogue, lang, PackageSource.APPROVED) != declare_agent(
            catalogue, lang, PackageSource.EXTERNAL
        )


def test_a_package_cannot_be_built_without_declaring_its_agent(
    engine: Engine,
) -> None:
    """Carried by the type, so there is no package anywhere that declares nothing."""
    package = answered(engine, SourceAdmission.APPROVED_ONLY)
    with pytest.raises(ValueError, match="declares the agent"):
        dataclasses.replace(package, agent="")
    with pytest.raises(ValueError, match="declares the agent"):
        dataclasses.replace(package, agent="   ")


def test_the_declaration_is_package_content_and_not_an_element(
    engine: Engine, placement: Placement
) -> None:
    """Why it is a field and not an element, stated as an assertion.

    An element has a role, a role decides which lens shows it, and the Executive Lens
    exists to be short. The declaration is carried on the package, so there is no role to
    place it under and therefore no lens that could drop it -- which is what *"in both
    lenses"* means structurally rather than by a table entry someone could edit.
    """
    package = answered(engine, SourceAdmission.APPROVED_ONLY)
    assert package.agent not in [placed.element.content for placed in package.elements]
    assert "agent" in {field.name for field in dataclasses.fields(AnswerPackage)}
    assert package.agent not in {role.value for role in Role}
    # Every lens shows a subset of the roles; none of them can name a thing that is not
    # a role, so the declaration survives whichever lens the reader is in.
    for lens in Lens:
        assert placement.roles_in(lens) <= set(Role)


def test_the_declaration_survives_the_shortest_lens(
    engine: Engine, placement: Placement
) -> None:
    """The Executive Lens drops roles. It still cannot reach the declaration."""
    package = answered(engine, SourceAdmission.APPROVED_ONLY)
    executive = tuple(
        placed
        for placed in package.elements
        if placement.shows(Lens.EXECUTIVE, placed.role)
    )
    assert len(executive) <= len(package.elements)
    assert package.agent.strip()


def test_the_wire_carries_the_declaration_beside_the_provenance_code(
    engine: Engine,
) -> None:
    """Two fields: the code a client routes on, and the sentence a reader reads."""
    package = answered(engine, SourceAdmission.APPROVED_ONLY)
    block = package_block(package)
    assert block["provenance"] == PackageSource.APPROVED.value
    assert block["agent"] == package.agent


def test_the_route_returns_the_declaration_for_every_package(app: FastAPI) -> None:
    payload = ask(app, sources=["approved", "external"])
    assert len(payload["packages"]) == 2
    for package in payload["packages"]:
        assert package["agent"].strip()
    assert payload["packages"][0]["agent"] != payload["packages"][1]["agent"]


def test_an_external_element_is_class_external_set_at_construction(
    engine: Engine,
) -> None:
    """AD-6: the class is set at construction and is immutable, so it is the class the
    element dies with. There is no setter, no ``with_class`` and no re-labelling."""
    element = Element(
        content="a third-party statement",
        element_class=ElementClass.EXTERNAL,
        source_ref="external|oxford",
    )
    assert element.element_class is ElementClass.EXTERNAL
    with pytest.raises(dataclasses.FrozenInstanceError):
        element.element_class = ElementClass.MEASURED  # type: ignore[misc]


def test_third_party_content_is_a_separate_labelled_package_never_merged(
    engine: Engine,
) -> None:
    """FR-52 and AD-10. Two packages, each labelled, and no approved figure among the
    external one's rows -- the reader can always see which half is which."""
    approved, external = packages(engine, SourceAdmission.BOTH)
    assert approved.source is PackageSource.APPROVED
    assert external.source is PackageSource.EXTERNAL
    assert approved is not external
    # The unconditional caveat is what stops external content reading as approved.
    assert external.caveat
    assert approved.caveat is None
    # No published row is claimed by the external half, and no external element has
    # found its way into the approved one.
    assert external.row_ids == ()
    assert all(
        placed.element.element_class is not ElementClass.EXTERNAL
        for placed in approved.elements
    )


def test_an_unwired_external_agent_still_declares_itself(
    engine: Engine, catalogue: Catalogue
) -> None:
    """The gap is stated as its own package (AD-15), and it says whose gap it is."""
    compiled = compile_question(
        CompileInput(question=f"What is {INFLATION} now?", today=MOMENT.date()), engine.names
    )
    package = external_package(compiled, catalogue, Lang.AR)
    assert package.source is PackageSource.EXTERNAL
    assert package.agent == declare_agent(catalogue, Lang.AR, PackageSource.EXTERNAL)
    assert package.kind is PackageKind.REFUSAL


def test_the_read_model_is_the_only_thing_the_approved_half_reads(
    databases: Databases,
) -> None:
    """A guard on the fixture rather than on the code: the approved answers above came
    out of the real ingested export, so the equality assertions are over real rows."""
    connection: sqlite3.Connection = databases.read_model
    (rows,) = connection.execute("SELECT COUNT(*) FROM datapoint").fetchone()
    assert rows > 0
