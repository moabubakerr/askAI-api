"""The operation is read from the question, and it decides which composer answers.

Two halves, and they were two separate holes.

**Binding.** ``QuerySpec.operation`` existed from Epic 1 and nothing ever set it: every
question in the system compiled to ``value`` by ``R-BIND-DEFAULT-OPERATION``, so *"What
does inflation mean?"* and *"What is inflation now?"* compiled to the same spec and were
answered with the same figure. The question's noun was read and its verb was discarded.
``compile.operations`` reads the verb, from the bilingual phrase tables in
``rules/data/operation-words.yaml``, with no model anywhere near it (AD-22, NFR-1).

**Dispatch.** Nothing in the tree branched on the field either -- a scan for ``Operation.``
across ``narrate/``, ``respond/`` and ``assemble/`` found no use -- so the composers Epics
3, 4 and 5 built were complete, tested and unreachable. ``narrate.dispatch`` is the
branch, and the scan below asserts the branch exists rather than trusting it.

Most of what follows runs against the **real ingested export**, for the reason
``tests/test_meta.py`` gives: the definition this proves end to end is a paragraph in
``data/``, and a fixture would let it be true of the fixture and false of the export.
"""

from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from datetime import date
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
from askai.assemble.roles import Placement, Role
from askai.compile.binder import CompileInput, compile_question
from askai.compile.binding import BoundBy, CompiledQuestion, Precedence, SpecField
from askai.compile.catalogue import SnapshotCatalogue
from askai.compile.lexicon import (
    OperationClause,
    OperationRule,
    bare_subject_frames,
    multi_reading_is_a_series,
    operation_order,
    operation_words,
)
from askai.domain.element import ElementClass
from askai.domain.normalise import normalise
from askai.domain.spec import Bound, Operation
from askai.execute.readmodel import ReadModelDatapoints
from askai.execute.value import execute_value
from askai.messages import Catalogue, Lang, load_catalogue
from askai.narrate.dispatch import (
    Composed,
    NotHeld,
    Request,
    Unwired,
    compose_operation,
)
from askai.narrate.package import AnswerPackage, PackageKind
from askai.narrate.structured import Answer, structured_package
from askai.rules import RuleSet, rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

TODAY: Final = date(2026, 9, 16)

#: The detail the deployed defect was demonstrated on, and the one this proves fixed.
#: Measured against ``data/`` on 2026-09-16: it publishes a real paragraph in both
#: languages, which is what makes it the honest case -- 88 of 289 details publish ``-``.
INFLATION_DETAIL: Final = "e4293295-fb43-46b0-7ac5-08dec461c23d"
INFLATION: Final = "Inflation"

#: Published names that *contain* an operation word, from the real export. A question
#: naming one of these is a question about that indicator, not about change or ranking.
GROWTH_NAMED_DETAIL: Final = "Global Merchandise Trade Growth"
RANK_NAMED_DETAIL: Final = "MSCI Rank"

#: The packages whose modules must contain the branch on the operation. Before this
#: story none of them did.
DISPATCHING_PACKAGES: Final = ("narrate",)


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


# --------------------------------------------------------------------------- helpers

EMPTY_CATALOGUE: Final = SnapshotCatalogue()


def compiled(
    asked: str,
    *,
    history: tuple[str, ...] = (),
    catalogue: SnapshotCatalogue = EMPTY_CATALOGUE,
) -> CompiledQuestion:
    return compile_question(
        CompileInput(question=asked, today=TODAY, history=history), catalogue
    )


def operation_of(asked: str) -> Operation:
    state = compiled(asked).spec.operation
    assert isinstance(state, Bound), f"{asked!r} bound no operation: {state}"
    return state.value


