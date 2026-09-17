"""The knowledge base is exactly what was admitted, and a refusal is never outsourced.

Stories 9.2 and 9.4. Five properties, and they are the five the acceptance criteria rest
on:

1. **The admission set is data, and the code reads it.** The set is built from
   ``src/askai/rules/data/knowledge-base.yaml`` through the same loader the service starts
   with, and a malformed table refuses to return a partial knowledge base.
2. **The read model is checked against the set, not the other way round.** Every table the
   read model creates must be named by an admitted source. A table added by a later story
   fails this gate until someone admits it deliberately, which is the only version of the
   check that is worth having -- deriving the set from the tables would admit everything
   that exists.
3. **Exported is not publishable.** The article predicate is applied to the *real*
   ``data/Articles.csv``: 84 rows exported, 67 admitted. The number is asserted against the
   file rather than against a fixture, because a fixture would agree with the predicate by
   construction and the whole claim is about rows nobody wrote for a test.
4. **Nothing leaves the box at answer time.** An inventory over the answer-path packages,
   in the idiom ``tests/test_api.py`` established: a network library import is a way out of
   the process, no answer-path module holds one, and in the tree as a whole one may live
   only under a path the rule file admits as reaching a runtime inside the estate.
5. **A gap is stated, and the quiet alternative is counted.** The six refusal causes are
   enumerated and closed, every ``RefusalCause`` member is bound to one of them, and
   ``observability/outsourcing.py`` classifies "the approved path refused while the external
   path answered" as a value computed from what was answered -- never a module-level total.
"""

from __future__ import annotations

