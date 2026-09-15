"""Story 1.14 -- the answer states what it did.

Two things arrive with this story and each is asserted behaviourally and structurally.

1. **The scope element** (FR-56, FR-63, AD-23). Every answer carries an element of role
   ``scope`` naming the grain, the period and the country scope it used, in reader-facing
   language, composed server-side from the bilingual catalogue and rendering correctly in
   both English and Arabic. It is not a spec dump: the tests below assert that what a
   reader sees is the catalogue's own wording in both languages, and that the home
   country is never named.

2. **The role tables** (AD-23, AD-18). A role decides two things and neither is a code
   literal: which lens shows the element -- with ``scope`` in **both**, so brevity can
   never remove what makes the figure defensible -- and, for a role that carries a
   figure, the ``FormatMode`` it is written at. The mode is *"decided once by the
   element's position, never chosen per composer"*, which is asserted as a scan: no
   module in the composing layers names a ``FormatMode`` member except the one that
   defines it and the one that maps a role to it.

The corpus half of the story is a property of the corpus, not of a module: an entry
asserts on the ``QuerySpec`` and never on prose. That is scanned here against the
committed files, so an entry pinning a sentence fails the build rather than the review.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from askai.assemble import (
    FormatMode,
    Lens,
    Placed,
    Placement,
    PlacementClause,
    PlacementError,
    PlacementRule,
    Provenance,
    Role,
    ScopeMessage,
    admit,
    admit_all,
    scope_element,
    scope_statement,
)
from askai.assemble.provenance import Admitted, Refused
from askai.domain.element import ElementClass
from askai.domain.period import Period
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Exact,
    Measure,
    Operation,
    QuerySpec,
    period_field,
)
from askai.messages import Catalogue, CatalogueError, Lang, load_catalogue, render
from askai.rules import RuleSet, load_rules, rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
ASSEMBLE_ROOT = PACKAGE_ROOT / "assemble"
CORPUS_DIR = PROJECT_ROOT / "corpus"

# The two modules allowed to name a `FormatMode` member: the one that defines the enum,
# and the one that maps a role to it. Everywhere else, the mode is asked for by role.
MODE_NAMING_MODULES = (ASSEMBLE_ROOT / "format.py", ASSEMBLE_ROOT / "roles.py")

# The layers that compose an answer. `execute/` produces values, never strings.
COMPOSING_PACKAGES = ("assemble", "narrate", "respond")

# What a corpus entry may carry. The first group is the question and its context, the
# second is the `QuerySpec` the entry asserts on, the third is documentation a human
# reads. There is no fourth group, and in particular none holding an expected sentence.
CORPUS_INPUT_KEYS = frozenset({"id", "question", "today", "history", "lang", "source"})
CORPUS_SPEC_KEYS = frozenset(
    {"spec_version", "operation", "measure", "detail", "period", "country_scope", "expected"}
)
CORPUS_DOCUMENTATION_KEYS = frozenset({"why", "refusal_reason"})

# The shapes an assertion on prose takes. A corpus that pins a sentence is a corpus that
# fails when the wording is fixed in the catalogue, which is the one file wording is
# meant to be fixable in.
CORPUS_PROSE_KEYS = frozenset(
    {"answer", "text", "expected_text", "expected_answer", "prose", "narrative", "contains"}
)

# The closed set `expected` draws from -- a package kind, never a rendering.
PACKAGE_KINDS = frozenset({"answer", "refusal", "clarification"})

_ARABIC = re.compile(r"[؀-ۿ]")


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def placement() -> Placement:
    return Placement(rule_set=rules())


def a_provenance(period: str = "2026-04", country: str | None = None) -> Provenance:
    return Provenance(
        detail_id="D-CPI-HEADLINE",
        period=Period(period),
        country=country,
        source_id="S-PSA-CPI",
    )


class Resolving:
    """A source catalogue holding exactly the references it was given."""

    def __init__(self, *known: str) -> None:
        self._known = frozenset(known)

    def resolves(self, source_ref: str) -> bool:
        return source_ref in self._known


# --------------------------------------------------------------- the scope element


def test_the_answer_carries_an_element_of_role_scope(catalogue: Catalogue) -> None:
    """FR-56: the answer says what it did, and the role is not the caller's to choose."""
    placed = scope_element(catalogue, Lang.EN, a_provenance(), National())
    assert isinstance(placed, Placed)
    assert placed.role is Role.SCOPE
    assert placed.element.content