def answered(
    asked: str,
    lang: Lang,
    *,
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups | None,
) -> AnswerPackage:
    """One question, all the way through: compile, execute, compose.

    The whole answer path bar the transport and the audit record, run the way
    ``api.ask.answer_question`` runs it -- with the one addition that module cannot make
    today, the catalogue port. The published detail is read for every question rather than
    only for one that produced a figure, which is the change ``api/ask.py`` needs for a
    definition to be able to name its indicator.
    """
    question = compiled(asked, catalogue=names)
    execution = execute_value(question, ReadModelDatapoints(read_model))
    detail = question.spec.detail
    published = (
        ReadModelPresentation(connection=read_model).detail(detail.value, lang)
        if isinstance(detail, Bound)
        else None
    )
    return structured_package(
        Answer(question=question, execution=execution, lang=lang, published=published),
        catalogue,
        formatter,
        placement,
        sources,
        groups,
    )


# ============================================================ the tables are well formed


def test_every_operation_has_a_phrase_table_and_a_place_in_the_order() -> None:
    """Derived from ``Operation`` rather than listed, so a member added to the domain
    fails here -- naming the clause the file is missing -- instead of silently having no
    words and never being classified."""
    assert set(operation_order()) == set(Operation)
    assert len(operation_order()) == len(Operation)
    assert set(operation_words()) == set(Operation)


def test_the_order_in_the_file_is_the_order_the_tables_are_walked() -> None:
    """The precedence is data (AD-11) and the mapping's insertion order *is* it, so a
    reviewer changing the file changes what the classifier does."""
    declared = rules().value(OperationRule.PRECEDENCE.value, OperationClause.ORDER.value)
    assert tuple(member.value for member in operation_words()) == declared


@pytest.mark.parametrize(
    "phrases",
    [*operation_words().values(), bare_subject_frames()],
    ids=lambda phrases: f"{len(phrases)}-phrases",
)
def test_every_phrase_in_the_operation_file_is_already_in_normal_form(
    phrases: frozenset[str],
) -> None:
    """A phrase that is not in normal form can never match, because the question always
    is. Silent, permanent, and exactly finding 121's Arabic half."""
    assert {phrase for phrase in phrases if normalise(phrase) != phrase} == set()


@pytest.mark.parametrize("rule", list(OperationRule))
def test_every_operation_rule_is_loaded_and_fireable(rule: OperationRule) -> None:
    assert rules().fire(rule.value).is_fireable


def test_value_and_explanation_name_no_words_on_purpose() -> None:
    """``value`` is the rule default and must stay reachable only as the last rung;
    ``explanation`` has no approved source to quote, so binding it would produce a
    refusal that reads like a missing feature."""
    assert operation_words()[Operation.VALUE] == frozenset()
    assert operation_words()[Operation.EXPLANATION] == frozenset()


def test_both_languages_are_carried_for_every_operation_that_has_words() -> None:
    """A word list living in code is a word list Arabic gets added to last. Every table
    that has any words has words in both scripts."""
    for operation, phrases in operation_words().items():
        if not phrases:
            continue
        latin = {phrase for phrase in phrases if phrase.isascii()}
        arabic = phrases - latin
        assert latin, f"{operation.value} has no English phrases"
        assert arabic, f"{operation.value} has no Arabic phrases"


