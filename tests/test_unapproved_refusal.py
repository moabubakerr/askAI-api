"""Story 2.8 -- the unapproved catalogue improves a refusal and never leaks into one.

FR-38a and AD-12. 342 of the CMS's 531 indicators were never approved and 281 of those
carry a real name, so a reader asking about one has asked a **sensible question about a
real indicator**. Telling them *"I do not hold an indicator matching that"* sends them
off to rephrase something no rephrasing will answer; telling them it exists and is not
approved for publication ends the retrying, which is the whole of the story.

Everything else here exists to stop that better answer from becoming a leak:

* **the crossing is one boolean, structurally.** ``Answer`` holds a
  ``str -> bool | None`` callable, not the port, so there is no type reachable from an
  answer on which an unapproved value, period, definition or *name* could arrive. That is
  asserted by walking every type reachable from ``Answer`` and ``AnswerPackage`` rather
  than by inspecting one composed refusal, and the walk is checked against a planted
  crossing so a scan that has never gone red is distinguishable from one that cannot;
* **the wording states a position and promises nothing.** Both languages are scanned for
  the words that would turn *"was not approved"* into *"has not been approved yet"* --
  an analyst told the figure is coming waits for it, which is the retrying this story
  ends, one turn later;
* **an unreadable catalogue degrades and does not guess.** It falls back to the plain
  refusal it would have given anyway and records a typed ``Degradation`` beside it, so
  the substitution is visible to an operator instead of invisible to everyone (AD-15).

The catalogue under test is the **real export**, for the reason ``test_refusals.py``
gives: these are claims about what a reader is told about real unapproved indicators, and
a fixture would make them true of the fixture.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final, TypeAliasType, get_args, get_type_hints

import pytest

from askai.adapters.readmodel.export import CmsExport
from askai.adapters.readmodel.unpublished import (
    MINIMUM_WORDS_RULE,
    UnpublishedCatalog,
    existence_probe,
)
from askai.compile.binder import CompileInput, compile_question
from askai.compile.catalogue import SnapshotCatalogue
from askai.domain.normalise import normalise
from askai.domain.period import Period
from askai.execute.value import execute_value
from askai.messages import Catalogue, Lang, Plain, load_catalogue
from askai.narrate.package import AnswerPackage, PackageKind
from askai.narrate.refusal import RefusalCode, refusal_message_id
from askai.narrate.structured import Answer, structured_package
from askai.narrate.unapproved import (
    UPGRADES_FROM,
    CatalogueProbe,
    UnapprovedRule,
    improved_refusal,
)
from askai.observability.degradations import DegradationKind
from askai.ports.datapoints import DatapointRow
from askai.ports.unpublished_catalogue import UnpublishedCatalogPort, UnpublishedName
from askai.rules import RuleSet, rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EXPORT_ROOT: Final = PROJECT_ROOT / "data"
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"

TODAY: Final = date(2026, 9, 17)

#: Unapproved in the real export, in both languages -- corpus entry e2-005. A reader
#: writes the question, not the catalogue's spelling, which is why the probe recognises
#: the whole name inside a longer sentence rather than by equality.
VOLUNTEER_EN: Final = "What is the rate of volunteer work in Qatar?"
VOLUNTEER_AR: Final = "ما هو معدل العمل التطوعي في قطر؟"
VOLUNTEER_NAME: Final = "The Rate of Volunteer Work"

#: Named in no catalogue at all, approved or otherwise -- the refusal that must stay
#: *"no such indicator"* however loudly the unapproved layer is consulted.
NOTHING_LIKE_IT: Final = "What is the gross national happiness index?"

#: The modules whose types may never be reachable from an answer.
UNPUBLISHED_MODULES: Final = frozenset(
    {"askai.ports.unpublished_catalogue", "askai.adapters.readmodel.unpublished"}
)

#: The layers an answer is built in. None of them may import the two modules above --
#: including ``narrate/unapproved.py``, which is the module that consults the catalogue.
ANSWER_PATH_PACKAGES: Final = (
    "compile",
    "validate",
    "execute",
    "assemble",
    "narrate",
    "respond",
    "api",
)

#: Words that turn a statement of the position into a promise about the future. FR-38a's
#: *"does not imply the data can be obtained"* is only checkable as its negation, so the
#: negation is written out, per language, and scanned for.
PROMISES_EN: Final = (
    "yet",
    "soon",
    "pending",
    "in future",
    "will be published",
    "once approved",
    "request",
    "contact",
    "apply for",
    "await",
)
PROMISES_AR: Final = (
    "بعد",
    "قريبا",
    "قريباً",
    "لاحقا",
    "لاحقاً",
    "سيتم",
    "سوف",
    "قيد",
    "اطلب",
    "تواصل",
)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def messages() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


@pytest.fixture(scope="module")
def unapproved() -> UnpublishedCatalog:
    return UnpublishedCatalog.from_export(CmsExport.rooted(EXPORT_ROOT))


@pytest.fixture(scope="module")
def probe(unapproved: UnpublishedCatalog) -> CatalogueProbe:
    return existence_probe(unapproved)


# ---------------------------------------------------------------------------- helpers


class NoDatapoints:
    """A ``DatapointsPort`` over nothing.

    Every question here fails to bind a detail, so the fetch never reaches a row; the
    port exists to keep the test honest about which layer produced the refusal.
    """

    def publishes(self, detail_id: str) -> bool:
        return False

    def periods(self, detail_id: str, country_id: str | None) -> tuple[Period, ...]:
        return ()

    def row(
        self, detail_id: str, period: Period, country_id: str | None
    ) -> DatapointRow | None:
        return None


class NothingResolves:
    """A ``SourceCatalogue`` that resolves no reference; no refusal composes an element."""

    def resolves(self, source_ref: str) -> bool:
        return False


class Exploding:
    """An ``UnpublishedCatalogPort`` whose store is not there.

    Not a typed failure and not an ``OSError`` -- a driver would raise its own class, and
    the point of converting at the adapter boundary is that a composer never has to know
    which one.
    """

    def holds(self, name: str) -> bool:
        raise RuntimeError("the base layer is unreachable")

    def names(self) -> Sequence[UnpublishedName]:
        raise RuntimeError("the base layer is unreachable")


def refusal(
    asked: str,
    lang: Lang,
    messages: Catalogue,
    probe: CatalogueProbe | None,
    *,
    named_indicator: str | None = None,
) -> AnswerPackage:
    """One question, compiled, executed and composed, with *probe* as its only extra."""
    question = compile_question(
        CompileInput(question=asked, today=TODAY, history=()), SnapshotCatalogue()
    )
    return structured_package(
        Answer(
            question=question,
            execution=execute_value(question, NoDatapoints()),
            lang=lang,
            unapproved=probe,
            named_indicator=named_indicator,
        ),
        messages,
        formatter_is_unused(),
        placement_is_unused(),
        NothingResolves(),
    )


def formatter_is_unused() -> Any:
    """A refusal formats no figure; handing one a real formatter would imply it might."""
    return None


def placement_is_unused() -> Any:
    """Likewise: nothing here takes a role, because nothing here is an element."""
    return None


def wording(messages: Catalogue, lang: Lang, message_id: str) -> str:
    entry = messages.entry(lang, message_id)
    assert isinstance(entry, Plain), f"{message_id} is counted; a refusal is not"
    return entry.text


def _python_files(root: Path) -> Iterator[Path]:
    yield from (
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts and path.is_file()
    )


def _imported_modules(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return frozenset(found)


def _unfold(annotation: object) -> Iterator[object]:
    """Every type mentioned by *annotation*, including inside aliases and callables."""
    yield annotation
    if isinstance(annotation, TypeAliasType):
        yield from _unfold(annotation.__value__)
        return
    for argument in get_args(annotation):
        if isinstance(argument, list):  # Callable's parameter list
            for parameter in argument:
                yield from _unfold(parameter)
        else:
            yield from _unfold(argument)


def reachable_types(*roots: type) -> set[type]:
    """Every type reachable from *roots* by following dataclass fields.

    The structural form of *"no type crosses from ``UnpublishedCatalogPort`` into
    ``Answer``"*: it does not inspect a composed answer -- one composed answer proves one
    composed answer -- it asks what an answer is **able** to carry.
    """
    seen: set[type] = set()
    pending: list[type] = list(roots)
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if not dataclasses.is_dataclass(current):
            continue
        for annotation in get_type_hints(current).values():
            for mentioned in _unfold(annotation):
                if isinstance(mentioned, type) and mentioned not in seen:
                    pending.append(mentioned)
    return seen


def crossings(*roots: type) -> list[str]:
    return sorted(
        f"{found.__module__}.{found.__qualname__}"
        for found in reachable_types(*roots)
        if getattr(found, "__module__", "") in UNPUBLISHED_MODULES
    )


# ============================================== the crossing, asserted structurally


def test_no_type_from_the_unpublished_port_is_reachable_from_an_answer() -> None:
    """R-UNAPPROVED-LEAKS-NOTHING, as a property of the types rather than of a run.

    Walked from both ends of composition: ``Answer`` is what a composer is handed and
    ``AnswerPackage`` is what it returns, so a type crossing in either direction is a
    type one of these two can reach.
    """
    assert crossings(Answer, AnswerPackage) == []


def test_the_reachability_walk_would_catch_a_planted_crossing() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""

    @dataclasses.dataclass(frozen=True)
    class Leaky:
        answer: Answer
        leaked: UnpublishedName | None = None

    assert crossings(Leaky) == ["askai.ports.unpublished_catalogue.UnpublishedName"]


def test_the_walk_actually_reaches_the_answer_s_own_types() -> None:
    """Non-vacuous: a walk that found nothing would pass the assertion above for free."""
    found = {f"{kind.__module__}.{kind.__qualname__}" for kind in reachable_types(Answer)}
    assert "askai.compile.binding.CompiledQuestion" in found
    assert "askai.execute.value.Execution" in found
    assert len(found) > 20


def test_the_crossing_is_one_boolean_question() -> None:
    """The probe's whole vocabulary is ``str`` in, ``bool | None`` out."""
    parameters, result = get_args(CatalogueProbe.__value__)
    assert parameters == [str]
    assert set(get_args(result)) == {bool, type(None)}


