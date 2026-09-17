"""Six distinct refusals, no substitution, a corrected premise, and one closed question.

Stories 2.7, 2.9, 2.10 and 2.11, which are one story told four ways: **what the engine
says when it is not going to hand over a figure**. 257 of 320 published names are
ambiguous, so this is not the error path -- it is most of the path.

The properties asserted here are the ones that cannot be recovered once they are lost:

* **Six means six** (2.7). The six renderings are pairwise distinct *in both languages*,
  and the mapping from the closed ``FigureCause`` and ``UnboundReason`` sets onto them is
  total. Collapsing two into "I can't answer that" destroys information no downstream
  layer can reconstruct, and the reader who needed the distinction is the QC tester whose
  whole job is to tell a data gap from a catalogue gap from an outage.
* **Never substitute** (2.9). A near miss may be *named* and may never be answered with,
  and nothing becomes an element without a ``source_ref`` the loaded published layer
  resolves.
* **The premise leads** (2.10). A question asserting a figure the data contradicts is
  corrected first, with full provenance, in both lenses.
* **One closed question** (2.11). It names the candidates or the dimension; *"please
  rephrase"* is asserted absent from the whole catalogue, in both languages.

Most of what follows runs against the **real ingested export**, for the reason
``tests/test_operations.py`` gives: these are claims about what a reader is told about
the published data, and a fixture would make them true of the fixture.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.catalogue import (
    ReadModelPresentation,
    ReadModelSources,
    read_model_snapshot,
)
from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.groups import (
    EitherSource,
    ReadModelCatalogueSources,
    ReadModelGroups,
)
from askai.adapters.readmodel.ingest import ingest_published_layer
from askai.adapters.store.provision import Databases, provision
from askai.assemble.format import Formatter
from askai.assemble.provenance import Admitted, Provenance, Refused, admit
from askai.assemble.roles import Lens, Placement, Role
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import (
    BoundBy,
    CompiledQuestion,
    Precedence,
    SpecField,
    UnboundReason,
)
from askai.compile.catalogue import SnapshotCatalogue
from askai.compile.resolve.decide import Offered
from askai.domain.element import Element, ElementClass
from askai.domain.normalise import normalise
from askai.domain.period import Period
from askai.domain.spec import Bound
from askai.execute.readmodel import ReadModelDatapoints
from askai.execute.value import FigureCause, execute_value
from askai.messages import Catalogue, Lang, Plain, load_catalogue
from askai.narrate.clarify import (
    CLARIFY_MESSAGE_IDS,
    ClarificationRate,
    ClarifyCode,
    clarification_for,
    one_question_per_turn,
    prefer_assumption,
)
from askai.narrate.package import AnswerPackage, PackageKind, PackageSource
from askai.narrate.premise import AssertedFigure, contradicts
from askai.narrate.refusal import (
    REFUSAL_MESSAGE_IDS,
    RefusalCode,
    RefusalTally,
    refusal_for,
    refusal_for_unbound,
    refusal_message_id,
    refusal_statement,
)
from askai.narrate.structured import Answer, structured_package
from askai.observability.degradations import DegradationKind
from askai.ports.datapoints import DatapointRow, DatapointsUnavailable
from askai.ports.provenance_source import SourceCatalogue
from askai.rules import RuleSet, RuleStatus, rules
from askai.rules.schema import RuleKind

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_ROOT: Final = PROJECT_ROOT / "data"
MESSAGES: Final = PROJECT_ROOT / "src" / "askai" / "messages" / "data"

TODAY: Final = date(2026, 9, 17)

#: Published, monthly, and with a figure at 2026-04 -- the row the deployed engine
#: answered from on the VM, which is why the premise correction is proved against it.
INFLATION: Final = "Inflation"
INFLATION_PERIOD: Final = "April 2026"
INFLATION_ASKED: Final = f"What was {INFLATION} in {INFLATION_PERIOD}?"
#: The published digits, read from the export rather than from the rendered answer --
#: 2.6162, shown as "2.6" at headline precision. A premise is compared against what was
#: published, not against what the answer happened to round it to.
INFLATION_VALUE: Final = Decimal("2.6162")
INFLATION_SHOWN: Final = "2.6"

#: A question naming nothing the published catalogue holds. The nearest lexical
#: neighbours are real indicators, which is exactly why it must not be answered with one.
NOTHING_LIKE_IT: Final = "What is the gross national happiness index?"

#: Phrases that mean *"say it again differently"*. FR-92 forbids all of them, and the
#: scan is over the rendered catalogue rather than over code because the sentence could
#: only ever arrive as data.
REPHRASE_EN: Final = (
    "rephrase",
    "rephrasing",
    "reword",
    "try again",
    "ask again",
    "be more specific",
    "clarify your question",
)
REPHRASE_AR: Final = ("صياغة", "أعد السؤال", "اسأل مرة", "وضّح سؤالك")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


@pytest.fixture(scope="module")
def ingested() -> Iterator[Databases]:
    with provision() as databases:
        ingest_published_layer(databases.read_model, CmsExport.rooted(EXPORT_ROOT))
        yield databases


@pytest.fixture(scope="module")
def read_model(ingested: Databases) -> sqlite3.Connection:
    return ingested.read_model


@pytest.fixture(scope="module")
def names(read_model: sqlite3.Connection) -> SnapshotCatalogue:
    return read_model_snapshot(read_model)


@pytest.fixture(scope="module")
def groups(read_model: sqlite3.Connection) -> ReadModelGroups:
    return ReadModelGroups(read_model)


@pytest.fixture(scope="module")
def sources(read_model: sqlite3.Connection) -> EitherSource:
    return EitherSource(
        datapoints=ReadModelSources(read_model),
        catalogue=ReadModelCatalogueSources(read_model),
    )


@pytest.fixture(scope="module")
def formatter(catalogue: Catalogue, rule_set: RuleSet) -> Formatter:
    return Formatter(catalogue=catalogue, rule_set=rule_set)


@pytest.fixture(scope="module")
def placement(rule_set: RuleSet) -> Placement:
    return Placement(rule_set=rule_set)


# ---------------------------------------------------------------------------- helpers


EMPTY_CATALOGUE: Final = SnapshotCatalogue()


class NothingResolves:
    """A ``SourceCatalogue`` that resolves no reference at all.

    The shape a read model takes when the refresh that built the elements has been
    superseded by one that retired their rows. Every element composed against it is
    refused, which is the state AD-7 is about.
    """

    def resolves(self, source_ref: str) -> bool:
        return False


class UnreachableDatapoints:
    """A ``DatapointsPort`` whose store does not answer -- an outage, not an absence."""

    def publishes(self, detail_id: str) -> bool:
        raise DatapointsUnavailable("the read model is not reachable in this test")

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        raise DatapointsUnavailable("the read model is not reachable in this test")

    def row(
        self, detail_id: str, period: Period, country_id: str | None
    ) -> DatapointRow | None:
        raise DatapointsUnavailable("the read model is not reachable in this test")


def compiled(
    asked: str,
    *,
    history: tuple[str, ...] = (),
    catalogue: SnapshotCatalogue = EMPTY_CATALOGUE,
) -> CompiledQuestion:
    return compile_question(
        CompileInput(question=asked, today=TODAY, history=history), catalogue
    )


def answered(
    asked: str,
    lang: Lang,
    *,
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: SourceCatalogue,
    groups: ReadModelGroups | None = None,
    premise: AssertedFigure | None = None,
    suggestion: str | None = None,
) -> AnswerPackage:
    """One question, all the way through: compile, execute, compose."""
    question = compiled(asked, catalogue=names)
    execution = execute_value(question, ReadModelDatapoints(read_model))
    detail = question.spec.detail
    published = (
        ReadModelPresentation(connection=read_model).detail(detail.value, lang)
        if isinstance(detail, Bound)
        else None
    )
    return structured_package(
        Answer(
            question=question,
            execution=execution,
            lang=lang,
            published=published,
            premise=premise,
            suggestion=suggestion,
        ),
        catalogue,
        formatter,
        placement,
        sources,
        groups,
    )


def a_shared_name(read_model: sqlite3.Connection) -> str:
    """A published name two details share -- the commonest question the engine gets.

    Found in the export rather than named here: which name is shared is a fact about the
    published data, and a hard-coded one would make this test true of a spelling instead
    of true of the ambiguity.
    """
    names = read_model_snapshot(read_model)
    for row in read_model.execute("SELECT name_en FROM detail ORDER BY detail_id"):
        spelling = str(row[0])
        if len(names.details_named(normalise(spelling))) > 1:
            return spelling
    raise AssertionError("the export is expected to publish an ambiguous detail name")


def rendered(catalogue: Catalogue, lang: Lang, message_id: str) -> str:
    """A message with every parameter filled, so two wordings can be compared as text."""
    entry = catalogue.entry(lang, message_id)
    assert isinstance(entry, Plain), f"{message_id} is counted; the six refusals are not"
    return entry.text.format(**{field: "X" for field in catalogue.parameters(message_id)})


# ==================================================== Story 2.7 -- six means six


def test_the_six_refusals_are_six(catalogue: Catalogue) -> None:
    """FR-38 names six causes; the closed set has exactly six members and six ids."""
    assert len(RefusalCode) == 6
    assert set(REFUSAL_MESSAGE_IDS) == set(RefusalCode)
    ids = list(REFUSAL_MESSAGE_IDS.values())
    assert len(set(ids)) == 6, "two causes sharing an id is five sentences, not six"
    for message_id in ids:
        for lang in Lang:
            assert catalogue.entry(lang, message_id)


@pytest.mark.parametrize("lang", list(Lang))
def test_the_six_renderings_are_pairwise_distinct(catalogue: Catalogue, lang: Lang) -> None:
    """The acceptance criterion, and the one property nothing downstream can restore.

    A reader who is shown the same sentence for an editorial gap and for an outage has
    been told the same thing about two different worlds. Asserted per language, because a
    catalogue can be six ways distinct in English and three ways distinct in Arabic -- and
    that is precisely the drift the two files are reviewed side by side to catch.
    """
    said = {code: rendered(catalogue, lang, refusal_message_id(code)) for code in RefusalCode}
    assert len(set(said.values())) == 6, (
        f"{lang.value}: two of the six causes read identically -- "
        f"{sorted(said.values())}"
    )


@pytest.mark.parametrize("cause", list(FigureCause))
def test_every_figure_cause_is_said_as_one_of_the_six(cause: FigureCause) -> None:
    """Total over the closed set. A cause with no wording reaches a reader as a blank."""
    assert refusal_for(cause) in set(RefusalCode)


@pytest.mark.parametrize("reason", list(UnboundReason))
def test_every_unbound_reason_is_said_as_one_of_the_six(reason: UnboundReason) -> None:
    """Total over ``UnboundReason`` too -- the other closed set a non-answer arrives on."""
    assert refusal_for_unbound(reason) in set(RefusalCode)


def test_the_causes_are_not_collapsed_onto_three() -> None:
    """The regression this story is: a mapping that lands on fewer than the six is one
    that has quietly merged two facts about the world back together."""
    reached = {refusal_for(cause) for cause in FigureCause}
    assert len(reached) >= 4, (
        "the fetch can produce at most four of the six on its own -- the other two are "
        "reached from the catalogue layer -- but landing on fewer than four means the "
        "table has collapsed causes that were kept apart"
    )


def test_an_empty_detail_and_an_empty_period_are_different_refusals() -> None:
    """Cause three against cause four, which is the pair most often collapsed.

    28 of the published details carry no data points at all. A reader told "no data for
    that period" retries twenty periods that are all equally empty; a reader told "this
    indicator does not exist" stops asking about something the catalogue does hold.
    """
    assert refusal_for(FigureCause.DETAIL_PUBLISHES_NOTHING) is RefusalCode.PUBLISHED_WITH_NO_DATA
    assert (
        refusal_for(FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD)
        is RefusalCode.NO_DATA_FOR_THIS_SELECTION
    )
    assert refusal_for(FigureCause.DETAIL_PUBLISHES_NOTHING) is not refusal_for(
        FigureCause.NO_ROW_FOR_THE_NAMED_PERIOD
    )


def test_a_lookup_failure_is_the_unreachable_cause_and_not_an_absence() -> None:
    """AD-15, findings 23/128/150: the fault is said as a fault."""
    assert refusal_for(FigureCause.LOOKUP_FAILED) is RefusalCode.DATA_COULD_NOT_BE_REACHED


# ------------------------------------------------- the code travels with the package


def test_a_refusal_carries_its_machine_code_beside_its_message_id(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """FR-38's second clause. The code is what a dashboard counts; the id is what a
    reviewer opens the catalogue at, and the two are on the package together."""
    package = answered(
        NOTHING_LIKE_IT,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
    )
    assert package.kind is PackageKind.REFUSAL
    assert package.refusal_code is RefusalCode.NO_SUCH_INDICATOR
    assert package.reason_id == refusal_message_id(RefusalCode.NO_SUCH_INDICATOR)
    assert package.reason == refusal_statement(catalogue, Lang.EN, RefusalCode.NO_SUCH_INDICATOR)


def test_a_clarification_is_not_counted_as_a_refusal(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """An engine that asks well must not look like an engine that fails often."""
    package = answered(
        f"What is {a_shared_name(read_model)}?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
    )
    assert package.kind is PackageKind.CLARIFICATION
    assert package.refusal_code is None
    assert package.reason_id in set(CLARIFY_MESSAGE_IDS.values())


def test_a_package_cannot_be_a_refusal_without_naming_its_cause(
    names: SnapshotCatalogue, catalogue: Catalogue
) -> None:
    """The invariant, rather than a convention about how the constructor is called."""
    question = compiled("What is inflation?")
    with pytest.raises(ValueError, match="six causes"):
        AnswerPackage(
            source=PackageSource.APPROVED,
            kind=PackageKind.REFUSAL,
            agent="x",
            spec=question.spec,
            bindings=question.bindings,
            reason="x",
            reason_id="refusal.no_such_indicator",
        )


def test_a_clarification_cannot_claim_a_refusal_cause(catalogue: Catalogue) -> None:
    question = compiled("What is inflation?")
    with pytest.raises(ValueError, match="six causes"):
        AnswerPackage(
            source=PackageSource.APPROVED,
            kind=PackageKind.CLARIFICATION,
            agent="x",
            spec=question.spec,
            bindings=question.bindings,
            reason="x",
            reason_id="clarify.which_indicator",
            refusal_code=RefusalCode.NO_SUCH_INDICATOR,
        )


# ------------------------------------------------------------ counted by cause


def test_refusals_are_counted_by_cause() -> None:
    """The PRD's coverage ceiling is only readable per cause: a rising
    ``DATA_COULD_NOT_BE_REACHED`` is an outage and a rising
    ``PUBLISHED_WITH_NO_DATA`` is the engine being honest about 28 empty details."""
    tally = RefusalTally.of(
        [
            RefusalCode.NO_SUCH_INDICATOR,
            RefusalCode.NO_SUCH_INDICATOR,
            RefusalCode.DATA_COULD_NOT_BE_REACHED,
        ]
    )
    assert tally.total == 3
    assert tally.count(RefusalCode.NO_SUCH_INDICATOR) == 2
    assert tally.count(RefusalCode.DATA_COULD_NOT_BE_REACHED) == 1
    assert tally.count(RefusalCode.PUBLISHED_WITH_NO_DATA) == 0
    assert set(tally.as_mapping()) == {
        RefusalCode.NO_SUCH_INDICATOR,
        RefusalCode.DATA_COULD_NOT_BE_REACHED,
    }


def test_two_tallies_of_the_same_causes_are_equal_whatever_order_they_arrived_in() -> None:
    first = RefusalTally.of([RefusalCode.NO_SUCH_INDICATOR, RefusalCode.QUESTION_NOT_SUPPORTED])
    second = RefusalTally.of([RefusalCode.QUESTION_NOT_SUPPORTED, RefusalCode.NO_SUCH_INDICATOR])
    assert first == second and hash(first) == hash(second)


def test_a_tally_travels_up_a_call_chain_without_a_shared_counter() -> None:
    """AD-15: the count is on the value, so two requests cannot corrupt one."""
    combined = RefusalTally.of([RefusalCode.NO_SUCH_INDICATOR]) + RefusalTally.of(
        [RefusalCode.NO_SUCH_INDICATOR, RefusalCode.PUBLISHED_WITH_NO_DATA]
    )
    assert combined.count(RefusalCode.NO_SUCH_INDICATOR) == 2
    assert combined.total == 3


def test_an_absent_cause_is_absent_rather_than_zero() -> None:
    assert not RefusalTally.of([])
    with pytest.raises(ValueError, match="absent cause"):
        RefusalTally(counts=((RefusalCode.NO_SUCH_INDICATOR, 0),))


# ------------------------------------- an unreachable dependency is never an absence


def test_an_unreachable_store_is_a_typed_degradation_and_never_no_approved_figures(
    names: SnapshotCatalogue,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """AD-15's clause, end to end: the reader is told the data could not be read, the
    package carries the counted degradation, and the cause is the sixth and not the
    first, third or fourth -- all of which would be statements about the data."""
    question = compiled(f"What is {INFLATION} now?", catalogue=names)
    execution = execute_value(question, UnreachableDatapoints())
    package = structured_package(
        Answer(question=question, execution=execution, lang=Lang.EN, published=None),
        catalogue,
        formatter,
        placement,
        sources,
    )
    assert package.kind is PackageKind.REFUSAL
    assert package.refusal_code is RefusalCode.DATA_COULD_NOT_BE_REACHED
    assert [degradation.kind for degradation in package.degradations] == [
        DegradationKind.ADAPTER_UNAVAILABLE.value
    ]
    absences = {
        RefusalCode.NO_SUCH_INDICATOR,
        RefusalCode.PUBLISHED_WITH_NO_DATA,
        RefusalCode.NO_DATA_FOR_THIS_SELECTION,
    }
    assert package.refusal_code not in absences
    assert package.reason_id not in {refusal_message_id(code) for code in absences}
    assert package.reason is not None and "could not be read" in package.reason


# ------------------------------------------------ the wording rules are in the catalogue


def test_the_refusal_wording_rules_are_data_rather_than_code(rule_set: RuleSet) -> None:
    """FR-63's second clause: the wording rules are the catalogue's `wording` entries.

    Asserted as a property of the rule set rather than by naming a file, so moving a rule
    between files does not fail this and deleting one does.
    """
    wording = [
        entry
        for entry in rule_set
        if entry.rule.kind is RuleKind.WORDING and entry.id.startswith(("R-REFUSAL-", "R-CLARIFY-"))
    ]
    assert len(wording) >= 5, [entry.id for entry in wording]
    for entry in wording:
        assert entry.rule.status is not RuleStatus.REJECTED
        assert entry.rule.sources


def test_the_six_causes_and_the_no_substitution_rule_are_both_recorded(
    rule_set: RuleSet,
) -> None:
    for rule_id in (
        "R-REFUSAL-SIX-DISTINCT-CAUSES",
        "R-REFUSAL-EMPTY-IS-NOT-ABSENT",
        "R-REFUSAL-FAILURE-IS-NEVER-AN-ABSENCE",
        "R-REFUSAL-NEVER-SUBSTITUTES",
    ):
        assert rule_set.fire(rule_id).kind is RuleKind.WORDING


# ============================== Story 2.9 -- never substitute, never invent


def test_a_near_miss_is_named_as_a_suggestion_and_never_answered_with(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """FR-39: *"Nominal GDP"* asked, only *"Real GDP"* published.

    The package stays a refusal, carries no element and therefore no figure, and the
    similar indicator appears only inside the stated reason -- as its own sentence, from
    its own message id, marked as not what was asked.
    """
    package = answered(
        NOTHING_LIKE_IT,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        suggestion="Real GDP",
    )
    assert package.kind is PackageKind.REFUSAL
    assert package.elements == ()
    assert package.row_ids == ()
    assert package.reason is not None and "Real GDP" in package.reason
    plain = refusal_statement(catalogue, Lang.EN, RefusalCode.NO_SUCH_INDICATOR)
    assert package.reason.startswith(plain), "the refusal's own sentence is unchanged"
    assert len(package.reason) > len(plain), "the suggestion is a second sentence"


@pytest.mark.parametrize("lang", list(Lang))
def test_the_suggestion_sentence_exists_in_both_languages(
    catalogue: Catalogue, lang: Lang
) -> None:
    assert catalogue.entry(lang, "suggestion.not_what_you_asked")
    assert catalogue.parameters("suggestion.not_what_you_asked") == frozenset({"suggestion"})


def test_a_suggestion_is_never_offered_beside_a_failure(
    names: SnapshotCatalogue,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """A near miss beside *"the data could not be read"* would read as the engine
    proposing a workaround for its own outage."""
    question = compiled(f"What is {INFLATION} now?", catalogue=names)
    execution = execute_value(question, UnreachableDatapoints())
    package = structured_package(
        Answer(
            question=question,
            execution=execution,
            lang=Lang.EN,
            published=None,
            suggestion="Real GDP",
        ),
        catalogue,
        formatter,
        placement,
        sources,
    )
    assert package.reason is not None and "Real GDP" not in package.reason


def test_no_figure_is_produced_when_nothing_resolves_against_the_published_layer(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
) -> None:
    """FR-40 and AD-3, at the point a figure would have become reader-facing.

    The fetch found a real row; the published layer the answer is admitted against
    resolves nothing. No element survives, so no figure exists in the answer -- and the
    result is the failure cause, never *"no approved figures for that period"*.
    """
    package = answered(
        f"What is {INFLATION} now?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=NothingResolves(),
    )
    assert package.kind is PackageKind.REFUSAL
    assert package.elements == ()
    assert package.refusal_code is RefusalCode.DATA_COULD_NOT_BE_REACHED


def test_an_element_whose_source_ref_does_not_resolve_is_refused_not_dropped() -> None:
    """AD-7, asserted directly on ``admit`` -- the regression test for behaviour
    ``assemble/`` already has, so that a later refactor cannot turn it into a
    ``continue``. A silent drop leaves a short answer that reads exactly like a
    complete one, which is the whole failure the typed refusal prevents.
    """
    provenance = Provenance(
        detail_id="D-1",
        period=Period("2026-04"),
        country=None,
        source_id="S-1",
    )
    element = Element(
        content="x",
        element_class=ElementClass.MEASURED,
        source_ref=provenance.source_ref,
    )
    match admit(element, NothingResolves()):
        case Refused(degradation=degradation):
            assert degradation.kind
            assert degradation.where
            assert provenance.source_ref in degradation.detail
        case Admitted():  # pragma: no cover -- nothing resolves, by construction
            pytest.fail("an unresolvable source_ref was admitted")


# ================================ Story 2.10 -- correct a premise the data contradicts


def test_a_premise_the_data_contradicts_is_corrected_first(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """FR-41 and FR-58. The correction is element zero, because it answers the question
    that was actually asked -- and a briefing built on the asserted figure is what a
    correction arriving second does not prevent."""
    package = answered(
        INFLATION_ASKED,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        premise=AssertedFigure(value=Decimal("0.2")),
    )
    assert package.kind is PackageKind.ANSWER
    correction = package.elements[0]
    assert correction.role is Role.HEADLINE
    assert correction.element.content != package.elements[1].element.content
    assert INFLATION_SHOWN in correction.element.content


def test_the_correction_carries_the_published_figure_with_its_provenance(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """A correction a reader cannot check is an assertion, which is what it corrects."""
    package = answered(
        INFLATION_ASKED,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        premise=AssertedFigure(value=Decimal("0.2")),
    )
    correction = package.elements[0].element
    assert correction.element_class is ElementClass.MEASURED
    assert correction.source_ref
    # The same reference the headline carries: one row, corrected and then answered from.
    assert correction.source_ref == package.elements[1].element.source_ref


def test_the_correction_appears_in_both_lenses(placement: Placement) -> None:
    """FR-59d: an executive is not shielded from the fact that their premise was wrong.

    A property of the role table rather than of the composer: ``headline`` is named by
    both lenses in ``R-ROLE-LENS-MAPPING``, so brevity cannot remove the correction
    without removing the answer with it.
    """
    assert placement.lenses_for(Role.HEADLINE) == frozenset(Lens)


def test_a_premise_the_data_supports_produces_no_correction(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """Manufacturing a correction for a premise that is right trains a reader to skip
    them, which costs exactly the case the story is about."""
    with_premise = answered(
        INFLATION_ASKED,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        premise=AssertedFigure(value=INFLATION_VALUE),
    )
    without = answered(
        INFLATION_ASKED,
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
    )
    assert len(with_premise.elements) == len(without.elements)


def test_trailing_zeros_are_not_a_contradiction() -> None:
    """A premise is compared numerically; ``2.6`` and ``2.60`` are the same figure."""
    assert not contradicts(AssertedFigure(value=Decimal("2.60")), Decimal("2.6"))
    assert contradicts(AssertedFigure(value=Decimal("0.2")), Decimal("2.6"))


@pytest.mark.parametrize("lang", list(Lang))
def test_the_correction_is_worded_in_both_languages(catalogue: Catalogue, lang: Lang) -> None:
    assert catalogue.entry(lang, "premise.corrected")
    assert catalogue.parameters("premise.corrected") == frozenset(
        {"detail", "value", "unit", "period"}
    )


# ============================= Story 2.11 -- one specific, closed clarifying question


@pytest.mark.parametrize("lang", list(Lang))
def test_no_message_in_the_catalogue_asks_the_reader_to_rephrase(
    catalogue: Catalogue, lang: Lang
) -> None:
    """FR-92, asserted over the whole catalogue in both languages.

    A scan over rendered messages rather than over the raw file, so a comment explaining
    *why* the engine never says it cannot fail the test the comment is about.
    """
    banned = REPHRASE_EN if lang is Lang.EN else REPHRASE_AR
    offences = [
        f"{message_id}: {phrase}"
        for message_id, entry in catalogue.entries[lang].items()
        for text in ([entry.text] if isinstance(entry, Plain) else list(entry.forms.values()))
        for phrase in banned
        if phrase.lower() in text.lower()
    ]
    assert not offences, (
        "'please rephrase' hands the engine's problem back to the reader (FR-92):\n  "
        + "\n  ".join(offences)
    )


def test_a_clarifying_question_names_the_candidates(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """Specific and closed (FR-92): the question carries the names, not an invitation."""
    shared = a_shared_name(read_model)
    package = answered(
        f"What is {shared}?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
    )
    assert package.kind is PackageKind.CLARIFICATION
    assert package.reason_id == CLARIFY_MESSAGE_IDS[ClarifyCode.WHICH_INDICATOR]
    assert package.reason is not None and package.reason.strip()
    # The options parameter was filled from the particulars, so the question is closed.
    template = catalogue.entry(Lang.EN, package.reason_id)
    assert isinstance(template, Plain)
    assert len(package.reason) > len(template.text)


def test_at_most_one_clarifying_question_is_asked_in_a_turn(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    rule_set: RuleSet,
) -> None:
    """FR-93, structurally: a package carries one ``reason_id``, so there is no list of
    questions that could grow to two."""
    assert one_question_per_turn(rule_set)
    package = answered(
        f"What is {a_shared_name(read_model)}?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
    )
    assert isinstance(package.reason_id, str)
    asked = [
        message_id
        for message_id in CLARIFY_MESSAGE_IDS.values()
        if message_id == package.reason_id
    ]
    assert len(asked) == 1


@pytest.mark.parametrize("reason", list(UnboundReason))
def test_every_unbound_reason_either_asks_one_question_or_refuses(
    reason: UnboundReason,
) -> None:
    """Total, and never both: the two outcomes are exclusive by construction."""
    asked = clarification_for(reason)
    assert asked is None or asked in set(ClarifyCode)


def test_a_dominant_candidate_is_answered_under_an_assumption_rather_than_asked_about(
    rule_set: RuleSet,
) -> None:
    """FR-93's preference, with its threshold in ``rules/`` rather than in code."""
    candidates = (
        Offered(detail_id="D-1", indicator_id="I-1", surface="Real GDP", score=9.0),
        Offered(detail_id="D-2", indicator_id="I-2", surface="Nominal GDP", score=1.0),
    )
    dominant = prefer_assumption(candidates, rule_set)
    assert dominant is not None and dominant.detail_id == "D-1"