def test_the_scope_element_states_the_grain_the_period_and_the_country_scope(
    catalogue: Catalogue,
) -> None:
    """The acceptance criterion's own example, with the home country left unnamed."""
    statement = scope_statement(catalogue, Lang.EN, a_provenance(), National())
    assert statement == "monthly, National, April 2026"


@pytest.mark.parametrize(
    ("period", "grain_word"),
    [("2026-04", "monthly"), ("2026-Q1", "quarterly"), ("2025", "yearly")],
)
def test_the_grain_stated_is_the_one_the_period_carries(
    catalogue: Catalogue, period: str, grain_word: str
) -> None:
    """A period owns its grain, so the statement cannot claim a grain it does not have.

    This is the binding error the element exists to make visible: a reader seeing
    *"monthly ... 2025"* has found one, and an element assembled from two independent
    fields could never show them disagreeing.
    """
    statement = scope_statement(catalogue, Lang.EN, a_provenance(period), National())
    assert statement.startswith(grain_word)


def test_a_named_country_set_says_which_countries_were_compared(
    catalogue: Catalogue,
) -> None:
    """FR-56's *"what was compared with what"*, answered rather than implied."""
    scope: CountryScope = Named(frozenset({"KWT", "BHR"}))
    statement = scope_statement(catalogue, Lang.EN, a_provenance(), scope)
    assert "BHR" in statement
    assert "KWT" in statement
    assert statement.index("BHR") < statement.index("KWT"), "a set is stated in a stable order"


def test_a_declared_benchmark_scope_says_so_rather_than_listing_nothing(
    catalogue: Catalogue,
) -> None:
    statement = scope_statement(catalogue, Lang.EN, a_provenance(), DeclaredBenchmarks())
    assert statement != scope_statement(catalogue, Lang.EN, a_provenance(), National())
    assert render(catalogue, Lang.EN, ScopeMessage.BENCHMARKS.value) in statement


def test_every_country_scope_the_engine_binds_can_be_stated(catalogue: Catalogue) -> None:
    """The closed set, exhaustively -- a member with no phrase is a hole in the answer."""
    scopes: tuple[CountryScope, ...] = (
        National(),
        Named(frozenset({"BHR"})),
        DeclaredBenchmarks(),
    )
    for lang in Lang:
        statements = {scope_statement(catalogue, lang, a_provenance(), scope) for scope in scopes}
        assert len(statements) == len(scopes), "each scope reads differently from the others"


def test_an_unknown_country_scope_is_refused_rather_than_read_as_national(
    catalogue: Catalogue,
) -> None:
    """AD-5's failure arriving through an omission, closed off.

    A member added to ``CountryScope`` without a phrase here must fail loudly; falling
    through to the national case would be the home country vanishing from its own
    comparison for the third time.
    """
    with pytest.raises(CatalogueError):
        scope_statement(catalogue, Lang.EN, a_provenance(), "every country")  # type: ignore[arg-type]


# ------------------------------------------------- composed from the catalogue, AD-23


def test_the_statement_renders_in_both_languages(catalogue: Catalogue) -> None:
    """FR-63 and FR-61: Arabic is authored beside English, not translated at the edge."""
    english = scope_statement(catalogue, Lang.EN, a_provenance(), National())
    arabic = scope_statement(catalogue, Lang.AR, a_provenance(), National())
    assert english != arabic
    assert _ARABIC.search(arabic)
    assert not _ARABIC.search(english)


def test_the_arabic_statement_is_not_the_english_one_with_the_words_swapped(
    catalogue: Catalogue,
) -> None:
    """Every fragment is the Arabic catalogue's own: the grain word, the scope phrase,
    the period form and the punctuation between them."""
    arabic = scope_statement(catalogue, Lang.AR, a_provenance(), National())
    assert render(catalogue, Lang.AR, ScopeMessage.GRAIN_MONTHLY.value) in arabic
    assert render(catalogue, Lang.AR, ScopeMessage.NATIONAL.value) in arabic
    assert render(catalogue, Lang.AR, "period.month.4") in arabic
    assert "monthly" not in arabic
    assert "April" not in arabic


def test_the_separator_between_fragments_is_the_language_s_own(
    catalogue: Catalogue,
) -> None:
    """The mark that joins a list is editorial text, so it is an id like any other."""
    english = scope_statement(catalogue, Lang.EN, a_provenance(), Named(frozenset({"BHR", "KWT"})))
    arabic = scope_statement(catalogue, Lang.AR, a_provenance(), Named(frozenset({"BHR", "KWT"})))
    assert render(catalogue, Lang.EN, ScopeMessage.LIST_SEPARATOR.value) in english
    assert render(catalogue, Lang.AR, ScopeMessage.LIST_SEPARATOR.value) in arabic


