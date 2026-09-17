"""Stories 9.6-9.9 -- the external agent: parallel, budgeted, two answers, recorded.

Four properties, and the second one is the one that gets softened by accident.

1. **Parallel, on its own budget, and never in the way** (9.6, AD-9, NFR-10, NFR-3). The
   external call is submitted before the question is compiled and collected after the
   packages are final, so a slow or dead third party cannot degrade, delay or block the
   approved answer. When the budget expires the wait is abandoned client-side and the
   orphaned job is *recorded*, not shrugged off. The elapsed time is on every record so
   ``[ASSUMPTION A4]``'s ~2x Combined latency can be tested rather than believed.

2. **Two answers, never one** (9.7, FR-85, FR-86, FR-87, AD-10). ``ExternalAnswer`` is a
   distinct type from ``Answer`` and ``AnswerPackage`` with no conversion between them,
   and the merge somebody would write **fails ``mypy --strict``** -- asserted here by
   running the type checker over it, because a runtime test cannot assert a thing that
   never runs. No function anywhere takes both and returns one. A refusal on the approved
   side is still shown and the external answer never stands in for it.

3. **The caveat is unconditional, and honest about its own limits** (9.8, FR-84, FR-88,
   FR-88a). Every external answer carries one -- prose, timeout, dead platform, no
   platform at all, and ``{External}``-only where there is no approved anchor to judge
   against. The percentage band check is **ratified** from the system being replaced
   rather than reinvented, it annotates and never strips, and ``BandCheck`` cannot be
   constructed without the sentence stating what it did not check.

4. **Recorded** (9.9, FR-90, NFR-4a, NFR-9). The single record carries the agent selected,
   what was sent -- the reader's question and a deterministic context line, and never
   approved data -- and the outcome, within Story 1.16's bounded size.

Everything here passes with **nothing reachable**, because nothing is: no external agent
platform exists for this system at all. The adapter is driven through a scripted exchange
and the port through ``adapters/external/fakes``.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.external.agent import (
    ExchangeTimeout,
    ExternalAgentClient,
    HttpReply,
    HttpRequest,
    job_body,
)
from askai.adapters.external.fakes import ScriptedExternalAgent, no_external_agent
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.readmodel.startup import engine_for
from askai.adapters.store.provision import Databases, provision
from askai.api.ask import Ask, answer_question, external_context_line
from askai.api.engine import Engine
from askai.api.wire import ask_response, external_block
from askai.config.model import ConfigError, ExternalAgentSettings
from askai.domain.admission import PackageSource, SourceAdmission
from askai.domain.spec import QuerySpec, Unbound
from askai.messages import Lang
from askai.narrate.package import AnswerPackage
from askai.observability.identity import Anonymous
from askai.observability.record import (
    MAX_RECORD_BYTES,
    SPEC_FIELDS,
    AnswerRecord,
    BindingMechanism,
    ExternalCall,
    FieldBinding,
    row_size_bytes,
)
from askai.ports.external_agent import (
    DEFAULT_EXTERNAL_BUDGET,
    ExternalAgentPort,
    ExternalBudget,
    ExternalOutcome,
    ExternalRequest,
    ExternalResult,
)
from askai.respond.external import (
    DEFAULT_CAUTION_BAND,
    PERCENT_IN_PROSE,
    BandCheck,
    ExternalAnswer,
    band_check,
    percentages_in,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

MOMENT: Final = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
INFLATION: Final = "Inflation"

#: A budget short enough that a blocked call is abandoned inside a test run, and still a
#: real budget: every slice is positive and none of them exceeds the whole.
TINY_BUDGET: Final = ExternalBudget(
    total_seconds=0.05, connect_seconds=0.01, read_seconds=0.02, poll_interval_seconds=0.01
)

#: Prose with figures in it, one of them beyond the ratified band. The -28.76% is the
#: figure F-002 recorded and the epic is named after.
WILD_PROSE: Final = "Growth was 2.5 % last year and the forecast is -28.76% for next year."

SETTINGS: Final = ExternalAgentSettings(base_url="http://agent.invalid/v1")

#: A spec with nothing bound, for the record invariants below. Nothing here is about
#: compiling; it is the minimum a complete ``AnswerRecord`` needs to exist at all.
EMPTY_SPEC: Final = QuerySpec(
    detail=Unbound(reason="not under test"),
    period=Unbound(reason="not under test"),
    country_scope=Unbound(reason="not under test"),
    measure=Unbound(reason="not under test"),
    operation=Unbound(reason="not under test"),
    today=MOMENT.date(),
)


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


def with_agent(
    engine: Engine,
    agent: ExternalAgentPort | None,
    budget: ExternalBudget = DEFAULT_EXTERNAL_BUDGET,
) -> Engine:
    """*engine*, wired to *agent*. The only thing any of these tests changes about one."""
    return replace(engine, external=agent, external_budget=budget)


def ask_it(
    engine: Engine,
    admission: SourceAdmission = SourceAdmission.BOTH,
    question: str = f"What is {INFLATION} now?",
    lang: Lang = Lang.EN,
) -> tuple[tuple[AnswerPackage, ...], ExternalAnswer | None, dict[str, object]]:
    """One real request through the real path: packages, external half, audit evidence."""
    answered = answer_question(
        engine, Ask(question=question, lang=lang, sources=admission)
    )
    evidence = json.loads(answered.record.answer_json)
    assert isinstance(evidence, dict)
    return answered.response.packages, answered.external, evidence


# ------------------------------------------------------------- a scripted job platform


@dataclass
class ScriptedExchange:
    """A platform, as a list of replies. Not a mock: the adapter's real loop drives it.

    ``replies`` is consumed in order and the last one repeats, so *"pending, pending,
    succeeded"* is three entries and *"pending forever"* is one. ``fail_with`` raises
    instead, which is how a dead platform and a slow one are told apart.
    """

    replies: list[HttpReply] = field(default_factory=list)
    fail_with: BaseException | None = None
    seen: list[HttpRequest] = field(default_factory=list)

    def __call__(self, request: HttpRequest) -> HttpReply:
        self.seen.append(request)
        if self.fail_with is not None and request.method == "POST":
            raise self.fail_with
        if not self.replies:
            return HttpReply(status=500, text="")
        if len(self.replies) == 1:
            return self.replies[0]
        return self.replies.pop(0)

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.seen]


@dataclass
class RecordedWaits:
    """A waiter that records what it was asked to spend instead of spending it.

    Strictly better than a real sleep for testing a budget: the assertion becomes *"it
    asked to wait a poll interval"* rather than *"the suite took a poll interval"*.
    """

    asked: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.asked.append(seconds)


def client(exchange: ScriptedExchange, waits: RecordedWaits | None = None) -> ExternalAgentClient:
    return ExternalAgentClient(
        settings=SETTINGS, exchange=exchange, wait=waits or RecordedWaits()
    )


def a_request(budget: ExternalBudget = DEFAULT_EXTERNAL_BUDGET) -> ExternalRequest:
    return ExternalRequest(question="what is inflation", context="language=en", budget=budget)


def job(status: str, answer: str | None = None) -> HttpReply:
    body: dict[str, object] = {"status": status}
    if answer is not None:
        body["answer"] = answer
    return HttpReply(status=200, text=json.dumps(body))


# ==================================================== 9.6 -- parallel, on its own budget


def test_the_port_has_one_verb_and_it_returns_a_result_rather_than_a_job() -> None:
    """A port with a job lifecycle on it is a port a caller can build a loop out of."""
    verbs = [name for name in vars(ExternalAgentPort) if not name.startswith("_")]
    assert verbs == ["ask"]


@pytest.mark.parametrize(
    ("total", "connect", "read", "interval"),
    [
        (0.0, 1.0, 1.0, 0.1),
        (-1.0, 1.0, 1.0, 0.1),
        (10.0, 0.0, 1.0, 0.1),
        (10.0, 1.0, 0.0, 0.1),
        (10.0, 1.0, 1.0, 0.0),
        # A slice longer than the whole: a timeout that can never be reached, because the
        # caller abandons at the total whatever the transport was told.
        (1.0, 2.0, 1.0, 0.1),
        (1.0, 1.0, 2.0, 0.1),
    ],
)
def test_a_budget_that_bounds_nothing_cannot_be_constructed(
    total: float, connect: float, read: float, interval: float
) -> None:
    with pytest.raises(ValueError):
        ExternalBudget(
            total_seconds=total,
            connect_seconds=connect,
            read_seconds=read,
            poll_interval_seconds=interval,
        )


def test_the_outbound_payload_is_the_question_and_a_context_line_and_nothing_else() -> None:
    """NFR-4a: explicit, minimal, and never approved data -- as a shape, not a rule."""
    body = job_body(a_request())
    assert set(body) == {"question", "context"}
    assert {field.name for field in dataclasses.fields(ExternalRequest)} == {
        "question",
        "context",
        "budget",
    }


def test_a_submitted_job_is_polled_until_it_answers_and_the_prose_comes_back() -> None:
    exchange = ScriptedExchange(
        replies=[
            HttpReply(status=200, text=json.dumps({"job_id": "j-1"})),
            job("pending"),
            job("succeeded", "The external view."),
        ]
    )
    waits = RecordedWaits()
    result = client(exchange, waits).ask(a_request())
    assert result.outcome is ExternalOutcome.ANSWERED
    assert result.prose == "The external view."
    assert result.job_id == "j-1"
    assert exchange.methods == ["POST", "GET", "GET"]
    # One poll interval, asked for and never spent.
    assert waits.asked == [pytest.approx(DEFAULT_EXTERNAL_BUDGET.poll_interval_seconds)]


def test_a_timeout_submitting_is_a_timeout_and_a_refusal_is_unavailable() -> None:
    """A slow dependency and a dead one are different tickets for different people."""
    timed_out = client(
        ScriptedExchange(fail_with=ExchangeTimeout("no reply"))
    ).ask(a_request())
    assert timed_out.outcome is ExternalOutcome.TIMED_OUT

    dead = client(ScriptedExchange(fail_with=OSError("name does not resolve"))).ask(a_request())
    assert dead.outcome is ExternalOutcome.UNAVAILABLE
    assert dead.degradations[0].kind == "external_agent_unavailable"


@pytest.mark.parametrize(
    "reply",
    [
        HttpReply(status=503, text="upstream is down"),
        HttpReply(status=200, text="<html>please log in</html>"),
        HttpReply(status=200, text=json.dumps({"queued": True})),
    ],
)
def test_a_platform_that_does_not_answer_with_a_job_is_unavailable(reply: HttpReply) -> None:
    result = client(ScriptedExchange(replies=[reply])).ask(a_request())
    assert result.outcome is ExternalOutcome.UNAVAILABLE
    assert result.prose == ""


@pytest.mark.parametrize("status", ["failed", "cancelled", "error"])
def test_a_job_that_finishes_without_answering_is_unavailable(status: str) -> None:
    exchange = ScriptedExchange(
        replies=[HttpReply(status=200, text=json.dumps({"job_id": "j-1"})), job(status)]
    )
    result = client(exchange).ask(a_request())
    assert result.outcome is ExternalOutcome.UNAVAILABLE
    assert "j-1" in result.degradations[0].detail


def test_a_success_carrying_no_prose_never_becomes_an_empty_card() -> None:
    """FR-89, caught at the only place it can be: the platform said yes and sent nothing."""
    exchange = ScriptedExchange(
        replies=[
            HttpReply(status=200, text=json.dumps({"job_id": "j-1"})),
            job("succeeded", "   "),
        ]
    )
    result = client(exchange).ask(a_request())
    assert result.outcome is ExternalOutcome.UNAVAILABLE
    assert result.prose == ""


def test_the_budget_expiring_abandons_the_call_and_records_the_orphaned_job() -> None:
    """Spine open question 2, answered: cancel if you can, abandon regardless, record it."""
    exchange = ScriptedExchange(
        replies=[HttpReply(status=200, text=json.dumps({"job_id": "j-7"})), job("pending")]
    )
    ticks = iter([0.0, 0.0, 99.0, 99.0, 99.0])
    agent = ExternalAgentClient(
        settings=SETTINGS,
        exchange=exchange,
        wait=RecordedWaits(),
        clock=lambda: next(ticks),
    )
    result = agent.ask(a_request())
    assert result.outcome is ExternalOutcome.ABANDONED
    assert result.orphaned_job == "j-7"
    # The cancellation was attempted. It is a courtesy, and it is attempted either way.
    assert "DELETE" in exchange.methods
    assert "abandoned client-side" in result.degradations[0].detail


def test_the_poll_loop_never_outlives_its_budget_however_long_the_platform_takes() -> None:
    """The loop is bounded by time, not by an attempt limit -- so it always terminates."""
    exchange = ScriptedExchange(
        replies=[HttpReply(status=200, text=json.dumps({"job_id": "j-1"})), job("pending")]
    )
    waits = RecordedWaits()
    tick = iter(range(1000))
    agent = ExternalAgentClient(
        settings=SETTINGS,
        exchange=exchange,
        wait=waits,
        clock=lambda: float(next(tick)) / 10.0,
    )
    result = agent.ask(a_request(TINY_BUDGET))
    assert result.outcome is ExternalOutcome.ABANDONED
    assert len(waits.asked) < 5


def test_a_dead_third_party_does_not_delay_or_block_the_approved_answer(
    engine: Engine,
) -> None:
    """**NFR-10, measured.** The approved answer arrives while the call is outstanding.

    The scripted agent blocks in a worker thread until this test releases it. The answer
    path abandons on its own clock at a 0.05s budget, composes the approved package, and
    returns -- so the assertion is on the wall-clock of the whole request, which is the
    only honest way to assert "it did not wait".
    """
    released = threading.Event()

    def blocked(_seconds: float) -> None:
        released.wait(30.0)

    agent = ScriptedExternalAgent(prose="late prose", latency_seconds=5.0, wait=blocked)
    started = time.monotonic()
    try:
        packages, external, _ = ask_it(with_agent(engine, agent, TINY_BUDGET))
    finally:
        released.set()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"the approved answer waited {elapsed}s on a dead third party"
    assert [package.source for package in packages] == [PackageSource.APPROVED]
    assert external is not None
    assert external.outcome is ExternalOutcome.ABANDONED
    assert external.reason and not external.prose


def test_an_unwired_deployment_states_the_gap_rather_than_narrowing_the_selection(
    engine: Engine,
) -> None:
    """No platform exists. The reader asked for one, so they are told (FR-82, FR-89)."""
    packages, external, _ = ask_it(with_agent(engine, None))
    assert [package.source for package in packages] == [PackageSource.APPROVED]
    assert external is not None
    assert external.outcome is ExternalOutcome.UNAVAILABLE
    assert external.reason.strip()
    assert external.degradations[0].kind == "external_agent_unavailable"


def test_the_approved_only_admission_makes_no_external_call_at_all(engine: Engine) -> None:
    """FR-79 from the other end: not ignored, never made."""
    agent = ScriptedExternalAgent(prose="should never be asked")
    packages, external, evidence = ask_it(
        with_agent(engine, agent), SourceAdmission.APPROVED_ONLY
    )
    assert agent.requests == ()
    assert external is None
    assert evidence["external_call"] is None
    assert [package.source for package in packages] == [PackageSource.APPROVED]


def test_combined_latency_is_measured_on_every_answer_rather_than_assumed(
    engine: Engine,
) -> None:
    """NFR-3 and ``[ASSUMPTION A4]``: the ~2x baseline is testable because this is here."""
    agent = ScriptedExternalAgent(prose="an external view", latency_seconds=1.25)
    _, external, evidence = ask_it(with_agent(engine, agent))
    assert external is not None
    assert external.elapsed_seconds == pytest.approx(1.25)
    call = evidence["external_call"]
    assert isinstance(call, dict)
    assert call["elapsed_ms"] == 1250


# ============================================ 9.7 -- two answers, never one


def _mypy(*arguments: str) -> subprocess.CompletedProcess[str]:
    scripts_dir = Path(sys.executable).parent
    candidates = [scripts_dir / "mypy.exe", scripts_dir / "mypy"]
    executable = next((path for path in candidates if path.is_file()), None)
    resolved = str(executable) if executable else shutil.which("mypy")
    assert resolved, "mypy is not installed; run `uv sync --locked --all-extras`"
    return subprocess.run(
        [resolved, "--strict", "--no-incremental", "--no-error-summary", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )


MERGE_ATTEMPT: Final = '''\
"""A merge of the approved and external answers, which must not type-check."""

from __future__ import annotations

from askai.narrate.package import AnswerPackage
from askai.respond.external import ExternalAnswer


def merge(approved: AnswerPackage, external: ExternalAnswer) -> AnswerPackage:
    """Blend the two halves -- the function AD-10 exists to make impossible."""
    return AnswerPackage(
        source=approved.source,
        kind=approved.kind,
        agent=approved.agent,
        spec=external.spec,
        bindings=external.bindings,
        elements=approved.elements + external.elements,
        row_ids=approved.row_ids + external.row_ids,
    )


def substitute(external: ExternalAnswer) -> AnswerPackage:
    """Let the external answer stand in for the approved one (FR-87's forbidden move)."""
    return external
'''

NO_MERGE: Final = '''\
"""Reading each answer as itself, which is all anyone is allowed to do."""

from __future__ import annotations

from askai.narrate.package import AnswerPackage
from askai.respond.external import ExternalAnswer


def both(approved: AnswerPackage, external: ExternalAnswer) -> tuple[str, str]:
    """Side by side, labelled, neither touching the other."""
    return approved.agent, external.agent
'''


def _planted(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_a_function_merging_the_two_answers_fails_mypy_strict(tmp_path: Path) -> None:
    """**The type-level guarantee, proven by making the type checker refuse it.**

    A runtime test cannot assert this: the whole point is that the code never runs. So the
    merge somebody would plausibly write is planted, ``mypy --strict`` is run over it as a
    subprocess -- the idiom ``tests/test_dependency_contracts.py`` established -- and the
    failure is asserted field by field. ``tmp_path`` is pytest's own and is removed for us,
    so nothing is left in the tree whatever this test does.

    If this ever goes green, a conversion, a shared base class or an ``elements`` field has
    been added to ``ExternalAnswer``, and the merge AD-10 forbids has become writable.
    """
    result = _mypy(str(_planted(tmp_path, "merge_attempt.py", MERGE_ATTEMPT)))
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"mypy accepted a merge of the two answers:\n{output}"
    # Every field a merge would need is absent from ExternalAnswer, one error each.
    for absent in ("spec", "bindings", "elements", "row_ids"):
        assert f'"ExternalAnswer" has no attribute "{absent}"' in output, output
    # And the substitution FR-87 names is refused in its own right.
    assert "ExternalAnswer" in output and "AnswerPackage" in output


def test_the_negative_assertion_can_go_green_so_it_is_not_vacuous(tmp_path: Path) -> None:
    """A checker that failed everything would prove nothing. This is the control."""
    result = _mypy(str(_planted(tmp_path, "no_merge.py", NO_MERGE)))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output


def test_no_function_anywhere_takes_both_answers_and_returns_one() -> None:
    """AD-10 as a scan: the shape of a reconciliation, wherever it is written.

    Taking both is allowed -- ``wire.ask_response`` does, and serialises them side by side.
    *Returning one of them* from a function that took both is the reconciliation, and there
    is none.
    """
    answer_types = {"AnswerPackage", "Answer", "ExternalAnswer"}
    offences: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, SyntaxError):  # another session's file, mid-write
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            parameters = " ".join(
                ast.unparse(argument.annotation)
                for argument in node.args.args + node.args.kwonlyargs
                if argument.annotation is not None
            )
            returns = "" if node.returns is None else ast.unparse(node.returns)
            takes_both = "ExternalAnswer" in parameters and (
                "AnswerPackage" in parameters or "Answer(" in parameters
            )
            if takes_both and any(name in returns for name in answer_types):
                offences.append(
                    f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno} {node.name}"
                )
    assert not offences, (
        "a function taking both answers and returning one is a reconciliation nobody can "
        "defend (FR-86, AD-10):\n  " + "\n  ".join(offences)
    )


def test_the_external_answer_has_no_field_a_figure_could_cross_through() -> None:
    """The absence *is* the design: no elements, no spec, no row ids, no source_ref."""
    fields = {field.name for field in dataclasses.fields(ExternalAnswer)}
    assert not fields & {
        "elements",
        "spec",
        "bindings",
        "row_ids",
        "resolution",
        "source_ref",
        "chartable",
    }
    # And no conversion in either direction, under any of the names one would be given.
    for name in ("to_package", "as_package", "from_package", "merge", "reconcile"):
        assert not hasattr(ExternalAnswer, name)
        assert not hasattr(AnswerPackage, name)


def test_combined_returns_two_answers_approved_first_each_with_its_own_provenance(
    engine: Engine,
) -> None:
    """FR-85 on the wire: two headings, two shapes, and nothing shared between them."""
    agent = ScriptedExternalAgent(prose=WILD_PROSE)
    answered = answer_question(
        with_agent(engine, agent),
        Ask(
            question=f"What is {INFLATION} now?",
            lang=Lang.EN,
            sources=SourceAdmission.BOTH,
        ),
    )
    body = ask_response(answered.response, answered.external)
    packages = body["packages"]
    assert isinstance(packages, list)
    provenances = [
        package["provenance"] for package in packages if isinstance(package, dict)
    ]
    assert provenances == [PackageSource.APPROVED.value]
    block = body["external"]
    assert isinstance(block, dict)
    assert block["provenance"] == PackageSource.EXTERNAL.value
    assert block["prose"] == WILD_PROSE
    # No figure, period, unit or claim crosses: the external prose appears nowhere in the
    # approved half, and the approved half's rows appear nowhere in the external one.
    assert WILD_PROSE not in json.dumps(packages)
    assert "-28.76" not in json.dumps(packages)


def test_the_external_answer_never_stands_in_for_an_approved_refusal(
    engine: Engine,
) -> None:
    """FR-87. The substitution is what makes a refusal untrustworthy, so it is not made."""
    agent = ScriptedExternalAgent(prose="The third party is happy to answer anything.")
    packages, external, _ = ask_it(
        with_agent(engine, agent), question="What is the price of tea in orbit?"
    )
    assert [package.source for package in packages] == [PackageSource.APPROVED]
    approved = packages[0]
    assert approved.kind is not None
    # The approved half still speaks for itself, whatever the third party said.
    assert external is not None
    assert external.prose == "The third party is happy to answer anything."
    assert external.prose not in (approved.reason or "")
    for placed in approved.elements:
        assert external.prose not in placed.element.content


def test_respond_stays_generic_over_an_opaque_package_type() -> None:
    """Story 1.15's structural AD-10, not weakened by this story (9.7).

    ``respond/order.py`` and ``respond/response.py`` must keep naming no package type, so
    the layer that arranges packages still cannot read a field off one. ``external.py``
    lives beside them and is a *value* the layer above puts into the response -- it is not
    imported by either.
    """
    for module in ("order.py", "response.py"):
        source = (PACKAGE_ROOT / "respond" / module).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = [
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for name in ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            + [alias.name for alias in node.names]
        ]
        reached = ("askai.narrate", "askai.assemble")
        assert not [name for name in imported if name.startswith(reached)]
        assert "askai.respond.external" not in imported
        # The types are not merely unimported: they are unnameable here.
        for name in ("AnswerPackage", "ExternalAnswer"):
            assert name not in [
                node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            ]


# ================================== 9.8 -- the caveat, unconditional and honest


@pytest.mark.parametrize(
    "agent",
    [
        ScriptedExternalAgent(prose=WILD_PROSE),
        ScriptedExternalAgent(prose="x", latency_seconds=999.0),
        ScriptedExternalAgent(outcome=ExternalOutcome.TIMED_OUT),
        no_external_agent(),
        None,
    ],
)
@pytest.mark.parametrize("lang", [Lang.EN, Lang.AR])
@pytest.mark.parametrize(
    "admission", [SourceAdmission.BOTH, SourceAdmission.EXTERNAL_ONLY]
)
def test_every_external_answer_carries_its_caveat_whatever_happened(
    engine: Engine,
    agent: ExternalAgentPort | None,
    lang: Lang,
    admission: SourceAdmission,
) -> None:
    """FR-84: **always**, not "when they disagree".

    Across every outcome, both languages and both admissions that admit an external
    agent -- including ``{External}`` alone, where the closed-world rule does not apply
    because nothing claims to be approved, and where the caveat matters *more* rather than
    less because the reader has no approved anchor to judge against.
    """
    _, external, _ = ask_it(with_agent(engine, agent), admission, lang=lang)
    assert external is not None
    assert external.caveat.strip()
    assert external.agent.strip()


def test_the_caveat_is_a_field_of_the_content_and_not_an_element_a_lens_could_drop() -> None:
    """FR-84's *"a property of the content, not a footnote brevity may drop"*.

    An element has a role and a role decides which lens shows it. The caveat is neither:
    it is a required field, and the type refuses an external answer without one, so the
    Executive Lens has nothing to shorten away.
    """
    assert "elements" not in {field.name for field in dataclasses.fields(ExternalAnswer)}
    with pytest.raises(ValueError, match="unconditionally"):
        ExternalAnswer(
            agent="Answered by the external source.",
            caveat="   ",
            outcome=ExternalOutcome.UNAVAILABLE,
            reason="it was not reachable",
        )


def test_an_external_answer_is_prose_or_a_stated_gap_and_never_an_empty_card() -> None:
    """FR-89, at the type. Neither is the empty card; both is a gap over an answer."""
    with pytest.raises(ValueError, match="never both or neither"):
        ExternalAnswer(
            agent="a", caveat="c", outcome=ExternalOutcome.UNAVAILABLE, reason="", prose=""
        )
    with pytest.raises(ValueError, match="never both or neither"):
        ExternalAnswer(
            agent="a",
            caveat="c",
            outcome=ExternalOutcome.ANSWERED,
            prose="text",
            reason="also a gap",
        )


def test_the_percentage_pattern_is_the_one_the_current_system_ships() -> None:
    """FR-88: **ratified, not reinvented.**

    The pattern is ``app/main.py``'s, verbatim, and the band is the 25 it falls back to.
    A "better" extractor would be a second, untested one whose disagreements with the
    shipped one nobody could explain.
    """
    assert PERCENT_IN_PROSE.pattern == r"-?\d+(?:\.\d+)?(?=\s*%)"
    assert DEFAULT_CAUTION_BAND == 25.0
    assert percentages_in(WILD_PROSE) == (2.5, -28.76)
    assert percentages_in("no figures here at all") == ()


def test_the_band_check_annotates_and_never_strips_rewrites_or_withholds() -> None:
    """The predecessor relays the text verbatim and appends a caution. So does this."""
    checked = band_check(WILD_PROSE, limits="it only reads numbers written with a % sign")
    assert checked.found == (2.5, -28.76)
    assert checked.beyond == (-28.76,)
    assert checked.flagged
    answer = ExternalAnswer(
        agent="a",
        caveat="not from the approved published data",
        outcome=ExternalOutcome.ANSWERED,
        prose=WILD_PROSE,
        check=checked,
    )
    # The prose is untouched: the wild figure is still there for the reader to see.
    assert answer.prose == WILD_PROSE
    assert "-28.76" in answer.prose


def test_a_check_cannot_be_shown_without_the_limits_of_that_check() -> None:
    """**FR-88a.** A caveat implying figures were verified when they were not is worse
    than no caveat -- so the type refuses the version that implies it."""
    with pytest.raises(ValueError, match="states its own limits"):
        BandCheck(band=25.0, limits="  ")
    with pytest.raises(ValueError, match="flag something it did not read"):
        BandCheck(band=25.0, limits="only percentages", found=(1.0,), beyond=(99.0,))


def test_nothing_downstream_assumes_a_per_figure_range_check_exists(
    engine: Engine,
) -> None:
    """FR-88's deliberately weaker baseline.

    ``check`` is ``None`` on every answer this build produces, and ``None`` means *no
    check ran* -- never *nothing was wrong*. The caveat stands alone and unconditional,
    which is exactly what FR-88 asks the baseline to be.
    """
    agent = ScriptedExternalAgent(prose=WILD_PROSE)
    _, external, _ = ask_it(with_agent(engine, agent))
    assert external is not None
    assert external.check is None
    assert external.caveat.strip()
    block = external_block(external)
    assert block["check"] is None


def test_an_external_answer_is_always_classed_external_and_cannot_be_relabelled() -> None:
    """AD-6, Story 9.5: set by the type, so no argument and no ``replace`` can move it."""
    answer = ExternalAnswer(
        agent="a", caveat="c", outcome=ExternalOutcome.ANSWERED, prose="p"
    )
    assert answer.source is PackageSource.EXTERNAL
    assert "source" not in {field.name for field in dataclasses.fields(ExternalAnswer)}


# ========================================================= 9.9 -- recorded


def test_the_record_carries_the_agent_selected_on_every_answer(engine: Engine) -> None:
    """FR-90: which agent was asked is not recoverable from the packages afterwards."""
    for admission in SourceAdmission:
        answered = answer_question(
            engine,
            Ask(question=f"What is {INFLATION} now?", lang=Lang.EN, sources=admission),
        )
        evidence = json.loads(answered.record.answer_json)
        assert evidence["agent"] == admission.value


def test_the_record_carries_what_was_sent_and_what_the_call_did(engine: Engine) -> None:
    """NFR-4a: the outbound payload, reconstructable months later, and never approved data."""
    agent = ScriptedExternalAgent(prose="an external view")
    question = f"What is {INFLATION} now?"
    _, _, evidence = ask_it(with_agent(engine, agent), question=question)
    call = evidence["external_call"]
    assert isinstance(call, dict)
    assert call["outcome"] == ExternalOutcome.ANSWERED.value
    assert call["sent"] == {
        "question": question,
        "context": external_context_line(Lang.EN, MOMENT),
    }
    # What came *back* is not in the record: it would make one row grow with the length of
    # somebody else's essay (NFR-9).
    assert "an external view" not in json.dumps(evidence)


def test_the_context_line_is_deterministic_and_carries_no_approved_data() -> None:
    """AD-17 and NFR-4a in one line, which is why it is one line."""
    first = external_context_line(Lang.EN, MOMENT)
    assert first == external_context_line(Lang.EN, MOMENT)
    assert first == "language=en; asked_on=2026-09-30"
    assert external_context_line(Lang.AR, MOMENT).startswith("language=ar")


@pytest.mark.parametrize(
    "outcome",
    [
        ExternalOutcome.ANSWERED,
        ExternalOutcome.TIMED_OUT,
        ExternalOutcome.UNAVAILABLE,
        ExternalOutcome.ABANDONED,
    ],
)
def test_all_four_outcomes_reach_the_record(engine: Engine, outcome: ExternalOutcome) -> None:
    """Story 9.9 names four, and a record that could not tell them apart is one number."""
    agent: ExternalAgentPort
    if outcome is ExternalOutcome.ANSWERED:
        agent = ScriptedExternalAgent(prose="an external view")
    elif outcome is ExternalOutcome.ABANDONED:
        agent = ScriptedExternalAgent(prose="late", latency_seconds=999.0)
    else:
        agent = ScriptedExternalAgent(outcome=outcome)
    _, external, evidence = ask_it(with_agent(engine, agent))
    assert external is not None
    assert external.outcome is outcome
    call = evidence["external_call"]
    assert isinstance(call, dict)
    assert call["outcome"] == outcome.value


def test_an_abandoned_call_records_its_orphan_even_when_the_id_was_never_learned(
    engine: Engine,
) -> None:
    """The worst orphan is the one with no name, so it is the one that must still count."""
    released = threading.Event()

    def blocked(_seconds: float) -> None:
        released.wait(30.0)

    agent = ScriptedExternalAgent(prose="late", latency_seconds=5.0, wait=blocked)
    try:
        _, external, evidence = ask_it(with_agent(engine, agent, TINY_BUDGET))
    finally:
        released.set()
    assert external is not None
    assert external.outcome is ExternalOutcome.ABANDONED
    call = evidence["external_call"]
    assert isinstance(call, dict)
    assert call["orphaned_job"] == "unknown"


def test_an_orphan_cannot_be_recorded_against_any_other_outcome() -> None:
    with pytest.raises(ValueError, match="orphaned by being abandoned"):
        ExternalCall(
            outcome=ExternalOutcome.ANSWERED,
            sent_question="q",
            sent_context="c",
            orphaned_job="j-1",
        )


def test_a_record_cannot_claim_an_external_call_the_admission_never_admitted(
    engine: Engine,
) -> None:
    """FR-79: the engine never reaches an external service for an approved-only answer,
    so a record saying it did is a record that is wrong -- refused at construction."""
    answered = answer_question(
        engine,
        Ask(
            question=f"What is {INFLATION} now?",
            lang=Lang.EN,
            sources=SourceAdmission.APPROVED_ONLY,
        ),
    )
    evidence = json.loads(answered.record.answer_json)
    assert evidence["agent"] == SourceAdmission.APPROVED_ONLY.value
    assert evidence["external_call"] is None

    complete = AnswerRecord(
        record_id="r-1",
        recorded_at=MOMENT,
        identity=Anonymous(reason="nothing was asserted"),
        language=Lang.EN,
        question="a question",
        spec=EMPTY_SPEC,
        bindings=tuple(
            FieldBinding(field=name, mechanism=BindingMechanism.UNBOUND)
            for name in SPEC_FIELDS
        ),
    )
    with pytest.raises(ValueError, match="never reaches an external service"):
        dataclasses.replace(
            complete,
            external_call=ExternalCall(
                outcome=ExternalOutcome.ANSWERED, sent_question="q", sent_context="c"
            ),
        )
    with pytest.raises(ValueError, match="not one of the three admissions"):
        dataclasses.replace(complete, agent="oxford")


def test_the_record_stays_within_its_bound_however_long_the_question(
    engine: Engine,
) -> None:
    """NFR-9 and Story 1.16: the external fields are reduced like everything else."""
    agent = ScriptedExternalAgent(prose="an external view")
    answered = answer_question(
        with_agent(engine, agent),
        Ask(
            question=f"What is {INFLATION} now? " + ("and also " * 4000),
            lang=Lang.EN,
            sources=SourceAdmission.BOTH,
        ),
    )
    assert row_size_bytes(answered.record) <= MAX_RECORD_BYTES
    evidence = json.loads(answered.record.answer_json)
    call = evidence["external_call"]
    assert isinstance(call, dict)
    assert call["sent"]["question"].endswith("...")


def test_the_settings_refuse_a_budget_that_cannot_be_honoured() -> None:
    """A misconfigured deployment fails at startup naming the variable, not at t=0."""
    with pytest.raises(ConfigError):
        ExternalAgentSettings.from_env(
            {
                "ASKAI_EXTERNAL_BASE_URL": "http://agent.invalid/v1",
                "ASKAI_EXTERNAL_TOTAL_TIMEOUT": "1",
                "ASKAI_EXTERNAL_READ_TIMEOUT": "30",
            }
        )
    settings = ExternalAgentSettings.from_env(
        {"ASKAI_EXTERNAL_BASE_URL": "http://agent.invalid/v1"}
    )
    assert settings.submit_url == "http://agent.invalid/v1/jobs"
    assert settings.poll_url("j-1") == "http://agent.invalid/v1/jobs/j-1"
    assert settings.api_key is None


def test_a_result_that_did_not_answer_carries_a_degradation_and_no_prose() -> None:
    """AD-15 at the port: a failure with nothing on it is an absence wearing its name."""
    request = a_request()
    with pytest.raises(ValueError, match="at least one degradation"):
        ExternalResult(outcome=ExternalOutcome.UNAVAILABLE, request=request)
    with pytest.raises(ValueError, match="empty card"):
        ExternalResult(outcome=ExternalOutcome.ANSWERED, request=request, prose="  ")
