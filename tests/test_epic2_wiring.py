"""Stories 2.6 and 2.7, joined to the answer path.

Both stories were built and tested behind their own boundaries and neither was reachable
from a question. Three gaps closed here, and each one is a claim that only holds if it is
wired:

* **``bound_by: model`` is recorded.** Story 2.6's *"over-binding must be visible in
  data"* is a claim about records, so a rung that binds and is not recorded is the same
  as no rung at all. The binder consults the tie-break where AD-25's deterministic ladder
  left a tie, and the detail's ``Binding`` says who resolved it.
* **A missing or altered prompt fails the boot** (AD-29), not the request. Verified in
  ``create_app``, before a route exists.
* **A refusal's machine code reaches the client** (FR-38). A stable code that stops at
  the package boundary is an internal label.

Everything here runs with **no model reachable** (NFR-6). Where a model is involved it is
``adapters/model/fakes.py`` -- ``ScriptedModel`` runs the caller's real validator, so a
test that passes here has exercised AD-8's parse-and-validate floor rather than skipped
it -- and the default everywhere, as in every other test in the suite, is ``None``.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final, cast

import pytest

from askai.adapters.model.fakes import ScriptedModel, no_model
from askai.adapters.model.prompts import PromptError, verify_prompts
from askai.api.app import create_app
from askai.api.engine import Engine
from askai.api.tiebreak import TieBreakRung
from askai.api.wire import package_block
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import BoundBy, CompiledQuestion, SpecField, UnboundReason
from askai.compile.catalogue import SnapshotCatalogue
from askai.compile.resolve import Disambiguation, Resolved
from askai.domain.spec import Bound, Unbound
from askai.messages.lang import Lang
from askai.narrate.package import AnswerPackage, PackageKind, PackageSource
from askai.narrate.refusal import RefusalCode
from askai.ports.model import CallSite
from askai.ports.resolution import Candidate, CandidateFacts, MatchedSurface, UnitShape

PACKAGE_ROOT: Final = Path(__file__).resolve().parent.parent / "src" / "askai"

TODAY: Final = date(2026, 9, 16)

#: The two details a reader cannot tell apart and neither can the deterministic ladder:
#: one published surface, two details behind it. This is 257 of 320 names in one line.
SHARED: Final = "gross domestic product"
REAL: Final = "detail-real-gdp"
NOMINAL: Final = "detail-nominal-gdp"

#: Nothing is named exactly, so the ladder is what runs. An empty catalogue also keeps
#: the period, scope, measure and operation binders on their rule defaults, so the only
#: thing under test is the detail.
EMPTY_CATALOGUE: Final = SnapshotCatalogue()


# --------------------------------------------------------------------------- fixtures


def _imported(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Every module name *node* imports, ``from x import y`` written out as ``x.y``."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    root = node.module or ""
    return [root, *(f"{root}.{alias.name}" for alias in node.names)]


def _candidate(detail_id: str) -> Candidate:
    """One candidate carrying no distinguishing fact at all.

    Every fact is empty, which makes every structural signal *silent* -- so stage 2 has
    nothing to discriminate on and the ladder produces the genuine tie this rung exists
    for. A candidate with a period or a unit would be decided deterministically and would
    never reach a model.
    """
    return Candidate(
        detail_id=detail_id,
        indicator_id=f"i-{detail_id}",
        score=1.0,
        matched=MatchedSurface(kind="detail_name", lang=Lang.EN, text=SHARED),
        facts=CandidateFacts(
            periods=frozenset(),
            benchmark_countries=frozenset(),
            unit_shape=UnitShape.UNKNOWN,
            entity_names=(),
        ),
        surfaces=(SHARED,),
    )


class Fixed:
    """A ``CandidatePort`` returning what it was given. Stage 1 with no index."""

    def __init__(self, *candidates: Candidate) -> None:
        self._candidates = candidates

    def candidates(
        self,
        subject: str,
        *,
        lang: Lang | None = None,
        limit: int | None = None,
    ) -> tuple[Candidate, ...]:
        return self._candidates


def _tied() -> Fixed:
    return Fixed(_candidate(REAL), _candidate(NOMINAL))


def _answering(detail_id: str) -> ScriptedModel:
    """A runtime that names *detail_id*, whatever it is asked."""
    return ScriptedModel({CallSite.CANDIDATE_DISCRIMINATION: detail_id})


def _compiled(
    candidates: Fixed | None = None, rung: TieBreakRung | None = None
) -> CompiledQuestion:
    return compile_question(
        CompileInput(question=f"what is the {SHARED}", today=TODAY),
        EMPTY_CATALOGUE,
        candidates,
        tie_break=rung,
    )


def _detail(compiled: CompiledQuestion) -> tuple[object, BoundBy | None]:
    binding = compiled.by_field[SpecField.DETAIL]
    return compiled.state_of(SpecField.DETAIL), binding.bound_by


# =================================================== 1. bound_by: model, in the record


def test_a_tie_the_model_breaks_is_bound_and_recorded_as_the_models() -> None:
    """Story 2.6's auditability clause: the rung binds, and the record says it was it.

    ``SEMANTIC`` and ``MODEL`` are both ``named-in-question`` by precedence -- the
    reader's words chose it either way -- and they differ on FR-14's other axis, whose
    authority read those words. That is the difference an operator counts over-binding
    with, so it is the one asserted here.
    """
    rung = TieBreakRung(_answering(REAL))

    compiled = _compiled(_tied(), rung)

    state, bound_by = _detail(compiled)
    assert state == Bound(REAL)
    assert bound_by is BoundBy.MODEL
    assert isinstance(compiled.resolution, Resolved)
    assert compiled.resolution.detail_id == REAL


def test_the_bound_resolution_keeps_the_surface_the_reader_would_have_been_offered() -> None:
    """Nothing is re-derived by the rung: the ``Resolved`` is built from the ``Offered``
    that carried the id, so the audit record and the clarification agree about what
    matched."""
    compiled = _compiled(_tied(), TieBreakRung(_answering(NOMINAL)))

    assert isinstance(compiled.resolution, Resolved)
    assert compiled.resolution.matched_surface == SHARED


def test_with_no_model_reachable_the_tie_stays_a_tie_and_the_reader_is_asked() -> None:
    """NFR-6, and Story 2.6's declared fallback in one case.

    The worst case of an outage is a clarifying question -- the same one the reader would
    have been asked had no model been configured at all. Nothing is guessed, the
    candidate list is not narrowed, and the detail stays unbound with the cause that says
    *several match*.
    """
    rung = TieBreakRung(no_model())

    compiled = _compiled(_tied(), rung)

    state, bound_by = _detail(compiled)
    assert isinstance(state, Unbound)
    assert state.reason.startswith(UnboundReason.SEVERAL_INDICATORS_MATCH.value)
    assert bound_by is None
    assert isinstance(compiled.resolution, Disambiguation)


def test_a_fallback_is_counted_and_the_prompt_it_used_is_recorded() -> None:
    """AD-15 and AD-29 on the same failure.

    A fallback that counted nothing makes a rising failure rate indistinguishable from a
    quiet corpus, and an answer that used a prompt without recording which one is the
    untraceable card AD-29 exists to prevent -- including when the output was discarded.
    """
    rung = TieBreakRung(no_model())

    _compiled(_tied(), rung)

    assert rung.degradations
    assert [use.prompt_id for use in rung.prompts] == ["candidate-tie-break"]


def test_an_answer_the_validator_rejects_is_discarded_rather_than_bound() -> None:
    """AD-8's closed domain. A well-formed id the catalogue never offered is refused as
    firmly as unparseable text, and the reader is asked."""
    rung = TieBreakRung(_answering("detail-the-model-invented"))

    compiled = _compiled(_tied(), rung)

    state, bound_by = _detail(compiled)
    assert isinstance(state, Unbound)
    assert bound_by is None
    assert rung.degradations


def test_no_rung_injected_compiles_exactly_as_it_did_before() -> None:
    """The default, and the state every corpus entry and every Epic 1 caller is in.

    ``tie_break`` of ``None`` is not "a model that fails"; it is the deterministic ladder
    alone. The outcome is the same tie, which is what keeps NFR-1's twice-compiled corpus
    untouched by this story.
    """
    compiled = _compiled(_tied())

    state, bound_by = _detail(compiled)
    assert isinstance(state, Unbound)
    assert bound_by is None
    assert isinstance(compiled.resolution, Disambiguation)


def test_a_ladder_that_already_decided_is_never_put_to_a_model() -> None:
    """The rung is reached **only** from a tie.

    A ``Resolved`` is already bound and a ``Refusal`` is already a refusal; putting
    either to a model would ask it to overturn a decision the data made (AD-25). Asserted
    on the fake's own call log, so an implementation that called and then ignored the
    answer would fail here.
    """
    model = _answering(REAL)
    rung = TieBreakRung(model)

    compiled = _compiled(Fixed(_candidate(REAL)), rung)

    state, bound_by = _detail(compiled)
    assert state == Bound(REAL)
    assert bound_by is BoundBy.SEMANTIC
    assert model.calls == ()
    assert rung.used == []


def test_the_binder_cannot_name_a_model_at_all() -> None:
    """NFR-5, structurally, one module further out than ``tests/test_resolve.py`` asserts.

    The rung arrives as a function from the composition root. If the binder could import
    the adapter or the port, the injection would be a convention rather than the only
    route -- and ``lint-imports`` forbids ``compile -> adapters`` but says nothing about
    ``ports.model``.
    """
    tree = ast.parse((PACKAGE_ROOT / "compile" / "binder.py").read_text(encoding="utf-8"))
    imported = [
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
    ]

    banned = {"askai.ports.model", "askai.adapters.model", "httpx", "openai"}
    assert not [name for name in imported if name in banned or name.split(".")[0] in banned]


def test_the_rung_holds_its_calls_on_the_instance_and_never_at_module_scope() -> None:
    """AD-15's no-ambient-collector rule, at the one place this story adds state.

    Two readers answered concurrently hold two rungs; what one put to the model must not
    appear on the other's record.
    """
    first = TieBreakRung(no_model())
    second = TieBreakRung(no_model())

    _compiled(_tied(), first)

    assert first.used and second.used == []


# ============================================= 2. AD-29: a bad prompt fails the boot


def test_the_published_prompts_verify_so_a_boot_is_possible() -> None:
    """The precondition of every other assertion here: the shipped prompts are the
    reviewed ones, and ``create_app`` therefore does not fail on a good checkout."""
    assert verify_prompts()


def test_creating_the_app_verifies_the_prompts_before_it_reads_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-29's *"fails loudly at startup"*, and loudly means before a route exists.

    The engine is deliberately not a real one: if the check happened after the app had
    been built, or on the rung at answer time, this would fail with something other than
    ``PromptError``. It does not degrade, and that asymmetry is the story -- an outage is
    a fact about a runtime we do not control, and an altered prompt is a fact about what
    this deployment is about to tell a model to do.
    """
    def tampered(directory: Path | None = None) -> Sequence[object]:
        raise PromptError("candidate-tie-break@1 hashes to something nobody reviewed")

    monkeypatch.setattr("askai.api.app.verify_prompts", tampered)

    with pytest.raises(PromptError):
        create_app(cast(Engine, object()))