import ast
import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.readmodel.schema import READ_MODEL
from askai.compile.resolve import RefusalCause
from askai.observability.outsourcing import (
    AnswerStance,
    FinishedResponse,
    OutsourcedShare,
    Outsourcing,
    outsourcing_of,
)
from askai.rules import RuleLoadError, load_rules
from askai.rules.knowledge_base import (
    ADMITTED_SOURCES_RULE,
    ARTICLE_ADMISSION_RULE,
    OUTBOUND_INVENTORY_RULE,
    REFUSAL_CAUSES_RULE,
    KnowledgeBase,
    KnowledgeBaseError,
    knowledge_base,
    load_knowledge_base,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
PACKAGE_ROOT: Final = PROJECT_ROOT / "src" / "askai"
OUTSOURCING_MODULE: Final = PACKAGE_ROOT / "observability" / "outsourcing.py"
ARTICLES: Final = PROJECT_ROOT / "data" / "Articles.csv"

#: The admission set of FR-77, spelled out here as well as in the rule file. Two
#: independent spellings on purpose: a test that read the set from the file it is checking
#: would pass for any set at all, which is precisely the failure mode of a closed world
#: nobody enumerated.
ADMITTED: Final = frozenset(
    {
        "indicator",
        "detail",
        "datapoint",
        "analysis",
        "article",
        "reference",
        "country",
        "group",
        "entity",
    }
)

#: The six causes of Story 2.7, as machine codes.
SIX_CAUSES: Final = frozenset(
    {
        "no-such-indicator",
        "not-approved-for-publication",
        "published-but-no-data",
        "not-for-this-period-grain-or-country",
        "question-unsupported",
        "could-not-reach-the-data",
    }
)


@pytest.fixture(scope="module")
def base() -> KnowledgeBase:
    """The packaged knowledge base, through the loader the service starts with."""
    return knowledge_base()


# ------------------------------------------------------- the admission set, as data


def test_the_admission_set_is_exactly_the_enumerated_sources(base: KnowledgeBase) -> None:
    """FR-77: published indicators, details and datapoints; analyst text attached to a
    datapoint; live published articles; and the reference, group, country and
    champion/entity tables. Nothing else is a permitted source."""
    assert base.keys == ADMITTED


def test_an_admitted_source_says_what_it_is_and_where_it_lives(base: KnowledgeBase) -> None:
    assert base.source("datapoint").table == "datapoint"
    assert base.source("reference").table == "ref_lookup"
    # Admitted and materialised. It carried no table until the read model grew one:
    # Story 1.6 named Epic 1's tables and Story 1.8 asked for the analyses, so the
    # ingest counted 1,031 and stored none. The admission was never the missing half.
    assert base.source("analysis").table == "analysis"
    # Admitted, with no table of its own. Recorded as an absence rather than omitted.
    assert base.source("article").table is None
    assert base.source("entity").table is None
    assert all(source.about for source in base.sources)


def test_a_source_nobody_admitted_is_not_a_source(base: KnowledgeBase) -> None:
    with pytest.raises(LookupError):
        base.source("open_web")
    assert not base.admits_table("indicator_forecast")


def test_every_read_model_table_is_an_admitted_source(base: KnowledgeBase) -> None:
    """The gate. Checked in this direction so a *new* table fails it.

    Deriving the admitted set from the read model would make this vacuous -- every table
    would be admitted because it exists. Written this way, a story that adds a table has to
    come back to ``knowledge-base.yaml`` and say what the table is, in front of a reviewer.
    """
    created = {table.name for table in READ_MODEL.tables}
    assert created, "a scan that finds nothing proves nothing"
    unadmitted = sorted(name for name in created if not base.admits_table(name))
    assert not unadmitted, (
        "the read model creates tables no admitted source names: "
        + ", ".join(unadmitted)
        + f" -- admit them in {ADMITTED_SOURCES_RULE} or do not create them"
    )


def test_the_admitted_tables_are_the_read_models_tables(base: KnowledgeBase) -> None:
    """The other half: nothing is admitted as a table that the read model does not create.

    Together with the test above this pins the set exactly, so neither side can drift --
    an admitted table that is never created is a source a reviewer believes exists.
    """
    assert base.tables == {table.name for table in READ_MODEL.tables}


# ---------------------------------------------------------- exported is not publishable


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


@pytest.fixture(scope="module")
def articles() -> list[dict[str, str]]:
    """The real export's articles. Read rather than fixtured: the claim is about rows."""
    assert ARTICLES.is_file(), f"{ARTICLES} is the evidence for FR-77a and must be present"
    with ARTICLES.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_the_article_predicate_admits_67_of_the_84_exported(
    base: KnowledgeBase, articles: list[dict[str, str]]
) -> None:
    """FR-77a, asserted against the export and not against the rule file's own number.

    The count *is* assertable here -- ``data/Articles.csv`` is the reviewed export, it
    carries all four flags, and the fixtures reach it -- so it is asserted rather than
    replaced by a comment explaining why it is not.
    """
    checked = (*base.articles.required_true, *base.articles.required_false)
    flags = [{name: _flag(row.get(name, "")) for name in checked} for row in articles]
    admitted = [row for row in flags if base.articles.admits(row)]
    assert len(articles) == 84
    assert len(admitted) == 67
    assert (base.articles.exported, base.articles.admitted) == (len(articles), len(admitted))


def test_publication_state_is_four_flags_and_not_one(
    base: KnowledgeBase, articles: list[dict[str, str]]
) -> None:
    """The 17 excluded rows are excluded for three different reasons, which is the point.

    ``Published`` alone would admit 71 -- four rows that are inactive or deleted. That gap
    of four is the whole of FR-77a's "exported is not publishable" in one number.
    """
    published_only = [row for row in articles if _flag(row.get("Published", ""))]
    assert len(published_only) == 71
    assert base.articles.required_true == ("Published", "IsActive")
    assert base.articles.required_false == ("IsDeleted", "IsDraft")


def test_a_row_missing_a_flag_is_not_admitted(base: KnowledgeBase) -> None:
    """A flag the export stopped carrying must not default to the permissive answer."""
    live = {"Published": True, "IsActive": True, "IsDeleted": False, "IsDraft": False}
    assert base.articles.admits(live)
    assert not base.articles.admits({"Published": True})
    without_draft = {name: value for name, value in live.items() if name != "IsDraft"}
    assert not base.articles.admits(without_draft)
    assert not base.articles.admits(
        {"Published": True, "IsActive": True, "IsDeleted": False, "IsDraft": True}
    )


def test_no_article_in_the_export_is_a_draft(articles: list[dict[str, str]]) -> None:
    """Said out loud because the predicate checks a flag that discriminates nothing today.

    Exactly like the confidential priority type, this half of FR-77a cannot be *evidenced*
    from this export -- zero rows exercise it. The flag is in the predicate anyway, and this
    test records why the check looks redundant, so nobody removes it as dead weight.
    """
    assert not [row for row in articles if _flag(row.get("IsDraft", ""))]


# ----------------------------------------------- nothing leaves the box at answer time


def _modules(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return [node.module] if node.module and node.level == 0 else []


def _network_imports(base: KnowledgeBase, root: Path) -> list[str]:
    return [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules(root)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported(node)
        if base.outbound.is_network_library(name)
    ]


@pytest.mark.parametrize("package", tuple(knowledge_base().outbound.answer_path_packages))
def test_no_answer_path_package_can_leave_the_process(base: KnowledgeBase, package: str) -> None:
    """FR-79 and AD-9a as an inventory rather than as a promise.

    The engine reaches no open web and no external data service at answer time, and makes
    no synchronous call to indicator-svc either -- and it cannot, because no module on the
    answer path imports anything that opens a socket. That is the structural form of the
    claim: there is no client to call indicator-svc *with*.
    """
    root = PACKAGE_ROOT / package
    if not root.is_dir():
        pytest.skip(f"{package}/ is not built yet")
    assert not _network_imports(base, root)


def test_the_only_outbound_calls_are_held_inside_the_estate(base: KnowledgeBase) -> None:
    """NFR-4a. The scan finds real imports, and every one of them is where it is admitted."""
    found = _network_imports(base, PACKAGE_ROOT)
    assert found, "a scan that finds no network import proves nothing"
    outside = [
        place for place in found if not base.outbound.inside_the_estate(place.split(":")[0])
    ]
    assert not outside, (
        "a call leaves the process from a module the estate inventory does not admit: "
        + ", ".join(outside)
        + f" -- see {OUTBOUND_INVENTORY_RULE}"
    )


def test_the_estate_holders_are_adapters(base: KnowledgeBase) -> None:
    """An outbound call lives behind a port adapter or it does not live at all (AD-2)."""
    assert all(holder.startswith("adapters/") for holder in base.outbound.estate_holders)


# ------------------------------------------ say what is missing, with a specific cause


def test_the_six_refusal_causes_are_enumerated_and_closed(base: KnowledgeBase) -> None:
    """FR-80: the approved answer refuses with a specific cause from the six of Story 2.7."""
    assert frozenset(base.refusal_codes) == SIX_CAUSES
    assert len(base.refusal_codes) == len(SIX_CAUSES)


def test_the_catalogue_gap_is_one_of_the_six(base: KnowledgeBase) -> None:
    """The 342 unapproved CMS indicators have a cause of their own, not a shrug.

    "This exists but is not approved for publication" is a different statement from "no
    such indicator", and collapsing the two is what makes a reader keep rephrasing a
    question no rephrasing will answer.
    """
    assert "not-approved-for-publication" in base.refusal_codes
    assert "no-such-indicator" in base.refusal_codes


def test_every_resolution_outcome_is_bound_to_one_cause(base: KnowledgeBase) -> None:
    """A fourth ``RefusalCause`` member fails this until a reviewer says which cause it is.

    The binding is the anti-drift device: a cause discovered in ``compile/`` and phrased
    again in a refusal module would be two statements nobody keeps in step.
    """
    assert base.discoverers == {cause.value for cause in RefusalCause}


# ------------------------------------------------- the counter-metric, as a value


@pytest.mark.parametrize(
    ("approved", "external", "expected"),
    [
        (AnswerStance.ANSWERED, AnswerStance.ANSWERED, Outsourcing.APPROVED_ANSWERED),
        (AnswerStance.ANSWERED, AnswerStance.REFUSED, Outsourcing.APPROVED_ANSWERED),
        (AnswerStance.ANSWERED, AnswerStance.ABSENT, Outsourcing.APPROVED_ANSWERED),
        (AnswerStance.REFUSED, AnswerStance.ANSWERED, Outsourcing.OUTSOURCED),
        (AnswerStance.REFUSED, AnswerStance.REFUSED, Outsourcing.BOTH_SILENT),
        (AnswerStance.REFUSED, AnswerStance.ABSENT, Outsourcing.BOTH_SILENT),
        (AnswerStance.ABSENT, AnswerStance.ANSWERED, Outsourcing.NOT_MEASURED),
        (AnswerStance.ABSENT, AnswerStance.REFUSED, Outsourcing.NOT_MEASURED),
        (AnswerStance.ABSENT, AnswerStance.ABSENT, Outsourcing.NOT_MEASURED),
    ],
)
def test_the_classification_is_total_over_both_stances(
    approved: AnswerStance, external: AnswerStance, expected: Outsourcing
) -> None:
    """All nine combinations, so the metric has no unclassified corner to fall into."""
    assert outsourcing_of(FinishedResponse(approved=approved, external=external)) is expected


def test_outsourced_is_exactly_refused_while_the_other_answered() -> None:
    """The one case the metric exists for, named rather than inferred from a boolean."""
    outsourced = [
        FinishedResponse(approved=approved, external=external)
        for approved in AnswerStance
        for external in AnswerStance
        if outsourcing_of(FinishedResponse(approved=approved, external=external))
        is Outsourcing.OUTSOURCED
    ]
    assert outsourced == [
        FinishedResponse(approved=AnswerStance.REFUSED, external=AnswerStance.ANSWERED)
    ]


def test_the_share_is_derived_from_verdicts_and_never_accumulated() -> None:
    verdicts = [
        Outsourcing.APPROVED_ANSWERED,
        Outsourcing.OUTSOURCED,
        Outsourcing.BOTH_SILENT,
        Outsourcing.OUTSOURCED,
        Outsourcing.NOT_MEASURED,
    ]
    share = OutsourcedShare.over(verdicts)
    assert (share.outsourced, share.measured) == (2, 4)
    assert share.per_cent == 50
    # Recomputing from the same verdicts gives the same value: there is nothing to reset.
    assert OutsourcedShare.over(verdicts) == share


def test_an_external_only_request_is_outside_the_denominator() -> None:
    """The closed world does not govern ``{External}``, so it does not move this number."""
    share = OutsourcedShare.over([Outsourcing.NOT_MEASURED] * 5)
    assert (share.outsourced, share.measured) == (0, 0)
    assert share.per_cent is None


def test_two_shares_combine_without_anything_owning_a_total() -> None:
    first = OutsourcedShare.over([Outsourcing.OUTSOURCED, Outsourcing.APPROVED_ANSWERED])
    second = OutsourcedShare.over([Outsourcing.OUTSOURCED, Outsourcing.BOTH_SILENT])
    assert first + second == OutsourcedShare(outsourced=2, measured=4)


def test_a_share_larger_than_its_denominator_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="subset"):
        OutsourcedShare(outsourced=3, measured=2)
    with pytest.raises(ValueError, match="negative"):
        OutsourcedShare(outsourced=-1, measured=0)


def test_the_metric_holds_no_module_level_collector() -> None:
    """The house rule, asserted at the one module most tempted to break it.

    A share is a value computed from what was answered. A module-level counter would be
    shared between concurrent requests and would make this module untestable alone, which
    is exactly the ambient collector AD-15 rules out.
    """
    module = _parse(OUTSOURCING_MODULE)
    collectors = {"list", "dict", "set", "Counter", "defaultdict", "deque"}
    # ``__all__`` is the one module-level list the tree allows: it is read by an importer
    # and never written to, so it is not a collector in the sense that matters.
    assigned = [
        statement
        for statement in module.body
        if isinstance(statement, ast.Assign | ast.AnnAssign)
        and "__all__" not in ast.dump(statement)
    ]
    offences = [
        f"{node.lineno}: {getattr(node.func, 'id', '?')}"
        for statement in assigned
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in collectors
    ]
    assert not offences, offences
    assert not [
        statement.lineno
        for statement in assigned
        for node in ast.walk(statement)
        if isinstance(node, ast.List | ast.Dict | ast.Set)
    ]


# ------------------------------------------------------------ a bad table refuses to load


def _rule_file(sources: Sequence[str], causes: Sequence[str]) -> str:
    statement = "A statement long enough for the shared schema to accept it as a rule."
    source_lines = "\n".join(f'          - "{line}"' for line in sources)
    cause_lines = "\n".join(f'          - "{line}"' for line in causes)
    return (
        "area: KB\n"
        "about: a knowledge base built for a test, in the shape of the packaged one\n"
        "rules:\n"
        f"  - id: {ADMITTED_SOURCES_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: table\n"
        "    sources: [test]\n"
        "    values:\n"
        "      sources:\n"
        f"{source_lines}\n"
        f"  - id: {ARTICLE_ADMISSION_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: table\n"
        "    sources: [test]\n"
        "    values:\n"
        "      required_true: [Published]\n"
        "      required_false: [IsDeleted]\n"
        "      counts:\n"
        "        exported: 2\n"
        "        admitted: 1\n"
        f"  - id: {OUTBOUND_INVENTORY_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: table\n"
        "    sources: [test]\n"
        "    values:\n"
        "      network_libraries: [httpx]\n"
        "      answer_path_packages: [narrate]\n"
        "      estate_holders: [adapters/model]\n"
        f"  - id: {REFUSAL_CAUSES_RULE}\n"
        f"    statement: {statement}\n"
        "    status: proposed\n"
        "    kind: table\n"
        "    sources: [test]\n"
        "    values:\n"
        "      causes:\n"
        f"{cause_lines}\n"
    )


def _load(
    directory: Path,
    sources: Sequence[str] = ("indicator | catalogue | the published indicators",),
    causes: Sequence[str] = ("no-such-indicator | nothing-matched",),
) -> KnowledgeBase:
    (directory / "knowledge-base.yaml").write_text(_rule_file(sources, causes), "utf-8")
    return load_knowledge_base(load_rules(directory))


def test_a_hand_built_table_loads_the_same_way_the_packaged_one_does(tmp_path: Path) -> None:
    """The harness' own smoke test: the failures below must be the table's, not its."""
    built = _load(tmp_path)
    assert built.keys == {"indicator"}
    assert built.tables == {"catalogue"}
    assert built.refusal_codes == ("no-such-indicator",)


def test_a_source_admitted_twice_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="admitted twice"):
        _load(tmp_path, ["indicator | catalogue | one", "indicator | detail | two"])


