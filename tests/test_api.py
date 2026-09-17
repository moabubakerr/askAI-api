"""Story 1.15 -- ``POST /api/ask`` returns the structured answer package.

This is the integration story, so the acceptance that matters is an end-to-end one: a
real question, against the real ingested export, through the real FastAPI application,
returning a real figure with its unit, period, country scope and publishing source --
and writing exactly one answer record while doing it. Everything below either is that
test or guards one of the decisions the route rests on.

Four of those decisions are asserted structurally rather than behaviourally, because each
is a property of the code rather than of a response:

* **Only ``narrate/`` constructs an ``AnswerPackage``** (AD-10). Scanned, because the
  ``import-linter`` contract stops ``respond/`` *importing* the builder and a scan is what
  catches a second builder appearing somewhere the contract does not cover.
* **``respond/`` never reaches inside a package.** Its functions are generic over an
  opaque type, so the test hands them objects that are not packages at all -- if they
  worked by reading a field, they would not work on these.
* **The request carries no lens** (AD-23), asserted against the schema the app publishes
  rather than against the dataclass, because the schema is what a client sees.
* **No model client is on the answer path** (FR-55). Trivially true in this epic, scanned
  so that it stops being trivial loudly.

The application is driven over ASGI on the calling thread. That is not a shortcut around
HTTP: routing, validation, the response model and JSON serialisation all run. It is how a
sqlite estate is tested at all -- a connection belongs to the thread that opened it, and
a test client that dispatches into a worker thread would hand the read model to a thread
sqlite refuses to serve.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI

from askai.adapters.readmodel.catalogue import ReadModelSources, read_model_snapshot
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.readmodel.reachability import SqliteStoreHealth
from askai.adapters.readmodel.startup import engine_for
from askai.adapters.store.provision import Databases, provision
from askai.api.app import ASK_ROUTE, HEALTH_ROUTE, IDENTITY_HEADER, AskRequest, create_app
from askai.api.engine import READ_MODEL_STORE, RECORD_STORE, Engine
from askai.compile.binder import CompileInput, compile_question
from askai.domain.element import ElementClass
from askai.domain.normalise import normalise
from askai.messages import Lang
from askai.narrate.package import AnswerPackage, Chartable, PackageKind, PackageSource
from askai.narrate.structured import external_package
from askai.respond.order import OrderingError, concatenate, ordered
from askai.respond.response import Response
from askai.rules.countries import country_aliases

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: The moment every request in this module is answered at. Fixed, because ``today`` is an
#: input to compiling (AD-17) and a test that read the clock would bind a different period
#: every day. It is the date Story 1.12 measured FR-8 against.
MOMENT: Final = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

#: One detail is named exactly this in the whole catalogue (DATA-CONTRACT FACT 6), it
#: publishes 863 rows across all three grains, and its newest monthly actual is 2026-04.
INFLATION: Final = "Inflation"
INFLATION_PERIOD: Final = "2026-04"

#: The packages an answer may be made of, and the layer allowed to make one.
NARRATE_ROOT: Final = PACKAGE_ROOT / "narrate"
ANSWER_PATH_PACKAGES: Final = ("api", "narrate", "respond")

#: A model client under any of the names one arrives under (FR-55, AD-3, AD-22).
MODEL_LIBRARIES: Final = frozenset(
    {"openai", "anthropic", "langchain", "ollama", "llama_index", "cohere", "boto3"}
)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def databases() -> Iterator[Databases]:
    """The real export, ingested into databases this same schema step built.

    In memory, per module: NFR-6 wants the whole answer path exercised with no database
    service, no directory and no environment variable, and this is what that looks like.
    """
    with provision() as estate:
        ingest_published_layer(estate.read_model, CmsExport.rooted(EXPORT_ROOT))
        yield estate


@pytest.fixture(scope="module")
def state_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where the refresh state would live. Absent, so every answer reports never-refreshed."""
    return tmp_path_factory.mktemp("estate") / "refresh_state.json"