def test_the_statement_is_not_a_spec_dump(catalogue: Catalogue) -> None:
    """AD-23: the spec block is the machine's half and this is the reader's.

    The period is written in the language's period form rather than as the published
    key, and the grain is a word rather than an enum value.
    """
    for lang in Lang:
        statement = scope_statement(catalogue, lang, a_provenance(), National())
        assert "2026-04" not in statement
        assert "national" not in statement, "the enum member's spelling is not reader text"


def test_every_message_the_scope_element_needs_exists_in_both_languages(
    catalogue: Catalogue,
) -> None:
    """The loader already refuses a lopsided pair; this names the ids this story added."""
    for message in ScopeMessage:
        for lang in Lang:
            assert catalogue.entry(lang, message.value)


# ------------------------------------------------- the element, as an element (AD-6)


def test_the_scope_element_is_derived_and_says_so(catalogue: Catalogue) -> None:
    """Computed here from the bound spec and the published row's period, inputs stated."""
    placed = scope_element(catalogue, Lang.EN, a_provenance(), National())
    assert placed.element.element_class is ElementClass.DERIVED


def test_the_scope_element_carries_the_provenance_of_the_figure_it_describes(
    catalogue: Catalogue,
) -> None:
    provenance = a_provenance()
    placed = scope_element(catalogue, Lang.EN, provenance, National())
    assert placed.element.source_ref == provenance.source_ref


def test_the_scope_element_is_admitted_and_refused_with_its_figure(
    catalogue: Catalogue,
) -> None:
    """One ``source_ref`` for both, so a statement cannot outlive the figure it describes."""
    provenance = a_provenance()
    placed = scope_element(catalogue, Lang.EN, provenance, National())
    assert isinstance(admit(placed.element, Resolving(provenance.source_ref)), Admitted)
    assert isinstance(admit(placed.element, Resolving()), Refused)


def test_a_refused_scope_element_is_counted_rather_than_dropped(
    catalogue: Catalogue,
) -> None:
    placed = scope_element(catalogue, Lang.EN, a_provenance(), National())
    assembled = admit_all([placed.element], Resolving())
    assert assembled.elements == ()
    assert len(assembled.degradations) == 1


def test_a_placed_element_is_frozen(catalogue: Catalogue) -> None:
    """The role is assigned once, in ``assemble/``, like the class beside it."""
    placed = scope_element(catalogue, Lang.EN, a_provenance(), National())
    with pytest.raises(dataclasses.FrozenInstanceError):
        placed.role = Role.HEADLINE  # type: ignore[misc]


# --------------------------------------------------------------- the lens mapping


def test_the_scope_role_appears_in_both_lenses(placement: Placement) -> None:
    """AD-23 and FR-59b: brevity may remove detail, never what makes a figure defensible."""
    assert placement.lenses_for(Role.SCOPE) == frozenset(Lens)
    for lens in Lens:
        assert placement.shows(lens, Role.SCOPE)


def test_the_lens_mapping_is_data_and_not_a_list_in_code() -> None:
    """AD-11: the mapping is reachable by rule id and clause name, so no layer needs one."""
    rule_set = rules()
    executive = rule_set.value(
        PlacementRule.LENS_MAPPING.value, PlacementClause.EXECUTIVE_ROLES.value
    )
    explore = rule_set.value(
        PlacementRule.LENS_MAPPING.value, PlacementClause.EXPLORE_ROLES.value
    )
    assert isinstance(executive, tuple)
    assert isinstance(explore, tuple)
    assert Role.SCOPE.value in executive
    assert Role.SCOPE.value in explore


def test_every_role_is_shown_by_at_least_one_lens(placement: Placement) -> None:
    """An element composed, admitted, and then shown in neither lens is a silent drop."""
    for role in Role:
        assert placement.lenses_for(role)


def test_the_executive_lens_is_shorter_than_explore_without_losing_the_scope(
    placement: Placement,
) -> None:
    """FR-59b and FR-59c: depth is added by explore, not removed by brevity."""
    executive = placement.roles_in(Lens.EXECUTIVE)
    explore = placement.roles_in(Lens.EXPLORE)
    assert executive < explore
    assert Role.SCOPE in executive