def test_an_unseparated_candidate_set_is_asked_about_rather_than_guessed(
    rule_set: RuleSet,
) -> None:
    """The case FR-2 exists for: with 257 of 320 names shared, guessing is wrong often."""
    candidates = (
        Offered(detail_id="D-1", indicator_id="I-1", surface="Real GDP", score=1.0),
        Offered(detail_id="D-2", indicator_id="I-2", surface="Nominal GDP", score=0.98),
    )
    assert prefer_assumption(candidates, rule_set) is None


def test_a_candidate_set_no_signal_spoke_about_is_never_dominant(rule_set: RuleSet) -> None:
    """Every score zero means every candidate is equally unseparated; picking the one
    that sorted first is a confident answer about nothing."""
    candidates = (
        Offered(detail_id="D-1", indicator_id="I-1", surface="A", score=0.0),
        Offered(detail_id="D-2", indicator_id="I-2", surface="B", score=0.0),
    )
    assert prefer_assumption(candidates, rule_set) is None


def test_a_single_candidate_is_a_binding_and_not_a_question(rule_set: RuleSet) -> None:
    single = (Offered(detail_id="D-1", indicator_id="I-1", surface="A", score=5.0),)
    assert prefer_assumption(single, rule_set) is None
    assert prefer_assumption((), rule_set) is None