@pytest.fixture(scope="module")
def engine(databases: Databases, state_file: Path) -> Engine:
    return engine_for(databases, state_file, now=lambda: MOMENT)


@pytest.fixture(scope="module")
def app(engine: Engine) -> FastAPI:
    return create_app(engine)


@pytest.fixture(scope="module")
def a_package(engine: Engine) -> AnswerPackage:
    """One real package, built by the only layer allowed to build one."""
    compiled = compile_question(
        CompileInput(question=f"What is {INFLATION} now?", today=MOMENT.date()), engine.names
    )
    return external_package(compiled, engine.messages, Lang.EN)


def call(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    """One request through the real application, on this thread."""

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://engine") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(go())


def ask(app: FastAPI, question: str, **body: Any) -> dict[str, Any]:
    response = call(app, "POST", ASK_ROUTE, json={"question": question, "lang": "en", **body})
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def records(databases: Databases) -> list[sqlite3.Row]:
    cursor = databases.record_store.execute("SELECT * FROM record ORDER BY rowid")
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]  # type: ignore[misc]


# -------------------------------------------------- the acceptance: a real question


def test_a_real_question_returns_a_real_figure_with_its_provenance(
    app: FastAPI, databases: Databases
) -> None:
    """The epic's goal, end to end: *"one correct figure with its unit, period, country
    scope and publishing source -- defensible in front of the Council."*

    Nothing here is a fixture shaped like the export. The figure came out of a row the
    ingest wrote from the committed CMS files, by exact key, through the real route.
    """
    before = len(records(databases))
    payload = ask(app, f"What is {INFLATION} now?")

    assert set(payload) == {"conversation_id", "packages", "freshness"}
    package = payload["packages"][0]
    assert package["provenance"] == PackageSource.APPROVED.value
    assert package["kind"] == PackageKind.ANSWER.value

    headline = next(element for element in package["elements"] if element["role"] == "headline")
    # The unit is the detail's published one and the period is written in the language's
    # own period form -- both composed server-side, neither a spec dump.
    assert "2.6" in headline["text"]
    assert "%" in headline["text"]
    assert "April 2026" in headline["text"]
    assert INFLATION in headline["text"]

    # The country scope: national, which is the *absence* of a country (AD-5), so the
    # source_ref's country segment is empty and the home country is named nowhere.
    assert package["spec"]["country_scope"] == {"bound": "national"}
    detail_id, period, country, source_id = headline["source_ref"].split("|")
    assert period == INFLATION_PERIOD
    assert country == ""
    assert detail_id and source_id

    # ...and exactly one record was written for it.
    assert len(records(databases)) == before + 1


def test_the_figure_is_traceable_to_the_row_it_came_from(
    app: FastAPI, databases: Databases
) -> None:
    """AD-3: *"a number that cannot be traced to a row does not exist."*

    The reference on the element resolves against the loaded published layer through the
    same port ``assemble/`` admitted it with, and the row ids on the record name the
    datapoint the figure was read from.
    """
    payload = ask(app, f"What is {INFLATION} now?")
    elements = payload["packages"][0]["elements"]
    headline = next(element for element in elements if element["role"] == "headline")
    assert ReadModelSources(connection=databases.read_model).resolves(headline["source_ref"])

    written = json.loads(records(databases)[-1]["answer_json"])
    assert written["row_ids"], "the record names the published rows the answer used"
    detail_id, period, _country, _source = headline["source_ref"].split("|")
    stored = databases.read_model.execute(
        "SELECT source_datapoint_id FROM datapoint "
        "WHERE detail_id = ? AND period = ? AND country_id IS NULL",
        (detail_id, period),
    ).fetchone()
    assert stored is not None
    assert written["row_ids"] == [stored[0]]