def test_a_role_no_lens_names_is_refused_rather_than_hidden(tmp_path: Path) -> None:
    """The mapping is data, so the failure mode is a data edit -- and it is loud."""
    doctored = _doctored_roles(tmp_path, ('"scope", "note"', '"note"'))
    with pytest.raises(PlacementError, match="in no lens"):
        Placement(rule_set=doctored).lenses_for(Role.SCOPE)


def test_a_lens_table_naming_something_that_is_not_a_role_fails(tmp_path: Path) -> None:
    doctored = _doctored_roles(tmp_path, ('"note"', '"footnote"'))
    with pytest.raises(PlacementError, match="not a role"):
        Placement(rule_set=doctored).roles_in(Lens.EXECUTIVE)


# --------------------------------------------------------------- the mode mapping


@pytest.mark.parametrize(
    ("role", "mode"),
    [
        (Role.HEADLINE, FormatMode.HEADLINE),
        (Role.DELTA, FormatMode.HEADLINE),
        (Role.SERIES, FormatMode.EVIDENCE),
        (Role.EVIDENCE, FormatMode.EVIDENCE),
    ],
)
def test_the_mode_is_decided_by_the_role(
    placement: Placement, role: Role, mode: FormatMode
) -> None:
    """FR-48 and AD-18: the position decides, and the position is the role."""
    assert placement.mode_for(role) is mode


@pytest.mark.parametrize(
    "role", [Role.SCOPE, Role.NOTE, Role.ANALYSIS, Role.COMMENTARY]
)
def test_a_role_that_carries_no_figure_has_no_mode(placement: Placement, role: Role) -> None:
    """Refused rather than defaulted: a default mode is how a headline acquires evidence
    precision on the one card nobody checked."""
    assert not placement.carries_a_figure(role)
    with pytest.raises(PlacementError, match="no display mode"):
        placement.mode_for(role)


def test_the_mode_mapping_is_data_and_not_a_literal_in_a_composer() -> None:
    rule_set = rules()
    for clause in (
        PlacementClause.HEADLINE_ROLES,
        PlacementClause.EVIDENCE_ROLES,
        PlacementClause.UNFIGURED_ROLES,
    ):
        value = rule_set.value(PlacementRule.FORMAT_MODE.value, clause.value)
        assert isinstance(value, tuple)
        assert value


def test_every_role_is_given_exactly_one_mode(placement: Placement) -> None:
    """The three clauses partition the roles; the read that proves it runs on every call."""
    for role in Role:
        if placement.carries_a_figure(role):
            assert placement.mode_for(role) in set(FormatMode)


def test_a_role_with_no_mode_in_the_table_fails_rather_than_defaulting(
    tmp_path: Path,
) -> None:
    """A role added to the file without a mode fails on the first answer."""
    doctored = _doctored_roles(tmp_path, ('"headline", "delta"', '"headline"'))
    with pytest.raises(PlacementError, match="named by no clause"):
        Placement(rule_set=doctored).mode_for(Role.HEADLINE)


def test_a_role_named_twice_fails_rather_than_letting_call_order_decide(
    tmp_path: Path,
) -> None:
    """One published row rendering two ways on one card is the F-004 defect (AD-18)."""
    doctored = _doctored_roles(
        tmp_path, ('evidence_roles: ["series"', 'evidence_roles: ["delta", "series"')
    )
    with pytest.raises(PlacementError, match="named twice"):
        Placement(rule_set=doctored).mode_for(Role.HEADLINE)


def test_the_mode_table_must_be_a_list_of_names(tmp_path: Path) -> None:
    doctored = _doctored_roles(
        tmp_path, ('headline_roles: ["headline", "delta"]', "headline_roles: 2")
    )
    with pytest.raises(PlacementError, match="list of role names"):
        Placement(rule_set=doctored).mode_for(Role.HEADLINE)


@pytest.mark.parametrize("package", COMPOSING_PACKAGES)
def test_no_composer_names_a_format_mode(package: str) -> None:
    """*"The mode is decided once by the element's position, never chosen per composer."*

    Asserted as a scan, because the sentence is only true while nothing else names one.
    ``format.py`` defines the enum and ``roles.py`` maps a role to it; everywhere else a
    composer holds a role and asks ``Placement.mode_for``.
    """
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line} names FormatMode.{member}"
        for path in _modules(package)
        if path not in MODE_NAMING_MODULES
        for member, line in _format_mode_mentions(_parse(path))
    ]
    assert not offences, (
        "a composer asks for the mode by role (AD-18, FR-48):\n  " + "\n  ".join(offences)
    )