def test_no_layer_on_the_answer_path_imports_the_unapproved_catalogue() -> None:
    """Including ``narrate/unapproved.py``, the module that consults it."""
    offenders = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()} imports {name}"
        for package in ANSWER_PATH_PACKAGES
        for path in _python_files(PACKAGE_ROOT / package)
        for name in sorted(_imported_modules(path) & UNPUBLISHED_MODULES)
    ]
    assert offenders == []


# ================================================= the improvement, on the real export


def test_an_unapproved_indicator_is_refused_as_editorial_not_as_absent(
    messages: Catalogue, probe: CatalogueProbe
) -> None:
    """R-UNAPPROVED-IS-A-DISTINCT-REFUSAL, in both languages, end to end."""
    for asked, lang in ((VOLUNTEER_EN, Lang.EN), (VOLUNTEER_AR, Lang.AR)):
        package = refusal(asked, lang, messages, probe)
        assert package.kind is PackageKind.REFUSAL
        assert package.refusal_code is RefusalCode.NOT_APPROVED_FOR_PUBLICATION
        assert package.reason_id == refusal_message_id(
            RefusalCode.NOT_APPROVED_FOR_PUBLICATION
        )
        assert package.degradations == ()


def test_without_the_catalogue_the_same_question_is_the_weaker_refusal(
    messages: Catalogue,
) -> None:
    """The improvement is the catalogue's doing, not the question's.

    A deployment wired without the base layer answers exactly as it did before, and does
    **not** record a degradation: an engine that was never given the catalogue has not
    lost it, and counting that as a fault would report an outage on every refusal.
    """
    package = refusal(VOLUNTEER_EN, Lang.EN, messages, None)
    assert package.refusal_code is RefusalCode.NO_SUCH_INDICATOR
    assert package.degradations == ()