def test_the_period_the_answer_used_is_the_one_execute_resolved_latest_to(
    app: FastAPI,
) -> None:
    """FR-8 and AD-1: the request stays ``Latest``; what it resolved to is reported beside
    it, so the answer and the audit state one period rather than each deciding one."""
    spec = ask(app, f"What is {INFLATION} now?")["packages"][0]["spec"]
    assert spec["period"] == {"deferred": {"latest": True}}
    assert spec["resolved_period"] == INFLATION_PERIOD


def test_the_answer_states_what_it_did(app: FastAPI) -> None:
    """FR-56: every answer carries an element of role ``scope``, in both lenses."""
    elements = ask(app, f"What is {INFLATION} now?")["packages"][0]["elements"]
    scope = next(element for element in elements if element["role"] == "scope")
    assert scope["text"] == "monthly, National, April 2026"
    assert scope["class"] == ElementClass.DERIVED.value


def test_the_same_question_answers_in_arabic_when_asked_in_arabic(app: FastAPI) -> None:
    """FR-61 and FR-63: Arabic is a first-class path, not a translation at the edge."""
    english = ask(app, f"What is {INFLATION} now?")["packages"][0]["elements"][0]["text"]
    arabic = ask(app, f"What is {INFLATION} now?", lang="ar")["packages"][0]["elements"][0]["text"]
    assert english != arabic
    assert "April" not in arabic
    # Arabic decimal separator and Arabic-Indic digits, from the catalogue's own numerals.
    assert "2.6" not in arabic
    assert "April 2026" in english


# ------------------------------------------------------------------ the response shape


def test_the_request_carries_no_lens_parameter(app: FastAPI) -> None:
    """AD-23: the lens is a view over one answer, never an input to it.

    Asserted against the schema the application publishes, because that is what a client
    reads -- a field absent from the dataclass but present in the schema would still be
    an input someone could send.
    """
    assert "lens" not in AskRequest.model_fields
    schema = call(app, "GET", "/openapi.json").json()
    published = schema["components"]["schemas"]["AskRequest"]
    assert set(published["properties"]) == {"question", "lang", "sources", "conversation_id"}
    body = schema["paths"][ASK_ROUTE]["post"]
    assert "parameters" not in body or not [
        parameter for parameter in body["parameters"] if parameter["name"] == "lens"
    ]


def test_the_request_shape_is_the_spine_s(app: FastAPI) -> None:
    assert set(AskRequest.model_fields) == {"question", "lang", "sources", "conversation_id"}


def test_every_element_carries_both_a_class_and_a_role_as_two_fields(app: FastAPI) -> None:
    """AD-6: the two axes are independent and must stay so.

    ``class`` asks where the content came from; ``role`` asks what job it does. They are
    two fields on the wire, and the pair that proves independence is here: two elements
    of *different* classes in the same answer, one of which shares its role with nothing.
    """
    elements = ask(app, f"What is {INFLATION} now?")["packages"][0]["elements"]
    assert elements
    for element in elements:
        assert set(element) == {"class", "role", "text", "source_ref"}
        assert element["class"] in set(ElementClass)
        assert element["source_ref"].strip()
    classes = {element["class"] for element in elements}
    roles = {element["role"] for element in elements}
    assert len(classes) > 1 and len(roles) > 1


def test_the_spec_block_is_echoed_with_the_mechanism_that_bound_each_field(
    app: FastAPI,
) -> None:
    """AD-1 and AD-19: one artifact, several jobs -- the corpus asserts on this block and
    the record stores it, so it carries how each field reached its value."""
    spec = ask(app, f"What is {INFLATION} now?")["packages"][0]["spec"]
    assert spec["spec_version"] == 1
    assert spec["bound_by"] == {
        "detail": "named-in-question",
        "period": "named-in-question",
        "country_scope": "rule-default",
        "measure": "rule-default",
        "operation": "rule-default",
    }