def test_the_mode_naming_scan_would_catch_one() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse(
        "def show(v, published, lang):\n"
        "    return formatter.format(v, published, FormatMode.HEADLINE, lang)\n"
    )
    assert _format_mode_mentions(tree) == [("HEADLINE", 2)]


def test_roles_are_not_modelled_in_the_domain() -> None:
    """``domain/element.py``'s own claim: class is modelled there, role arrives with the
    lens mapping. A second ``Role`` would be a second vocabulary to drift."""
    definitions = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ClassDef) and node.name == "Role"
    ]
    assert len(definitions) == 1
    assert definitions[0].startswith("assemble/roles.py")


# --------------------------------------------------- the corpus asserts on the spec


def _corpus_entries() -> Iterator[tuple[Path, int, dict[str, Any]]]:
    for path in sorted(CORPUS_DIR.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not document:
            continue
        for index, entry in enumerate(document):
            assert isinstance(entry, dict), f"{path}: entry {index} is not a mapping"
            yield path, index, entry


def test_the_corpus_is_not_empty() -> None:
    """Otherwise every assertion below is vacuously true."""
    assert list(_corpus_entries())


def test_a_corpus_entry_asserts_on_the_query_spec_and_never_on_prose() -> None:
    """The ``spec`` block is echoed deliberately: it is what the corpus asserts on.

    An entry pinning a sentence would fail the day the wording is fixed in the catalogue
    -- which is the one file wording is meant to be fixable in, without a deploy.
    """
    known = CORPUS_INPUT_KEYS | CORPUS_SPEC_KEYS | CORPUS_DOCUMENTATION_KEYS
    offences = [
        f"{path.name} entry {index} carries {key!r}"
        for path, index, entry in _corpus_entries()
        for key in entry
        if key not in known or key in CORPUS_PROSE_KEYS
    ]
    assert not offences, (
        "a corpus entry asserts on the QuerySpec, never on prose:\n  " + "\n  ".join(offences)
    )


def test_every_corpus_entry_asserts_on_at_least_one_spec_field() -> None:
    for path, index, entry in _corpus_entries():
        asserted = CORPUS_SPEC_KEYS & frozenset(entry)
        assert asserted, f"{path.name} entry {index} asserts nothing about the spec"


def test_the_corpus_spec_fields_name_closed_domain_members() -> None:
    """A spec field is an enum member, not free text -- which is what makes it assertable."""
    for path, index, entry in _corpus_entries():
        where = f"{path.name} entry {index}"
        if entry.get("operation") is not None:
            assert entry["operation"] in {member.value for member in Operation}, where
        if entry.get("measure") is not None:
            assert entry["measure"] in {member.value for member in Measure}, where
        if entry.get("expected") is not None:
            assert entry["expected"] in PACKAGE_KINDS, where


def test_a_spec_is_what_the_corpus_can_compare_against() -> None:
    """The echoed block is one value, so an entry compares specs rather than renderings."""
    spec = QuerySpec(
        detail=Bound("D-CPI-HEADLINE"),
        period=period_field(Exact(Period("2026-04"))),
        country_scope=Bound(National()),
        measure=Bound(Measure.ACTUAL),
        operation=Bound(Operation.VALUE),
        today=date(2026, 9, 15),
    )
    assert spec == dataclasses.replace(spec)


# ------------------------------------------------------------------------ helpers


def _modules(package: str) -> list[Path]:
    return sorted(
        path
        for path in (PACKAGE_ROOT / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _format_mode_mentions(tree: ast.Module) -> list[tuple[str, int]]:
    return [
        (node.attr, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "FormatMode"
    ]


def _doctored_roles(tmp_path: Path, edit: tuple[str, str]) -> RuleSet:
    """The packaged role file with one substitution, loaded from a directory of its own.

    Copied rather than edited in place: a test that rewrites ``src/askai/rules/data/``
    to prove a failure mode leaves the tree broken when it is interrupted.
    """
    source = Path(rules().get(PlacementRule.FORMAT_MODE.value).source_file)
    body = source.read_text(encoding="utf-8")
    old, new = edit
    assert old in body, f"the doctored edit no longer matches the file: {old!r}"
    (tmp_path / source.name).write_text(body.replace(old, new), encoding="utf-8")
    return load_rules(tmp_path)