def test_a_question_naming_nothing_at_all_is_still_no_such_indicator(
    messages: Catalogue, probe: CatalogueProbe
) -> None:
    """The catalogue improves a refusal; it does not manufacture one."""
    package = refusal(NOTHING_LIKE_IT, Lang.EN, messages, probe)
    assert package.refusal_code is RefusalCode.NO_SUCH_INDICATOR
    assert package.degradations == ()


def test_the_refusal_surfaces_nothing_from_the_unapproved_row(
    messages: Catalogue, probe: CatalogueProbe, unapproved: UnpublishedCatalog
) -> None:
    """R-UNAPPROVED-LEAKS-NOTHING at the one place a reader could see it.

    The sentence takes no parameters at all, so there is no slot for a value, a period or
    a definition -- and the name that matched is not in the rendered text either, in
    either language.
    """
    message_id = refusal_message_id(RefusalCode.NOT_APPROVED_FOR_PUBLICATION)
    assert messages.parameters(message_id) == frozenset()
    for asked, lang in ((VOLUNTEER_EN, Lang.EN), (VOLUNTEER_AR, Lang.AR)):
        said = normalise(refusal(asked, lang, messages, probe).reason or "")
        for entry in unapproved.names():
            for spelling in (entry.name_en, entry.name_ar):
                folded = normalise(spelling)
                if len(folded.split()) >= 2:
                    assert folded not in said, spelling