def test_the_freshness_block_is_on_the_answer_and_on_health_and_they_agree(
    app: FastAPI,
) -> None:
    """NFR-7 and AD-21: one port, read for both, so they cannot disagree about the copy."""
    answered = ask(app, f"What is {INFLATION} now?")["freshness"]
    checked = call(app, "GET", HEALTH_ROUTE).json()["freshness"]
    assert answered == checked
    assert set(answered) == {"refreshed_at", "stale", "age_seconds"}
    # No refresh has ever succeeded against this read model, which is stale rather than
    # fresh-by-default: an empty copy is not an up-to-date one.
    assert answered == {"refreshed_at": None, "stale": True, "age_seconds": None}


def test_a_conversation_id_is_echoed_and_one_is_minted_when_none_is_sent(
    app: FastAPI,
) -> None:
    """The engine owns no session store (AD-24); it carries the thread the client keeps."""
    assert ask(app, f"What is {INFLATION} now?", conversation_id="c-9")["conversation_id"] == "c-9"
    minted = ask(app, f"What is {INFLATION} now?")["conversation_id"]
    assert minted and minted != ask(app, f"What is {INFLATION} now?")["conversation_id"]


def test_combined_sources_differ_only_by_returning_two_packages(app: FastAPI) -> None:
    """The spine's contract, and AD-10's refusal to merge them.

    The external half is unreachable in this build, so it is returned as its *own*
    package saying so -- never blended into the approved one, which is what would hide
    which half is missing (AD-15).
    """
    payload = ask(app, f"What is {INFLATION} now?", sources=["external", "approved"])
    assert [package["provenance"] for package in payload["packages"]] == ["approved", "external"]
    approved, external = payload["packages"]
    assert approved["kind"] == PackageKind.ANSWER.value
    assert approved["caveat"] is None
    # FR-84, FR-88: the caveat on external content is unconditional.
    assert external["caveat"]
    assert external["degradations"][0]["kind"] == "external_agent_unavailable"


def test_a_repeated_source_selection_is_answered_once(app: FastAPI) -> None:
    payload = ask(app, f"What is {INFLATION} now?", sources=["approved", "approved"])
    assert len(payload["packages"]) == 1


def test_selecting_no_source_is_refused_rather_than_answered_as_a_default(
    app: FastAPI,
) -> None:
    response = call(
        app, "POST", ASK_ROUTE, json={"question": "x", "lang": "en", "sources": []}
    )
    assert response.status_code == 422


# ------------------------------------------------- structured only, and no generated prose


def test_a_package_carries_composed_elements_and_no_prose(app: FastAPI) -> None:
    """This epic ships structured-only answers, and NFR-8 makes that permanent.

    There is no ``prose`` key waiting to be filled: a client reading this JSON must not
    be able to mistake the absence of generated prose for a fault, because it is the
    state the system falls back to whenever the model is unavailable.
    """
    package = ask(app, f"What is {INFLATION} now?")["packages"][0]
    assert set(package) == {
        "provenance",
        "agent",
        "kind",
        "spec",
        "elements",
        "chartable",
        "caveat",
        "reason",
        "degradations",
    }
    assert package["elements"]


@pytest.mark.parametrize("package", ANSWER_PATH_PACKAGES)
def test_no_model_client_is_imported_on_the_answer_path(package: str) -> None:
    """FR-55/AD-3 asserted while it is trivially true, so it stops being so loudly."""
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules(package)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
        if name.split(".")[0] in MODEL_LIBRARIES
    ]
    assert not offences, "Epic 1 makes no model call: " + ", ".join(offences)


# --------------------------------------------------- only narrate constructs a package


def test_only_narrate_constructs_an_answer_package() -> None:
    """AD-10, as a scan. The ``import-linter`` contract stops ``respond/`` importing the
    builder; this catches a second builder appearing anywhere else in the tree."""
    built = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "AnswerPackage"
    ]
    assert built, "a scan that finds nothing proves nothing"
    assert all(place.startswith("narrate/") for place in built), built


def test_the_package_type_is_declared_once_and_in_narrate() -> None:
    definitions = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ClassDef) and node.name == "AnswerPackage"
    ]
    assert len(definitions) == 1
    assert definitions[0].startswith("narrate/package.py")