# ============================================================== the verb is read, at last


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        # definition -- English, then Arabic
        ("What does inflation mean?", Operation.DEFINITION),
        ("Define inflation", Operation.DEFINITION),
        ("What is the definition of inflation?", Operation.DEFINITION),
        ("ماذا يعني التضخم؟", Operation.DEFINITION),
        ("ما تعريف التضخم؟", Operation.DEFINITION),
        ("ما معني التضخم؟", Operation.DEFINITION),
        # series
        ("Show me the trend for inflation", Operation.SERIES),
        ("What is the history of inflation?", Operation.SERIES),
        ("اتجاه التضخم", Operation.SERIES),
        ("تطور التضخم عبر الزمن", Operation.SERIES),
        # change
        ("How much did inflation change?", Operation.CHANGE),
        ("What was the growth in inflation?", Operation.CHANGE),
        ("التغير في التضخم", Operation.CHANGE),
        ("معدل النمو", Operation.CHANGE),
        # comparison
        ("Compare inflation and unemployment", Operation.COMPARISON),
        ("Inflation versus unemployment", Operation.COMPARISON),
        ("قارن التضخم والبطاله", Operation.COMPARISON),
        ("التضخم مقابل البطاله", Operation.COMPARISON),
        # extremum
        ("Which country has the highest inflation?", Operation.EXTREMUM),
        ("What is the lowest reading?", Operation.EXTREMUM),
        ("Who is the worst performer?", Operation.EXTREMUM),
        ("اعلي معدل تضخم", Operation.EXTREMUM),
        ("ادني قيمه", Operation.EXTREMUM),
        # rank
        ("What is the rank of inflation?", Operation.RANK),
        ("Our ranking among peers", Operation.RANK),
        ("ترتيب التضخم", Operation.RANK),
        ("المرتبه بين الدول المقارنه", Operation.RANK),
        # count
        ("How many indicators are published?", Operation.COUNT),
        ("The number of indicators", Operation.COUNT),
        ("كم عدد المؤشرات؟", Operation.COUNT),
        ("ما عدد المؤشرات؟", Operation.COUNT),
        # "كم" on its own opens "how much was inflation" as readily as "how many
        # indicators", so it is not a count word and this stays a value question.
        ("كم كان التضخم؟", Operation.VALUE),
        # list
        ("List the indicators in Tourism", Operation.LIST),
        ("Which indicators are published?", Operation.LIST),
        ("اذكر المؤشرات", Operation.LIST),
        ("ما هي المؤشرات المنشوره؟", Operation.LIST),
        # spread
        ("What is the gap between them?", Operation.SPREAD),
        ("The spread across benchmarks", Operation.SPREAD),
        ("الفجوه بين الدول المقارنه", Operation.SPREAD),
        ("الفرق بين القيمتين", Operation.SPREAD),
    ],
)
def test_the_operation_is_read_from_the_words_the_reader_used(
    asked: str, expected: Operation
) -> None:
    """Nine operations, both languages, from the phrase tables and nothing else."""
    assert operation_of(asked) is expected


def test_an_operation_the_reader_named_is_recorded_as_named_in_question() -> None:
    """FR-14 and AD-19: the rung and the authority, and they are different axes. The
    reader's own words chose it, so the precedence is named-in-question and the authority
    is the reader -- never the rule that used to supply every operation in the system."""
    account = compiled("What does inflation mean?")
    binding = account.by_field[SpecField.OPERATION]
    assert binding.precedence is Precedence.NAMED_IN_QUESTION
    assert binding.bound_by is BoundBy.READER


def test_no_operation_is_ever_bound_by_a_model() -> None:
    """AD-22 leaves the seam and this story implements nothing behind it. NFR-1 is why:
    ``tests/corpus_runner.py`` compiles every entry twice and fails on any difference,
    and a model in the binder is the one thing that could make a question compile twice."""
    for asked in ("What does inflation mean?", "Compare inflation and GDP", "اعلي قيمه"):
        assert compiled(asked).by_field[SpecField.OPERATION].bound_by is not BoundBy.MODEL


def test_compiling_an_operation_question_is_deterministic() -> None:
    """The gate NFR-1 makes of it, asserted here as well as in the corpus runner."""
    for asked in ("What does inflation mean?", "ما هو التضخم؟", "The gap between them"):
        assert compiled(asked) == compiled(asked)


# ------------------------------------------------- "what is X" -- the hard one, both ways


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("What is inflation?", Operation.DEFINITION),
        ("What is inflation now?", Operation.VALUE),
        ("What is inflation today?", Operation.VALUE),
        ("What is inflation in 2025?", Operation.VALUE),
        ("What is inflation in April 2026?", Operation.VALUE),
        ("What is the latest inflation?", Operation.VALUE),
        ("What is monthly inflation?", Operation.VALUE),
        ("What was inflation?", Operation.VALUE),
        ("ما هو التضخم؟", Operation.DEFINITION),
        ("ما هو التضخم الان؟", Operation.VALUE),
        ("ما هو التضخم حاليا؟", Operation.VALUE),
        ("ما هو التضخم في 2025؟", Operation.VALUE),
        ("ما هي البطاله؟", Operation.DEFINITION),
        ("ما هي البطاله في الوقت الحالي؟", Operation.VALUE),
    ],
)
def test_a_period_word_is_the_whole_difference_between_a_definition_and_a_value(
    asked: str, expected: Operation
) -> None:
    """*"What is inflation"* asks what the word means; *"What is inflation now"* asks for
    a number. The frame is identical and the period is the entire difference -- which is
    why the frame rung is told what the period binder bound rather than reading the
    period words a second time."""
    assert operation_of(asked) is expected