def test_neither_language_implies_the_figure_can_be_obtained(messages: Catalogue) -> None:
    """R-UNAPPROVED-IS-A-DISTINCT-REFUSAL's second half, scanned rather than reviewed.

    *"Not yet approved"* and *"pending publication"* are wrong in the same way as *"I do
    not hold that"*: the analyst waits instead of stopping. The wording may only state
    the position.
    """
    message_id = refusal_message_id(RefusalCode.NOT_APPROVED_FOR_PUBLICATION)
    english = f" {wording(messages, Lang.EN, message_id).casefold()} "
    for promise in PROMISES_EN:
        assert f" {promise} " not in english, promise
    arabic = wording(messages, Lang.AR, message_id)
    for promise in PROMISES_AR:
        assert promise not in arabic, promise


def test_the_improved_refusal_reads_differently_from_the_one_it_replaces(
    messages: Catalogue,
) -> None:
    """Six means six: the improvement is worth making only if it says something else."""
    for lang in Lang:
        editorial = wording(
            messages, lang, refusal_message_id(RefusalCode.NOT_APPROVED_FOR_PUBLICATION)
        )
        absent = wording(messages, lang, refusal_message_id(RefusalCode.NO_SUCH_INDICATOR))
        assert editorial != absent


# ============================================================== only the one cause


@pytest.mark.parametrize("code", list(RefusalCode))
def test_only_no_such_indicator_is_ever_improved(code: RefusalCode) -> None:
    """Upgrading an outage into an editorial gap is the AD-15 defect, better dressed."""
    verdict = improved_refusal(code, "anything at all", lambda _: True)
    if code is UPGRADES_FROM:
        assert verdict.code is RefusalCode.NOT_APPROVED_FOR_PUBLICATION
    else:
        assert verdict.code is code
    assert verdict.degradations == ()


def test_nothing_named_is_not_asked_about() -> None:
    def never_called(named: str) -> bool | None:  # pragma: no cover -- it is not called
        raise AssertionError(f"the catalogue was asked about {named!r}")

    assert improved_refusal(UPGRADES_FROM, "   ", never_called).code is UPGRADES_FROM


# ================================================ unreachable: degrade, never guess