def test_two_sources_claiming_one_table_fail_to_load(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="claimed by"):
        _load(tmp_path, ["indicator | catalogue | one", "entity | catalogue | two"])


def test_a_line_of_the_wrong_shape_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="fields"):
        _load(tmp_path, ["indicator | catalogue"])


def test_two_causes_discovered_by_one_outcome_fail_to_load(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="discovers"):
        _load(
            tmp_path,
            causes=[
                "no-such-indicator | nothing-matched",
                "question-unsupported | nothing-matched",
            ],
        )


def test_a_cause_listed_twice_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="listed twice"):
        _load(tmp_path, causes=["no-such-indicator | -", "no-such-indicator | -"])


def test_a_knowledge_base_error_is_a_rule_load_error(tmp_path: Path) -> None:
    """An operator catching rule-load failures at startup catches this one too."""
    with pytest.raises(RuleLoadError):
        _load(tmp_path, ["indicator | catalogue"])


def test_a_missing_rule_file_refuses_rather_than_admitting_nothing(tmp_path: Path) -> None:
    """An empty admission set and a correctly closed world look identical from outside."""
    (tmp_path / "unrelated.yaml").write_text(
        "area: OTHER\n"
        "about: a rule file that says nothing about the knowledge base\n"
        "rules:\n"
        "  - id: R-OTHER-ONE\n"
        "    statement: A statement long enough for the shared schema to accept it.\n"
        "    status: proposed\n"
        "    kind: constant\n"
        "    sources: [test]\n"
        "    values:\n"
        "      anything: 1\n",
        "utf-8",
    )
    with pytest.raises(LookupError):
        load_knowledge_base(load_rules(tmp_path))