def test_the_bare_subject_frame_is_read_off_the_period_binding_not_a_second_parser() -> None:
    """A grain and a relative expression are period expressions the frame must respect,
    and they are respected because the *binding* is consulted -- the one parser, in
    ``compile.periods``, that read them in the first place."""
    for asked in (
        "What is inflation over the last five years?",
        "What is quarterly inflation?",
        "What is inflation since 2019?",
    ):
        assert compiled(asked).by_field[SpecField.PERIOD].precedence is (
            Precedence.NAMED_IN_QUESTION
        )
        assert operation_of(asked) is Operation.VALUE


def test_a_period_inherited_from_an_earlier_turn_does_not_make_it_a_value() -> None:
    """A follow-up asking what the subject *is* has changed the question rather than
    narrowed it; answering it with the earlier turn's figure would answer the old one."""
    account = compiled("What is inflation?", history=("What was inflation in 2025?",))
    assert account.spec.operation == Bound(Operation.DEFINITION)
    assert account.by_field[SpecField.PERIOD].precedence is Precedence.INHERITED_FROM_HISTORY


# -------------------------------------------------------- what must not have changed


def test_a_question_naming_no_operation_still_binds_the_rule_default() -> None:
    """``value`` is deployed and answering. The rung it comes off is unchanged, and so is
    the record that says which rung that was."""
    account = compiled("What was inflation in April 2026?")
    assert account.spec.operation == Bound(Operation.VALUE)
    binding = account.by_field[SpecField.OPERATION]
    assert binding.precedence is Precedence.RULE_DEFAULT
    assert binding.bound_by is BoundBy.RULE


def test_a_multi_reading_request_is_not_by_itself_a_series() -> None:
    """``R-OP-SERIES-FROM-A-MULTI-READING-REQUEST`` is off, and this is what off means:
    a question asking for five readings still answers with the newest of them rather than
    refusing, because ``execute/`` produces no series to answer it with."""
    assert multi_reading_is_a_series() is False
    assert operation_of("Inflation over the last five years") is Operation.VALUE
    assert operation_of("Inflation from 2019 to 2025") is Operation.VALUE


@pytest.mark.parametrize(
    "asked",
    [
        f"What was {GROWTH_NAMED_DETAIL} in 2025?",
        f"What was the {RANK_NAMED_DETAIL} in 2025?",
    ],
)
def test_an_operation_word_inside_the_indicators_own_name_does_not_count(
    asked: str, names: SnapshotCatalogue
) -> None:
    """An indicator called *Global Merchandise Trade Growth* is not a question about
    change, and one called *MSCI Rank* is not a question about a ranking -- by the same
    mechanism the measure binder already uses: the span the detail bound from is excluded
    before the operation words are read. Both names are in the real export."""
    account = compiled(asked, catalogue=names)
    assert isinstance(account.spec.detail, Bound), f"{asked!r} bound no detail"
    assert account.spec.operation == Bound(Operation.VALUE)
    assert account.by_field[SpecField.OPERATION].precedence is Precedence.RULE_DEFAULT


def test_an_operation_is_inherited_from_an_earlier_turn_when_this_one_names_none() -> None:
    account = compiled("And in 2024?", history=("What does inflation mean?",))
    assert account.spec.operation == Bound(Operation.DEFINITION)
    assert account.by_field[SpecField.OPERATION].precedence is (
        Precedence.INHERITED_FROM_HISTORY
    )


# ======================================================= the dispatch exists at all