def test_respond_imports_neither_narrate_nor_assemble() -> None:
    """The contract in ``pyproject.toml`` says it; this says which module broke it."""
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules("respond")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
        if name.startswith(("askai.narrate", "askai.assemble"))
    ]
    assert not offences, offences


def test_a_package_cannot_be_mutated(a_package: AnswerPackage) -> None:
    """Frozen, and every field a tuple: ``respond/`` could not mutate one if it tried."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        a_package.kind = PackageKind.REFUSAL  # type: ignore[misc]


def test_an_external_package_cannot_exist_without_its_caveat(
    a_package: AnswerPackage,
) -> None:
    """FR-84 and FR-88: unconditional means the type refuses one without it."""
    assert a_package.source is PackageSource.EXTERNAL
    with pytest.raises(ValueError, match="caveat unconditionally"):
        dataclasses.replace(a_package, caveat=None)


def test_a_package_that_is_not_chartable_names_no_views() -> None:
    with pytest.raises(ValueError, match="names no views"):
        Chartable(available=False, default_view="line")


# ------------------------------------------- respond orders, and never reaches inside


def test_respond_orders_objects_it_cannot_look_inside() -> None:
    """AD-10's *"order and concatenate, never reach inside"*, as a property of the code.

    The things being ordered here are not packages and have no fields at all. If
    ``ordered`` worked by reading a package's ``source``, it could not order these -- so
    passing is evidence that it does not.
    """
    first, second, third = object(), object(), object()
    keys = {id(first): "external", id(second): "approved", id(third): "external"}
    arranged = ordered(
        [first, second, third], lambda item: keys[id(item)], ("approved", "external")
    )
    assert arranged == (second, first, third), "stable within a key"
    # Identity, not equality: every package that went in is the same object coming out.
    assert all(a is b for a, b in zip(arranged, (second, first, third), strict=True))


def test_ordering_refuses_a_package_kind_the_order_does_not_place() -> None:
    with pytest.raises(OrderingError, match="does not place"):
        ordered([object()], lambda _item: "partner", ("approved", "external"))


def test_concatenation_combines_nothing() -> None:
    """Two packages saying different things both survive; which to believe is the
    reader's decision and not this layer's."""
    left, right = object(), object()
    assert concatenate([left], [right], [left]) == (left, right, left)


def test_a_response_carries_a_conversation_and_at_least_one_package(
    engine: Engine, a_package: AnswerPackage
) -> None:
    freshness = engine.freshness.freshness(MOMENT)
    with pytest.raises(ValueError, match="at least one package"):
        Response(conversation_id="c-1", packages=(), freshness=freshness)
    with pytest.raises(ValueError, match="conversation id"):
        Response(conversation_id="  ", packages=(a_package,), freshness=freshness)


# ------------------------------------------------------------- identity, AD-24


def test_the_engine_records_the_identity_the_platform_asserted(
    app: FastAPI, databases: Databases
) -> None:
    """AD-24: no authentication, no session store -- the identity is consumed and recorded."""
    response = call(
        app,
        "POST",
        ASK_ROUTE,
        json={"question": f"What is {INFLATION} now?", "lang": "en"},
        headers={IDENTITY_HEADER: "analyst-7"},
    )
    assert response.status_code == 200
    written = records(databases)[-1]
    assert written["caller_id"] == "analyst-7"
    assert written["identity_asserted"] == 1


def test_an_unasserted_identity_is_recorded_as_anonymous_with_that_fact_recorded(
    app: FastAPI, databases: Databases
) -> None:
    """The sharp edge of AD-24. Anonymity is a value with a stated reason, never a NULL
    somebody later has to interpret -- and the request is still answered."""
    ask(app, f"What is {INFLATION} now?")
    written = records(databases)[-1]
    assert written["caller_id"] is None
    assert written["identity_asserted"] == 0
    identity = json.loads(written["answer_json"])["identity"]
    assert identity == {
        "asserted": False,
        "anonymous": True,
        "reason": "no identity asserted by the platform",
    }


def test_a_blank_assertion_is_not_a_weak_identity(app: FastAPI, databases: Databases) -> None:
    """"Nothing arrived" and "something arrived and was empty" mean different things to
    whoever later asks why an answer is not attributable."""
    call(
        app,
        "POST",
        ASK_ROUTE,
        json={"question": f"What is {INFLATION} now?", "lang": "en"},
        headers={IDENTITY_HEADER: "   "},
    )
    reason = json.loads(records(databases)[-1]["answer_json"])["identity"]["reason"]
    assert reason == "the platform asserted a blank identity"


def test_the_engine_establishes_no_identity_of_its_own(app: FastAPI) -> None:
    """AD-24: it owns no session, no login and no user store, so there is nothing to call.

    Scanned for the *imports* an authenticating edge would need rather than for the word
    -- ``PyJWT`` is a dependency of this project for other reasons, and a security scheme
    is something a route declares, not something a docstring mentions.
    """
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules("api")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
        if name.split(".")[0] in {"jwt", "passlib", "hashlib", "secrets"}
        or name in {"HTTPBearer", "OAuth2PasswordBearer", "SecurityScopes", "Security"}
    ]
    assert not offences, offences
    schema = call(app, "GET", "/openapi.json").json()
    assert "securitySchemes" not in schema.get("components", {})
    assert set(schema["paths"]) == {ASK_ROUTE, HEALTH_ROUTE}


# ------------------------------------------------------------------ one record, AD-16


def test_exactly_one_record_is_written_per_request(app: FastAPI, databases: Databases) -> None:
    before = len(records(databases))
    for _ in range(3):
        ask(app, f"What is {INFLATION} now?")
    assert len(records(databases)) == before + 3


def test_the_record_holds_the_spec_the_mechanisms_and_the_rules_that_fired(
    app: FastAPI, databases: Databases
) -> None:
    """AD-16 and FR-74: reconstructible and defensible months later."""
    ask(app, f"What is {INFLATION} now?")
    written = records(databases)[-1]
    spec = json.loads(written["spec_json"])
    answer = json.loads(written["answer_json"])

    assert written["spec_version"] == 1
    assert spec["detail"]["binding"] == "named-in-question"
    assert spec["country_scope"]["binding"] == "rule-default"
    # The single most-asked question of an old answer: what did "now" mean?
    assert spec["period"]["note"] == (
        f"resolved to {INFLATION_PERIOD} by R-LATEST-MOST-RECENT-ACTUAL"
    )
    assert {rule["rule_id"] for rule in answer["rules_fired"]} >= {
        "R-ROLE-FORMAT-MODE",
        "R-LATEST-MOST-RECENT-ACTUAL",
    }
    assert answer["element_count"] == 2
    assert written["question"] == f"What is {INFLATION} now?"
    # Class and provenance, never content: the record does not grow with the answer.
    assert all(set(element) == {"class", "source_ref"} for element in answer["elements"])


def test_the_record_is_written_after_the_package_is_final(
    app: FastAPI, databases: Databases
) -> None:
    """The record describes what was returned, not what was intended.

    Asserted by comparing the two: every element in the response is in the record, by
    its source reference, and the element count agrees.
    """
    payload = ask(app, f"What is {INFLATION} now?")
    answer = json.loads(records(databases)[-1]["answer_json"])
    served = [element["source_ref"] for element in payload["packages"][0]["elements"]]
    assert [element["source_ref"] for element in answer["elements"]] == served


def test_a_record_is_written_for_a_refusal_too(app: FastAPI, databases: Databases) -> None:
    """A question that could not be answered is exactly the one an auditor asks about."""
    before = len(records(databases))
    payload = ask(app, "What is the gross national happiness index?")
    assert payload["packages"][0]["kind"] in {
        PackageKind.REFUSAL.value,
        PackageKind.CLARIFICATION.value,
    }
    assert len(records(databases)) == before + 1


# ----------------------------------------------- refusal, clarification and failure


def test_a_question_naming_no_published_indicator_is_refused_and_says_so(
    app: FastAPI,
) -> None:
    package = ask(app, "What is the gross national happiness index?")["packages"][0]
    assert package["kind"] == PackageKind.REFUSAL.value
    assert package["elements"] == []
    assert package["reason"]
    assert package["spec"]["detail_id"]["unbound"].startswith("no-detail-named")


def test_a_shared_name_is_a_clarification_rather_than_a_guess(
    app: FastAPI, databases: Databases
) -> None:
    """257 of 320 published names are shared, so *"which of these did you mean"* is the
    commonest thing the engine has to say -- and saying "not published" would be false."""
    shared = _a_shared_name(databases)
    package = ask(app, f"What is {shared}?")["packages"][0]
    assert package["kind"] == PackageKind.CLARIFICATION.value
    assert package["reason"]


def test_a_failure_is_never_rendered_as_an_absence(
    databases: Databases, state_file: Path
) -> None:
    """Findings 23, 128 and 150: an error must not read as "no approved figures".

    The read model is closed underneath a live engine, which is the shape a store outage
    takes. The answer must say the data could not be *read*, carry a counted degradation,
    and never say the data does not exist.
    """
    with provision() as broken:
        ingest_published_layer(broken.read_model, CmsExport.rooted(EXPORT_ROOT))
        engine = engine_for(broken, state_file, now=lambda: MOMENT)
        application = create_app(engine)
        broken.read_model.close()
        payload = ask(application, f"What is {INFLATION} now?")

    package = payload["packages"][0]
    assert package["kind"] == PackageKind.REFUSAL.value
    assert "could not be read" in package["reason"]
    assert [degradation["kind"] for degradation in package["degradations"]] == [
        "adapter_unavailable"
    ]


# ------------------------------------------------------------------------- health


def test_health_reports_store_reachability_beside_read_model_freshness(
    app: FastAPI,
) -> None:
    """AD-21, and the two facts kept separable: a stale copy is served correctly."""
    payload = call(app, "GET", HEALTH_ROUTE).json()
    assert payload["status"] == "ok"
    assert {store["name"] for store in payload["stores"]} == {READ_MODEL_STORE, RECORD_STORE}
    assert all(store["reachable"] for store in payload["stores"])
    assert payload["freshness"]["stale"] is True, "stale, and still healthy"


def test_health_reports_a_store_that_does_not_answer(state_file: Path) -> None:
    with provision() as estate:
        application = create_app(engine_for(estate, state_file, now=lambda: MOMENT))
        estate.record_store.close()
        payload = call(application, "GET", HEALTH_ROUTE).json()
    assert payload["status"] == "unavailable"
    unreachable = [store for store in payload["stores"] if not store["reachable"]]
    assert [store["name"] for store in unreachable] == [RECORD_STORE]
    assert unreachable[0]["detail"], "a store that did not answer says why"


def test_a_health_report_cannot_say_reachable_and_why_it_is_not() -> None:
    with provision() as estate:
        health = SqliteStoreHealth(name="x", connection=estate.read_model).health()
    assert health.reachable and not health.detail


# --------------------------------------------------- the catalogue wiring, Story 1.11


def test_the_snapshot_is_built_from_the_read_model(databases: Databases) -> None:
    """Story 1.11 left ``SnapshotCatalogue`` unwired; this is the wiring, on real names."""
    names = read_model_snapshot(databases.read_model)
    found = names.details_named(INFLATION.casefold())
    assert len(found) == 1, "one detail is named exactly this in the whole catalogue"
    assert names.published_grains(found[0]) and len(names.published_grains(found[0])) == 3


def test_the_catalogue_declares_no_default_grain_because_the_export_does_not(
    databases: Databases,
) -> None:
    """FR-5: the declared default is never derived from the datapoints.

    The published layer carries no such column, so the honest answer is ``None`` -- and
    ``None`` is what lets a period-less question stay an ungrained ``Latest`` rather than
    being answered at a grain the newest row chose.
    """
    names = read_model_snapshot(databases.read_model)
    detail_id = names.details_named(INFLATION.casefold())[0]
    assert names.default_grain(detail_id) is None


def test_a_two_letter_country_code_is_not_a_country_name(databases: Databases) -> None:
    """`is`, `in`, `at` and `no` are all ISO codes in this reference. Binding a scope off
    one would make *"what is inflation now"* a question about Iceland."""
    names = read_model_snapshot(databases.read_model)
    for word in ("is", "in", "at", "no", "so", "me"):
        assert names.country_named(word) is None


def test_the_real_catalogue_does_not_offer_the_home_country_to_be_filtered_by(
    databases: Databases,
) -> None:
    """R-COUNTRY-HOME-IS-ABSENCE, asserted on the **real** snapshot.

    ``tests/test_compile.py`` already asserts that naming the home country binds the
    national scope, but it asserts it over a hand-built catalogue that omits the country
    to begin with -- so it passed throughout the period when the snapshot built from the
    read model offered the name and the binder duly built a filter from it. The reader
    saw the whole defect: *"inflation in <home country>"* refused with "no data for this
    selection" while the identical question without the name answered, because the
    published data carries the national series as the *absence* of a country value and
    the id matched no row.

    The home country is read from the rule table and its names from its own reference
    row, so this test names it nowhere and keeps passing if the deployment changes which
    country is home.
    """
    home_code = country_aliases().home_code
    row = databases.read_model.execute(
        "SELECT country_id, name_en, name_ar FROM ref_country WHERE UPPER(code) = ?",
        (home_code,),
    ).fetchone()
    assert row is not None, "the home country keeps its reference row; only the name is withheld"
    country_id, name_en, name_ar = row

    names = read_model_snapshot(databases.read_model)
    for spelling in (name_en, name_ar):
        assert names.country_named(normalise(spelling)) is None

    # It is withheld because it has nothing to be filtered by -- not as a special case.
    (rows,) = databases.read_model.execute(
        "SELECT COUNT(*) FROM datapoint WHERE country_id = ?", (country_id,)
    ).fetchone()
    assert rows == 0

    # And a benchmark country is still resolvable, so this excludes one country and not
    # the country lookup itself.
    other = databases.read_model.execute(
        "SELECT name_en FROM ref_country WHERE UPPER(code) != ? AND country_id IN "
        "(SELECT DISTINCT country_id FROM datapoint WHERE country_id IS NOT NULL) LIMIT 1",
        (home_code,),
    ).fetchone()
    assert other is not None
    assert names.country_named(normalise(other[0])) is not None


def test_a_source_reference_naming_the_wrong_publisher_does_not_resolve(
    databases: Databases, app: FastAPI
) -> None:
    """AD-7's closed world is the whole reference, not a prefix of it."""
    sources = ReadModelSources(connection=databases.read_model)
    reference = ask(app, f"What is {INFLATION} now?")["packages"][0]["elements"][0]["source_ref"]
    detail_id, period, country, _source = reference.split("|")
    assert sources.resolves(reference)
    assert not sources.resolves(f"{detail_id}|{period}|{country}|S-NOBODY")
    assert not sources.resolves("not-a-reference")


# ------------------------------------------------------------------------ helpers


def _a_shared_name(databases: Databases) -> str:
    """A published detail name two details share, found in the real catalogue."""
    names = read_model_snapshot(databases.read_model)
    for row in databases.read_model.execute("SELECT name_en FROM detail ORDER BY detail_id"):
        spelling = str(row[0])
        if len(names.details_named(normalise(spelling))) > 1:
            return spelling
    raise AssertionError("the export is expected to publish an ambiguous detail name")


def _modules(package: str) -> list[Path]:
    return sorted(
        path
        for path in (PACKAGE_ROOT / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    else:
        if node.module:
            yield node.module
        for alias in node.names:
            yield alias.name