def test_the_clarification_rate_is_a_tracked_counter_metric() -> None:
    """FR-93's metric. Frozen and combinable, with the denominator carried: a rate with
    no turn count cannot be compared between two days."""
    rate = ClarificationRate(turns=4, clarifications=1)
    assert rate.rate == pytest.approx(0.25)
    assert (rate + ClarificationRate(turns=4, clarifications=3)).rate == pytest.approx(0.5)
    assert ClarificationRate().rate == 0.0


def test_the_rate_cannot_record_two_questions_in_one_turn() -> None:
    with pytest.raises(ValueError, match="at most one question per turn"):
        ClarificationRate(turns=1, clarifications=2)


def test_a_reply_to_a_clarification_preserves_what_was_bound_and_is_the_readers(
    names: SnapshotCatalogue,
) -> None:
    """FR-94 and FR-14. The reply completes the existing query rather than starting one:
    the earlier turn is an input to compiling, a field carried over is
    ``inherited-from-history`` by precedence and ``reader`` by authority, and the two axes
    stay separate precisely so this case does not have to collapse them."""
    first = compiled(f"What was {INFLATION} in April 2026?", catalogue=names)
    reply = compiled(
        "and the monthly figure",
        history=(f"What was {INFLATION} in April 2026?",),
        catalogue=names,
    )
    assert isinstance(first.spec.detail, Bound)
    detail = reply.spec.detail
    assert isinstance(detail, Bound), "the reply lost the indicator the first turn bound"
    assert detail.value == first.spec.detail.value
    binding = reply.by_field[SpecField.DETAIL]
    assert binding.precedence is Precedence.INHERITED_FROM_HISTORY
    assert binding.bound_by is BoundBy.READER