def test_an_unreachable_catalogue_falls_back_and_records_why(messages: Catalogue) -> None:
    """R-UNAPPROVED-UNREACHABLE-DEGRADES, through the adapter's own guard.

    The port raises a class no pure layer has heard of. The answer is still composed, it
    is the refusal it would have been anyway, and the substitution is on the record.
    """
    package = refusal(VOLUNTEER_EN, Lang.EN, messages, existence_probe(Exploding()))
    assert package.kind is PackageKind.REFUSAL
    assert package.refusal_code is RefusalCode.NO_SUCH_INDICATOR
    assert [found.kind for found in package.degradations] == [
        DegradationKind.ADAPTER_UNAVAILABLE.value
    ]
    assert package.degradations[0].where == "narrate.unapproved"


def test_the_guard_converts_any_failure_into_the_third_state() -> None:
    """``None`` is produced at the adapter boundary, which is where AD-15 allows it."""
    assert existence_probe(Exploding())("anything") is None


def test_the_unreachable_fallback_is_never_a_leak(messages: Catalogue) -> None:
    """A fault may not be worded as an editorial gap, and may not be worded as a name."""
    package = refusal(VOLUNTEER_EN, Lang.EN, messages, existence_probe(Exploding()))
    assert normalise(VOLUNTEER_NAME) not in normalise(package.reason or "")


# ======================================================================= determinism


def test_the_same_question_refuses_identically_on_every_run(
    messages: Catalogue, probe: CatalogueProbe
) -> None:
    first = refusal(VOLUNTEER_EN, Lang.EN, messages, probe)
    second = refusal(VOLUNTEER_EN, Lang.EN, messages, probe)
    assert (first.refusal_code, first.reason_id, first.reason) == (
        second.refusal_code,
        second.reason_id,
        second.reason,
    )


def test_the_verdict_does_not_depend_on_the_order_the_catalogue_is_held_in(
    unapproved: UnpublishedCatalog,
) -> None:
    """Existence is a question about the set, so no tie is broken and none can be."""
    reversed_catalog = UnpublishedCatalog(
        entries=tuple(reversed(unapproved.entries)), by_name=unapproved.by_name
    )
    assert existence_probe(reversed_catalog)(VOLUNTEER_EN) is True


# ============================================ recognising a name inside a question


def test_a_name_is_recognised_inside_a_question_and_only_in_full(
    probe: CatalogueProbe, unapproved: UnpublishedCatalog
) -> None:
    assert probe(VOLUNTEER_EN) is True
    assert probe(VOLUNTEER_NAME) is True
    assert probe("volunteer") is False
    assert probe(NOTHING_LIKE_IT) is False


def test_the_arabic_spelling_reaches_the_same_entry(probe: CatalogueProbe) -> None:
    """One fold, or none at all: the reader's Arabic meets the stored Arabic."""
    assert probe(VOLUNTEER_AR) is True


def test_the_recognition_floor_is_a_rule_and_not_a_literal(rule_set: RuleSet) -> None:
    """R-UNAPPROVED-NAME-IS-RECOGNISED-IN-FULL carries the threshold as data."""
    assert rule_set.value(MINIMUM_WORDS_RULE, "minimum_words") == 2
    single = UnpublishedCatalog(
        entries=(UnpublishedName(name_en="Population", name_ar="السكان"),),
        by_name={},
    )
    probe = existence_probe(single)
    assert probe("what is the population of the country") is False
    assert probe("Population") is False, "equality goes through holds(), and by_name is empty"


def test_a_port_satisfying_the_protocol_is_what_the_probe_takes(
    unapproved: UnpublishedCatalog,
) -> None:
    port: UnpublishedCatalogPort = unapproved
    assert existence_probe(port)(VOLUNTEER_EN) is True


# ================================================================= rules and evidence


def test_this_story_s_rules_are_in_the_catalogue(rule_set: RuleSet) -> None:
    """Every rule the module names exists, is agreed, and is fireable."""
    for rule_id in (
        UnapprovedRule.IS_A_DISTINCT_REFUSAL,
        UnapprovedRule.LEAKS_NOTHING,
        UnapprovedRule.UNREACHABLE_DEGRADES,
        MINIMUM_WORDS_RULE,
    ):
        entry = rule_set.get(rule_id)
        assert entry.rule.is_fireable
        assert entry.rule.status.value == "agreed"