def test_something_now_branches_on_the_operation() -> None:
    """The defect this story closes, asserted as the scan that would have caught it.

    Before ``narrate.dispatch``, ``Operation`` was a closed set of eleven that nothing
    read: the composers of Epics 3, 4 and 5 were complete, tested and unreachable. This
    fails the day the branch is deleted, which is how it went missing the first time.
    """
    branching = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for package in DISPATCHING_PACKAGES
        for path in sorted((PACKAGE_ROOT / package).rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == Operation.__name__
    ]
    assert branching, (
        "nothing in narrate/ names an Operation member, so every question reaches the "
        "value composer whatever its verb -- which is the defect this story closed"
    )


@pytest.mark.parametrize(
    "operation", [member for member in Operation if member is not Operation.VALUE]
)
def test_every_operation_other_than_value_reaches_a_typed_outcome(
    operation: Operation, catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """No fall-through. A declared operation with no implementation is *stated* -- which
    is AD-2's declared-but-unwired defect closed at the routing rather than at the reader.
    """
    routed = compose_operation(
        Request(
            operation=operation,
            lang=Lang.EN,
            catalogue=catalogue,
            rule_set=rule_set,
            detail_id=INFLATION_DETAIL,
            detail_name=INFLATION,
        )
    )
    assert isinstance(routed, Composed | NotHeld | Unwired)


def test_value_is_never_routed(catalogue: Catalogue, rule_set: RuleSet) -> None:
    """The deployed path is the caller's own, and routing it would compose it twice."""
    with pytest.raises(ValueError, match="value"):
        compose_operation(
            Request(
                operation=Operation.VALUE,
                lang=Lang.EN,
                catalogue=catalogue,
                rule_set=rule_set,
                detail_id=INFLATION_DETAIL,
                detail_name=INFLATION,
            )
        )


def test_an_unwired_operation_says_what_it_needs(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """The reason is operator-facing and names the composer and the missing execution, so
    the gap is a thing a maintainer can read rather than one they have to infer."""
    routed = compose_operation(
        Request(
            operation=Operation.SERIES,
            lang=Lang.EN,
            catalogue=catalogue,
            rule_set=rule_set,
            detail_id=INFLATION_DETAIL,
            detail_name=INFLATION,
        )
    )
    assert isinstance(routed, Unwired)
    assert routed.operation is Operation.SERIES
    assert "execute" in routed.because


def test_a_definition_for_a_detail_the_catalogue_does_not_hold_is_not_an_absence(
    catalogue: Catalogue, rule_set: RuleSet, groups: ReadModelGroups
) -> None:
    """*"No such detail"* and *"no definition published"* are different answers (AD-15),
    and the port keeps them apart one layer earlier."""
    routed = compose_operation(
        Request(
            operation=Operation.DEFINITION,
            lang=Lang.EN,
            catalogue=catalogue,
            rule_set=rule_set,
            detail_id="D-NOT-A-DETAIL",
            detail_name="D-NOT-A-DETAIL",
            groups=groups,
        )
    )
    assert isinstance(routed, NotHeld)


def test_a_process_with_no_catalogue_port_refuses_rather_than_answering_emptily(
    catalogue: Catalogue, rule_set: RuleSet
) -> None:
    """``GroupsPort`` is not on ``Engine`` today. That is a wiring gap and it is stated as
    one -- never as "no definition is published", which would be false of the export."""
    routed = compose_operation(
        Request(
            operation=Operation.DEFINITION,
            lang=Lang.EN,
            catalogue=catalogue,
            rule_set=rule_set,
            detail_id=INFLATION_DETAIL,
            detail_name=INFLATION,
            groups=None,
        )
    )
    assert isinstance(routed, Unwired)
    assert "GroupsPort" in routed.because


# ===================================================== definition, end to end, both ways


@pytest.mark.parametrize(
    ("asked", "lang", "opening"),
    [
        (
            "What does Inflation mean?",
            Lang.EN,
            "Inflation: The increase in the general level of prices of goods and services",
        ),
        ("ماذا يعني التضخم؟", Lang.AR, "التضخم: "),
    ],
)
def test_a_definition_question_returns_the_published_definition(
    asked: str,
    lang: Lang,
    opening: str,
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """FR-33, from the question to the element: quoted from the published definition,
    attributed, never generated -- and the same question in Arabic answers from the
    Arabic column rather than from a translation of the English one (FR-60)."""
    package = answered(
        asked,
        lang,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=groups,
    )
    assert package.kind is PackageKind.ANSWER
    assert package.spec.operation == Bound(Operation.DEFINITION)
    assert len(package.elements) == 1
    placed = package.elements[0]
    assert placed.role is Role.EVIDENCE
    assert placed.element.element_class is ElementClass.MEASURED
    assert placed.element.content.startswith(opening)
    assert placed.element.source_ref == f"catalogue:detail:{INFLATION_DETAIL}"
    assert ReadModelCatalogueSources(read_model).resolves(placed.element.source_ref)
    assert package.degradations == ()


def test_the_two_languages_quote_different_text_from_the_same_detail(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """Absence in one language is stated and never filled from the other (FR-60); the
    positive case of the same rule is that the two answers are genuinely two columns."""
    kwargs = {
        "names": names,
        "read_model": read_model,
        "catalogue": catalogue,
        "formatter": formatter,
        "placement": placement,
        "sources": sources,
        "groups": groups,
    }
    english = answered("What does Inflation mean?", Lang.EN, **kwargs)  # type: ignore[arg-type]
    arabic = answered("ماذا يعني التضخم؟", Lang.AR, **kwargs)  # type: ignore[arg-type]
    assert english.elements[0].element.content != arabic.elements[0].element.content
    assert english.elements[0].element.source_ref == arabic.elements[0].element.source_ref


def test_a_definition_answer_records_the_rule_that_decided_it(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """A third of the catalogue publishes ``-`` as its definition, and the rule that
    refuses to quote one fired on this answer whichever way it went (AD-16)."""
    package = answered(
        "What does Inflation mean?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=groups,
    )
    assert "R-META-PLACEHOLDER-IS-NOT-A-DEFINITION" in package.rules_fired


def test_a_definition_question_with_no_catalogue_port_is_refused_not_answered_with_a_figure(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
) -> None:
    """The deployed defect, restated as its floor: a question about what an indicator
    *means* never comes back as that indicator's latest figure, even in a process that
    cannot answer it."""
    package = answered(
        "What does Inflation mean?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=None,
    )
    assert package.kind is PackageKind.REFUSAL
    assert package.elements == ()
    assert package.reason


def test_an_unwired_operation_refuses_rather_than_answering_the_wrong_question(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """*"Show me the trend"* used to return one figure. It now says the published data
    cannot answer it as asked, which is true, and which is the answer a reader can act on.
    """
    package = answered(
        f"Show me the trend for {INFLATION}",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=groups,
    )
    assert package.spec.operation == Bound(Operation.SERIES)
    assert package.kind is PackageKind.REFUSAL
    assert package.reason
    assert package.elements == ()


def test_the_value_path_is_untouched(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """The deployed answer, through the same entry point, with the dispatcher in front of
    it. It still returns the figure with its unit, its period and a resolving source_ref.
    """
    package = answered(
        f"What is {INFLATION} now?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=groups,
    )
    assert package.spec.operation == Bound(Operation.VALUE)
    assert package.kind is PackageKind.ANSWER
    assert package.row_ids
    assert any(
        placed.element.content.startswith(INFLATION) for placed in package.elements
    )


def test_an_unanswerable_question_is_still_a_clarification_whatever_its_operation(
    names: SnapshotCatalogue,
    read_model: sqlite3.Connection,
    catalogue: Catalogue,
    formatter: Formatter,
    placement: Placement,
    sources: EitherSource,
    groups: ReadModelGroups,
) -> None:
    """257 of 320 published names are shared, so *"which of these did you mean"* is the
    commonest thing the engine says. A question that bound no detail is the reader's to
    finish, and the operation only decides which composer answers a finished one."""
    package = answered(
        "What is the price of tea?",
        Lang.EN,
        names=names,
        read_model=read_model,
        catalogue=catalogue,
        formatter=formatter,
        placement=placement,
        sources=sources,
        groups=groups,
    )
    assert package.kind is not PackageKind.ANSWER
    assert package.reason