def test_a_reply_never_records_the_engine_as_the_binder(names: SnapshotCatalogue) -> None:
    """The authority axis is the reader's, whatever rung carried the value across."""
    reply = compiled(
        "and the monthly figure",
        history=(f"What was {INFLATION} in April 2026?",),
        catalogue=names,
    )
    inherited = [
        binding
        for binding in reply.bindings
        if binding.precedence is Precedence.INHERITED_FROM_HISTORY
    ]
    assert inherited, "nothing was inherited, so this asserts nothing"
    assert all(binding.bound_by is BoundBy.READER for binding in inherited)


# --------------------------------------------------------- the two files stay in step


@pytest.mark.parametrize(
    "message_id",
    sorted(
        set(REFUSAL_MESSAGE_IDS.values())
        | set(CLARIFY_MESSAGE_IDS.values())
        | {"suggestion.not_what_you_asked", "premise.corrected", "clarify.assumed"}
    ),
)
def test_every_id_this_batch_added_exists_in_both_languages(
    catalogue: Catalogue, message_id: str
) -> None:
    for lang in Lang:
        assert catalogue.entry(lang, message_id)


def test_the_arabic_refusals_are_authored_arabic_rather_than_the_english_ones(
    catalogue: Catalogue,
) -> None:
    """The halves are one artifact in two languages, not a translation layer."""
    for code in RefusalCode:
        message_id = refusal_message_id(code)
        assert rendered(catalogue, Lang.AR, message_id) != rendered(
            catalogue, Lang.EN, message_id
        )