def test_the_startup_check_is_called_and_is_not_wrapped_in_a_handler() -> None:
    """It must not degrade. A ``try`` around the call is the one thing that would turn
    AD-29's loud failure back into a quiet one, so the call site is read structurally."""
    tree = ast.parse((PACKAGE_ROOT / "api" / "app.py").read_text(encoding="utf-8"))
    factory = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    called = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "verify_prompts"
    ]
    assert len(called) == 1, "create_app verifies every published prompt exactly once"
    assert not [node for node in ast.walk(factory) if isinstance(node, ast.Try)]


# ================================================ 3. the refusal code, on the wire


def _package(
    kind: PackageKind, *, reason_id: str, code: RefusalCode | None
) -> AnswerPackage:
    compiled = compile_question(
        CompileInput(question="what is the mood of the nation", today=TODAY),
        EMPTY_CATALOGUE,
    )
    return AnswerPackage(
        source=PackageSource.APPROVED,
        kind=kind,
        spec=compiled.spec,
        bindings=compiled.bindings,
        agent="the approved-data agent",
        reason="I hold nothing matching that.",
        reason_id=reason_id,
        refusal_code=code,
    )


def test_a_refusal_carries_its_code_and_its_message_id_to_the_client() -> None:
    """FR-38: *a stable machine code alongside its message id*.

    Two fields and two jobs. ``reason_id`` survives a wording fix in ``messages/data``,
    and ``refusal_code`` is which of FR-38's six causes this is -- what refusals are
    **counted** by. Both were on the package from Story 2.7 and neither reached the wire,
    which is the same as not having them from a client's point of view.
    """
    block = package_block(
        _package(
            PackageKind.REFUSAL,
            reason_id="refusal.no_such_indicator",
            code=RefusalCode.NO_SUCH_INDICATOR,
        )
    )

    assert block["reason_id"] == "refusal.no_such_indicator"
    assert block["refusal_code"] == "no-such-indicator"


def test_a_clarification_carries_an_id_and_no_refusal_code() -> None:
    """A question asked well is not a failure.

    ``refusal_code`` is absent rather than null: counting a clarification as a refusal
    would make an engine that asks well look like one that cannot answer, and the six
    causes stay a count of refusals.
    """
    block = package_block(
        _package(PackageKind.CLARIFICATION, reason_id="clarify.which_indicator", code=None)
    )

    assert block["reason_id"] == "clarify.which_indicator"
    assert "refusal_code" not in block


def test_every_refusal_code_serialises_as_its_stable_value() -> None:
    """All six, so a code added to the closed set cannot reach the wire as a repr."""
    for code in RefusalCode:
        block = package_block(
            _package(PackageKind.REFUSAL, reason_id="refusal.no_such_indicator", code=code)
        )
        assert block["refusal_code"] == code.value
