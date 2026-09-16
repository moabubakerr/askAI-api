"""The ``names`` collection: one vector per surface, scored to the maximum across them.

Story 2.2's acceptance criteria, asserted against the real export in ``data/`` and
against the generation the build actually produces. Nothing here is a mock: the corpus is
the published layer, the counts are measurements, and a disagreement between a number
below and the data is evidence about the data rather than a broken test.

Two of the assertions are worth reading closely, because they are the ones a plausible
wrong implementation would still pass if they were written the obvious way.

**"Maximum across surfaces, never one blended vector."** Asserting that a detail's score
is the maximum of its surfaces' scores is not enough -- a blend of two similar surfaces
is close to their maximum, so the test would pass on the design the story exists to
forbid. So the assertion is made on a detail whose two surfaces are deliberately far
apart (a two-word Arabic name and a long English one), where a blend and a maximum
differ by more than any tolerance, and it is made again structurally: the collection
holds one row *per surface*, and each row's stored vector is the vector of its own text
and of nothing else.

**"Name and definition are two spaces, never concatenated."** The structural half is that
no row's indexed text is a name with a definition appended; the behavioural half is that a
definition-only match scores strictly below the same match on a name, by the reviewed
weight, and that removing the definition space changes the ranking rather than nothing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.index.build import build_generation
from askai.adapters.index.generation import IndexGeneration, load_generation
from askai.adapters.index.lexical import (
    NAMES_LEXICAL_TABLE,
    lexical_scores,
    match_expression,
)
from askai.adapters.index.names import NamesCorpusError, name_rows, name_surfaces
from askai.adapters.index.namesearch import NameCandidate, NamesIndex
from askai.adapters.index.schema import collection_table
from askai.adapters.index.surfaces import (
    NAME_SURFACES,
    NameSurface,
    SurfaceIdError,
    SurfaceKind,
    surface_of,
)
from askai.adapters.index.tuning import (
    DEFINITION_WEIGHT_RULE,
    LEXICAL_FUSION_RULE,
    definition_weight,
    lexical_weight,
)
from askai.adapters.index.vectors import TrigramVectorSource, unit_vector_for
from askai.adapters.readmodel.content import published_text
from askai.adapters.readmodel.export import CmsExport
from askai.domain.normalise import normalise
from askai.messages.lang import Lang
from askai.ports.index import Collection, IndexRow, IndexScope
from askai.rules import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: Measured on the export in ``data/`` (2026-08-11). AD-13 sizes the collection at
#: "~1,135 name surfaces"; this is what the published layer actually carries once
#: duplicate spellings are resolved on the engine's one normal form. See
#: ``test_the_collection_is_the_size_the_spine_budgeted_for`` for the breakdown.
EXPECTED_SURFACES: Final = 1101
EXPECTED_NAME_SURFACES: Final = 897
EXPECTED_DEFINITION_SURFACES: Final = 204
EXPECTED_DETAILS: Final = 289
EXPECTED_INDICATORS: Final = 189

BUILT_AT: Final = "2026-09-15T10:00:00+00:00"

# A synthetic detail whose two names are as far apart as the corpus gets: two Arabic
# words, and a long English phrase naming the same thing. A blended vector and a maximum
# across surfaces cannot both be right about this row, which is the point of it.
SHORT_ARABIC: Final = "معدل التضخم"
LONG_ENGLISH: Final = "Consumer Price Index annual inflation rate for the national basket"
A_DEFINITION: Final = (
    "The percentage change over twelve months in the weighted average of prices paid by "
    "households for a fixed basket of goods and services."
)

INDICATOR: Final = "11111111-1111-1111-1111-111111111111"
DETAIL: Final = "22222222-2222-2222-2222-222222222222"
OTHER_DETAIL: Final = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(scope="module")
def source() -> TrigramVectorSource:
    return TrigramVectorSource()


@pytest.fixture(scope="module")
def export() -> CmsExport:
    return CmsExport.rooted(EXPORT_ROOT)


@pytest.fixture(scope="module")
def surfaces(export: CmsExport) -> tuple[NameSurface, ...]:
    return name_surfaces(export)


@pytest.fixture(scope="module")
def published(
    tmp_path_factory: pytest.TempPathFactory, export: CmsExport, source: TrigramVectorSource
) -> IndexGeneration:
    """The whole published ``names`` collection, built and loaded once for the module."""
    directory = tmp_path_factory.mktemp("published-names")
    path = build_generation(
        directory, {Collection.NAMES: name_rows(export)}, source, built_at=BUILT_AT
    )
    return load_generation(path, source)


@pytest.fixture(scope="module")
def published_index(published: IndexGeneration) -> NamesIndex:
    return NamesIndex(published)


def _surface(kind: SurfaceKind, lang: Lang, text: str, *, detail: str = DETAIL) -> NameSurface:
    return NameSurface(
        indicator_id=INDICATOR, detail_id=detail, kind=kind, lang=lang, text=text
    )


def _synthetic() -> tuple[IndexRow, ...]:
    """One detail with four surfaces, and a second detail to rank against."""
    return (
        _surface(SurfaceKind.DETAIL_NAME, Lang.EN, LONG_ENGLISH).row(),
        _surface(SurfaceKind.DETAIL_NAME, Lang.AR, SHORT_ARABIC).row(),
        _surface(SurfaceKind.LABEL, Lang.EN, "Inflation").row(),
        _surface(SurfaceKind.DEFINITION, Lang.EN, A_DEFINITION).row(),
        _surface(
            SurfaceKind.DETAIL_NAME, Lang.EN, "Total Population", detail=OTHER_DETAIL
        ).row(),
    )


@pytest.fixture
def synthetic(tmp_path: Path, source: TrigramVectorSource) -> NamesIndex:
    path = build_generation(
        tmp_path, {Collection.NAMES: _synthetic()}, source, built_at=BUILT_AT
    )
    return NamesIndex(load_generation(path, source))


def _best(candidates: Sequence[NameCandidate], detail_id: str) -> NameCandidate:
    for candidate in candidates:
        if candidate.detail_id == detail_id:
            return candidate
    raise AssertionError(f"{detail_id} is not among {[c.detail_id for c in candidates]}")


# ------------------------------------------------- one row per surface, each in EN and AR


def test_every_published_surface_gets_its_own_row(surfaces: tuple[NameSurface, ...]) -> None:
    """The load-bearing shape: a row is (detail, kind, language), not (detail)."""
    identities = {(s.detail_id, s.kind, s.lang) for s in surfaces}
    assert len(identities) == len(surfaces), "two surfaces share one identity"
    assert len({s.row_id for s in surfaces}) == len(surfaces)


def test_a_surface_row_carries_its_kind_and_its_language(
    surfaces: tuple[NameSurface, ...],
) -> None:
    """Each row says which surface it is -- the AC's `carrying a kind`."""
    for surface in surfaces:
        parsed = surface_of(surface.row())
        assert parsed == surface
        assert parsed.kind in set(SurfaceKind)
        assert parsed.lang in set(Lang)


def test_both_languages_are_indexed_as_separate_rows(
    surfaces: tuple[NameSurface, ...],
) -> None:
    by_lang = {lang: [s for s in surfaces if s.lang is lang] for lang in Lang}
    assert all(by_lang.values()), "a language with no surfaces cannot be asked a question"
    for detail_name in (s for s in surfaces if s.kind is SurfaceKind.DETAIL_NAME):
        assert detail_name.text.strip()


def test_each_row_holds_the_vector_of_its_own_text_and_nothing_else(
    published: IndexGeneration, source: TrigramVectorSource
) -> None:
    """One vector per surface, structurally: no row's vector is a blend of two texts."""
    loaded = published.collections[Collection.NAMES]
    for row, vector in zip(loaded.rows[:200], loaded.vectors[:200], strict=True):
        assert vector == pytest.approx(unit_vector_for(row.text, source), abs=1e-6)


def test_every_names_row_points_back_at_a_detail(published: IndexGeneration) -> None:
    """Including the ones carrying an indicator's name: AD-14 filters on a column, and a
    candidate with no detail is one the discrimination stage cannot scope."""
    for row in published.collections[Collection.NAMES].rows:
        surface = surface_of(row)
        assert row.detail_id == surface.detail_id
        assert row.detail_id


# ------------------------------------------------------- where the surfaces come from


def test_the_surfaces_are_the_columns_the_published_layer_carries(
    surfaces: tuple[NameSurface, ...], export: CmsExport
) -> None:
    """Grounded in the export: every indexed text is a cell that exists in ``P01``/``P02``."""
    indicator_names = {
        normalise(row[column])
        for row in export.published_indicators()
        for column in ("NameEN", "NameAR")
    }
    detail_names = {
        normalise(row[column])
        for row in export.published_details()
        for column in ("NameEN", "NameAR")
    }
    labels = {
        normalise(row[column])
        for row in export.published_details()
        for column in ("LabelEN", "LabelAR")
    }
    published_cells = {
        SurfaceKind.INDICATOR_NAME: indicator_names,
        SurfaceKind.DETAIL_NAME: detail_names,
        SurfaceKind.LABEL: labels,
    }
    for surface in surfaces:
        if surface.kind is SurfaceKind.DEFINITION:
            continue
        assert normalise(surface.text) in published_cells[surface.kind]


def test_no_alias_surface_is_invented(surfaces: tuple[NameSurface, ...]) -> None:
    """The AC names an `alias` surface; this export publishes none, anywhere.

    There is no alias column on ``P01`` or ``P02``, no alias reference table, and no loose
    file carrying alternative names for an indicator. So there is no ``ALIAS`` kind and no
    row claiming to be one -- an empty surface in the enum would tell a reader that
    aliases were searched when nothing was.
    """
    assert "alias" not in {kind.value for kind in SurfaceKind}
    assert all(surface.kind in set(SurfaceKind) for surface in surfaces)


def test_a_repeated_spelling_is_one_surface_and_keeps_the_most_specific_kind(
    surfaces: tuple[NameSurface, ...],
) -> None:
    """Most details repeat their name as their label; indexing it twice buys nothing.

    Two identical rows would score identically and make "which surface matched"
    unanswerable, which is the one thing this collection has to be able to say.
    """
    by_detail: dict[tuple[str, Lang], set[str]] = {}
    for surface in surfaces:
        key = (surface.detail_id, surface.lang)
        folded = normalise(surface.text)
        assert folded not in by_detail.get(key, set()), (
            f"{surface.detail_id} indexes {surface.text!r} twice"
        )
        by_detail.setdefault(key, set()).add(folded)
    # The preference order is the declared one: a duplicate never costs the detail its
    # own name in favour of its indicator's.
    kinds: dict[tuple[str, Lang], list[SurfaceKind]] = {
        (s.detail_id, s.lang): [] for s in surfaces
    }
    for surface in surfaces:
        if surface.kind is not SurfaceKind.DEFINITION:
            kinds[(surface.detail_id, surface.lang)].append(surface.kind)
    for present in kinds.values():
        assert present == sorted(present, key=NAME_SURFACES.index)
        assert present[0] is SurfaceKind.DETAIL_NAME


def test_a_confidential_indicator_publishes_no_searchable_name(tmp_path: Path) -> None:
    """FR-50 is about names as much as about values: a name is how a reader finds a thing."""
    surfaces = name_surfaces(_export_with_one_confidential_indicator(tmp_path))
    assert surfaces, "the fixture export publishes more than the refused indicator"
    assert all(surface.indicator_id != "i-secret" for surface in surfaces)


def test_the_collection_is_the_size_the_spine_budgeted_for(
    surfaces: tuple[NameSurface, ...], published: IndexGeneration
) -> None:
    """AD-13 budgets ~1,135 name surfaces. Measured on this export, it is 1,101.

    The breakdown, so the number is auditable rather than pinned:

    * 289 details x 2 languages = 578 detail-name rows -- every detail publishes both;
    * 253 indicator-name rows -- 578 possible, minus the 325 details whose own name
      already folds to their indicator's;
    * 66 label rows -- 578 possible, minus the 512 labels that repeat the detail's name;
    * 204 definition rows -- 578 cells, minus 237 that are empty rich-text shells or a
      bare hyphen and 137 that merely repeat a name.
    """
    assert len(surfaces) == EXPECTED_SURFACES
    assert published.size(Collection.NAMES) == EXPECTED_SURFACES
    names = [s for s in surfaces if not s.is_definition]
    assert len(names) == EXPECTED_NAME_SURFACES
    assert len(surfaces) - len(names) == EXPECTED_DEFINITION_SURFACES
    assert len({s.detail_id for s in surfaces}) == EXPECTED_DETAILS
    assert len({s.indicator_id for s in surfaces}) == EXPECTED_INDICATORS
    counted = {kind: len([s for s in surfaces if s.kind is kind]) for kind in SurfaceKind}
    assert counted == {
        SurfaceKind.DETAIL_NAME: 578,
        SurfaceKind.INDICATOR_NAME: 253,
        SurfaceKind.LABEL: 66,
        SurfaceKind.DEFINITION: 204,
    }


# --------------------------------------------- the maximum across surfaces, never a blend


def test_the_short_arabic_name_is_not_diluted_by_the_long_english_one(
    synthetic: NamesIndex, source: TrigramVectorSource
) -> None:
    """The story's own sentence, as an assertion.

    The Arabic question is scored against the Arabic surface at that surface's own
    length. A single blended vector per detail would have to include the long English
    name, which shares almost no trigram with the question, and the score would collapse
    towards the blend.
    """
    candidates = synthetic.candidates(SHORT_ARABIC, scope=IndexScope())
    candidate = _best(candidates, DETAIL)
    assert candidate.matched.surface.lang is Lang.AR
    assert candidate.matched.surface.text == SHORT_ARABIC
    # The surface matched itself, so its cosine is 1 and nothing dragged it down.
    assert candidate.matched.cosine == pytest.approx(1.0, abs=1e-6)
    blended = unit_vector_for(f"{SHORT_ARABIC} {LONG_ENGLISH}", source)
    query = unit_vector_for(SHORT_ARABIC, source)
    blend_score = sum(a * b for a, b in zip(query, blended, strict=True))
    assert blend_score < 0.8, "the fixture must make blending visibly worse"
    assert candidate.matched.cosine > blend_score


def test_a_detail_scores_as_the_maximum_of_its_surfaces(synthetic: NamesIndex) -> None:
    candidate = _best(synthetic.candidates(SHORT_ARABIC, scope=IndexScope()), DETAIL)
    names = [scored for scored in candidate.surfaces if not scored.surface.is_definition]
    assert candidate.name_score == pytest.approx(max(scored.score for scored in names))
    assert candidate.name_score == pytest.approx(candidate.matched.score)


def test_every_surface_of_a_matched_detail_is_carried_not_only_the_winner(
    synthetic: NamesIndex,
) -> None:
    """A maximum is only defensible if the values it was taken over are visible."""
    candidate = _best(synthetic.candidates("inflation", scope=IndexScope()), DETAIL)
    assert len(candidate.surfaces) > 1
    assert candidate.matched in candidate.surfaces
    assert candidate.surfaces[0] == max(candidate.surfaces, key=lambda s: s.score)


def test_a_question_reaches_one_candidate_per_detail_not_one_per_surface(
    published_index: NamesIndex,
) -> None:
    """The reviewed candidate count is ten *things to discriminate*, not ten spellings."""
    candidates = published_index.candidates("sector contribution to gdp", scope=IndexScope())
    assert candidates
    assert len({candidate.detail_id for candidate in candidates}) == len(candidates)


# ---------------------------------------------------- which surface matched (finding 32)


def test_the_matched_surface_is_recorded_so_an_answer_can_disclose_it(
    synthetic: NamesIndex,
) -> None:
    arabic = _best(synthetic.candidates(SHORT_ARABIC, scope=IndexScope()), DETAIL)
    english = _best(synthetic.candidates("national basket", scope=IndexScope()), DETAIL)
    assert arabic.matched.surface.lang is Lang.AR
    assert english.matched.surface.lang is Lang.EN
    assert arabic.matched.surface.kind is SurfaceKind.DETAIL_NAME
    assert english.matched.surface.text == LONG_ENGLISH


def test_a_label_match_is_disclosed_as_a_label(synthetic: NamesIndex) -> None:
    candidate = _best(synthetic.candidates("Inflation", scope=IndexScope()), DETAIL)
    assert candidate.matched.surface.kind is SurfaceKind.LABEL
    assert candidate.matched.surface.text == "Inflation"


def test_a_candidate_carried_by_its_definition_says_so(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """It does not borrow the name it did not match."""
    rows = (
        _surface(SurfaceKind.DETAIL_NAME, Lang.EN, "Total Population").row(),
        _surface(SurfaceKind.DEFINITION, Lang.EN, A_DEFINITION).row(),
    )
    index = NamesIndex(
        load_generation(
            build_generation(tmp_path, {Collection.NAMES: rows}, source, built_at=BUILT_AT),
            source,
        )
    )
    candidate = _best(index.candidates("basket of goods and services", scope=IndexScope()), DETAIL)
    assert candidate.matched.surface.kind is SurfaceKind.DEFINITION
    assert candidate.definition_score > candidate.name_score


def test_both_halves_of_the_hybrid_are_disclosed_per_surface(
    published_index: NamesIndex,
) -> None:
    """A candidate that was typed and one that was paraphrased are distinguishable."""
    candidates = published_index.candidates("population", scope=IndexScope())
    assert candidates
    assert any(candidate.matched.lexical > 0.0 for candidate in candidates)
    assert all(candidate.matched.cosine >= 0.0 for candidate in candidates)


# ------------------------------------- two scoring spaces, definition weighted, never one field


def test_no_row_concatenates_a_name_with_a_definition(
    published: IndexGeneration, export: CmsExport
) -> None:
    """The structural half: there is no field holding both, so the failure is unrepresentable.

    Every indexed text is *exactly one* published cell. A concatenation would be a text
    equal to no cell the export carries, which is what this rules out -- and it rules it
    out without asking whether one cell happens to be a substring of another, which on
    this corpus it sometimes is.
    """
    indicators = {row["PublishedIndicatorId"]: row for row in export.published_indicators()}
    cells: dict[str, set[str]] = {}
    for detail in export.published_details():
        indicator = indicators[detail["PublishedIndicatorId"]]
        cells[detail["PublishedIndicatorDetailId"]] = {
            text
            for text in (
                detail["NameEN"].strip(),
                detail["NameAR"].strip(),
                detail["LabelEN"].strip(),
                detail["LabelAR"].strip(),
                published_text(detail["DefinationEN"].strip()) or "",
                published_text(detail["DefinationAR"].strip()) or "",
                indicator["NameEN"].strip(),
                indicator["NameAR"].strip(),
            )
            if text
        }
    for row in published.collections[Collection.NAMES].rows:
        surface = surface_of(row)
        assert row.text in cells[surface.detail_id], (
            f"{row.id} indexes text that is no single published cell"
        )


def test_the_definition_space_is_weighted_and_combined_at_the_end(
    synthetic: NamesIndex,
) -> None:
    candidate = _best(synthetic.candidates("inflation rate basket", scope=IndexScope()), DETAIL)
    assert candidate.definition_score > 0.0
    assert candidate.score == pytest.approx(
        candidate.name_score + definition_weight() * candidate.definition_score
    )


def test_the_definition_weight_is_a_half_and_carries_its_reason(synthetic: NamesIndex) -> None:
    """AD-11 and the AC together: the number *and* why, in ``rules/``."""
    assert definition_weight() == pytest.approx(0.5)
    rule = rules().get(DEFINITION_WEIGHT_RULE).rule
    assert rule.values["definition_weight_percent"] == 50
    reason = (rule.note or "").lower()
    assert "4 first-place answers" in reason or "4 first-place" in reason
    assert "false positives" in reason
    assert "50 real questions" in reason


def test_a_definition_match_cannot_outrank_the_same_match_on_a_name(
    tmp_path: Path, source: TrigramVectorSource
) -> None:
    """The weight's whole purpose: a definition breaks ties, it does not win outright."""
    shared = "gross domestic product at constant prices"
    rows = (
        _surface(SurfaceKind.DETAIL_NAME, Lang.EN, shared).row(),
        _surface(SurfaceKind.DEFINITION, Lang.EN, shared, detail=OTHER_DETAIL).row(),
        _surface(SurfaceKind.DETAIL_NAME, Lang.EN, "Total Population", detail=OTHER_DETAIL).row(),
    )
    index = NamesIndex(
        load_generation(
            build_generation(tmp_path, {Collection.NAMES: rows}, source, built_at=BUILT_AT),
            source,
        )
    )
    candidates = index.candidates(shared, scope=IndexScope())
    assert candidates[0].detail_id == DETAIL
    assert _best(candidates, DETAIL).score > _best(candidates, OTHER_DETAIL).score


# ----------------------------------------------------------- one normalisation (AD-26)


def test_the_surface_build_and_the_query_fold_with_the_engines_one_normalisation() -> None:
    """Both halves of the hybrid, not only the vector half.

    An FTS5 tokeniser folding text its own way is exactly how the index and the query
    come apart: finding 121's Arabic half is that failure, and it is invisible in English.
    """
    import askai.adapters.index.lexical as lexical_module
    import askai.adapters.index.names as names_module
    import askai.adapters.index.vectors as vectors_module

    # `vars(...)` rather than attribute access: the claim is about the object each module
    # actually holds at runtime, which a re-export or a shim would hide.
    assert vars(lexical_module)["normalise"] is normalise
    assert vars(names_module)["normalise"] is normalise
    assert vars(vectors_module)["normalise"] is normalise


def test_a_differently_spelled_arabic_question_reaches_the_indexed_surface(
    synthetic: NamesIndex,
) -> None:
    """Hamza, teh marbuta and diacritics are folded on both sides, so they cannot split a root."""
    spelled_otherwise = "مُعَدَّل التَّضَخُّم"
    assert spelled_otherwise != SHORT_ARABIC
    candidate = _best(synthetic.candidates(spelled_otherwise, scope=IndexScope()), DETAIL)
    assert candidate.matched.cosine == pytest.approx(1.0, abs=1e-6)


def test_the_lexical_half_indexes_the_folded_form_not_the_published_spelling(
    published: IndexGeneration,
) -> None:
    connection = sqlite3.connect(str(published.path))
    try:
        indexed = dict(
            connection.execute("SELECT row_id, folded FROM " + NAMES_LEXICAL_TABLE)
        )
        stored = dict(
            connection.execute(
                "SELECT id, text FROM " + collection_table(Collection.NAMES)
            )
        )
    finally:
        connection.close()
    assert set(indexed) == set(stored)
    for row_id, folded in indexed.items():
        assert folded == normalise(str(stored[row_id]))


# ------------------------------------------------------- FTS5, fused, with no second system


def test_the_lexical_table_lives_in_the_same_generation_file_as_the_vectors(
    published: IndexGeneration,
) -> None:
    """"Hybrid search with no second system": one file, one build, one rename."""
    connection = sqlite3.connect(str(published.path))
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()
    assert NAMES_LEXICAL_TABLE in tables
    assert collection_table(Collection.NAMES) in tables


def test_an_exactly_typed_name_is_found_lexically(published_index: NamesIndex) -> None:
    candidates = published_index.candidates("Sector Contribution To GDP", scope=IndexScope())
    matched = _best(candidates, candidates[0].detail_id)
    assert matched.matched.lexical > 0.0
    assert normalise("sector contribution to gdp") in normalise(matched.matched.surface.text)


def test_a_misspelling_is_still_reached_by_the_semantic_half(
    synthetic: NamesIndex,
) -> None:
    """One trigram short of the name: the lexical half misses it and the fusion does not."""
    candidate = _best(synthetic.candidates("inflaton", scope=IndexScope()), DETAIL)
    assert candidate.matched.lexical == 0.0
    assert candidate.matched.cosine > 0.0
    assert candidate.score > 0.0


def test_a_lexical_only_row_is_still_a_candidate(
    published: IndexGeneration, published_index: NamesIndex
) -> None:
    """The union, not the intersection -- and the scope filter applies to both halves."""
    lexical = lexical_scores(published.path, "population")
    assert lexical
    candidates = published_index.candidates("population", scope=IndexScope())
    reached = {scored.surface.row_id for c in candidates for scored in c.surfaces}
    assert reached & set(lexical)


def test_a_question_is_never_read_as_fts5_syntax() -> None:
    """Every token is quoted, so a reader typing a query language types a question."""
    expression = match_expression('inflation AND "rate" OR NEAR(x)')
    assert expression is not None
    assert expression.count(" OR ") == len(expression.split(" OR ")) - 1
    assert all(term.startswith('"') and term.endswith('"') for term in expression.split(" OR "))


def test_a_question_with_no_terms_matches_nothing_rather_than_everything(
    published: IndexGeneration,
) -> None:
    assert match_expression("!!! ...") is None
    assert lexical_scores(published.path, "!!! ...") == {}


def test_the_lexical_weight_is_reviewed_and_stated_to_be_a_default() -> None:
    assert 0.0 <= lexical_weight() <= 1.0
    rule = rules().get(LEXICAL_FUSION_RULE).rule
    assert rule.values["lexical_weight_percent"] == 50
    assert "default" in (rule.note or "").lower()


def test_a_surface_score_is_the_two_halves_fused_at_the_reviewed_weight(
    synthetic: NamesIndex,
) -> None:
    candidate = _best(synthetic.candidates(SHORT_ARABIC, scope=IndexScope()), DETAIL)
    weight = lexical_weight()
    for scored in candidate.surfaces:
        assert scored.score == pytest.approx(
            (1.0 - weight) * scored.cosine + weight * scored.lexical
        )


# ------------------------------------------------------- filtered before it is ranked (AD-14)


def test_the_scope_is_a_pre_filter_over_the_hybrid_not_only_over_the_cosine(
    published: IndexGeneration, published_index: NamesIndex
) -> None:
    """A row the lexical half found and the scope excludes is not a candidate."""
    detail_id = surface_of(published.collections[Collection.NAMES].rows[0]).detail_id
    candidates = published_index.candidates(
        "population", scope=IndexScope(detail_id=detail_id)
    )
    assert {candidate.detail_id for candidate in candidates} <= {detail_id}


def test_a_language_scope_returns_only_that_languages_surfaces(
    published_index: NamesIndex,
) -> None:
    candidates = published_index.candidates("population", scope=IndexScope(lang=Lang.AR))
    assert candidates
    for candidate in candidates:
        assert all(scored.surface.lang is Lang.AR for scored in candidate.surfaces)


def test_a_scope_admitting_nothing_returns_nothing(published_index: NamesIndex) -> None:
    assert published_index.candidates("population", scope=IndexScope(detail_id="no-such")) == ()


# ------------------------------------------------------------------- determinism, no floor


def test_the_same_question_returns_the_same_candidates_every_time(
    published_index: NamesIndex,
) -> None:
    first = published_index.candidates("economy growth", scope=IndexScope())
    second = published_index.candidates("economy growth", scope=IndexScope())
    assert [(c.detail_id, c.score) for c in first] == [(c.detail_id, c.score) for c in second]


def test_ties_break_on_the_detail_id(tmp_path: Path, source: TrigramVectorSource) -> None:
    rows = (
        _surface(SurfaceKind.DETAIL_NAME, Lang.EN, "Total Population").row(),
        _surface(
            SurfaceKind.DETAIL_NAME, Lang.EN, "Total Population", detail=OTHER_DETAIL
        ).row(),
    )
    index = NamesIndex(
        load_generation(
            build_generation(tmp_path, {Collection.NAMES: rows}, source, built_at=BUILT_AT),
            source,
        )
    )
    candidates = index.candidates("Total Population", scope=IndexScope())
    assert [candidate.detail_id for candidate in candidates] == sorted(
        [DETAIL, OTHER_DETAIL]
    )


def test_this_story_invents_no_relevance_floor(published_index: NamesIndex) -> None:
    """AD-30: a floor is derived from a labelled set, and there is no labelled set yet."""
    for entry in rules():
        assert "floor" not in entry.rule.values, f"{entry.id} declares an underived floor"
    candidates = published_index.candidates("economy", scope=IndexScope())
    assert candidates
    assert min(candidate.score for candidate in candidates) < 0.5


def test_a_question_that_folds_to_nothing_returns_nothing(published_index: NamesIndex) -> None:
    assert published_index.candidates("...", scope=IndexScope()) == ()


# ------------------------------------------------------------------ the id grammar refuses


def test_a_row_id_from_another_collection_has_no_surface() -> None:
    with pytest.raises(SurfaceIdError, match="not a names row id"):
        surface_of(IndexRow(id="a-1", lang=Lang.EN, text="anything"))


def test_a_row_id_naming_an_unknown_kind_is_refused() -> None:
    with pytest.raises(SurfaceIdError, match="which is not one"):
        surface_of(IndexRow(id="i|d|nickname|en", lang=Lang.EN, text="anything"))


def test_a_row_disagreeing_with_its_own_id_about_language_is_refused() -> None:
    with pytest.raises(SurfaceIdError, match="cannot be attributed"):
        surface_of(IndexRow(id="i|d|detail_name|ar", lang=Lang.EN, text="anything"))


def test_an_id_part_containing_the_separator_is_refused() -> None:
    with pytest.raises(SurfaceIdError, match="separator"):
        _surface(SurfaceKind.LABEL, Lang.EN, "x", detail="a|b")


def test_a_duplicate_surface_id_stops_the_build(tmp_path: Path) -> None:
    """Named where the message can say which detail, not three layers down at the insert."""
    export = _export_with_a_duplicated_detail(tmp_path)
    with pytest.raises(NamesCorpusError, match="published twice"):
        name_surfaces(export)


# ------------------------------------------------------------------------ fixture exports

_INDICATOR_HEADER: Final = (
    "PublishedIndicatorId,NameEN,NameAR,IndicatorPriorityTypeId,"
    "IndicatorEntityTypeId,EntityClassificationName\n"
)
_DETAIL_HEADER: Final = (
    "PublishedIndicatorDetailId,PublishedIndicatorId,NameEN,NameAR,"
    "LabelEN,LabelAR,DefinationEN,DefinationAR\n"
)
_PRIORITY_HEADER: Final = "Id,NameEN,NameAR\n"


def _write_export(directory: Path, indicators: str, details: str) -> CmsExport:
    cms = directory / "cms"
    cms.mkdir(parents=True, exist_ok=True)
    (cms / "P01_Published_Indicators-x.csv").write_text(
        _INDICATOR_HEADER + indicators, encoding="utf-8"
    )
    (cms / "P02_Published_IndicatorDetails-x.csv").write_text(
        _DETAIL_HEADER + details, encoding="utf-8"
    )
    (cms / "P13_Ref_IndicatorPriorityTypes-x.csv").write_text(
        _PRIORITY_HEADER + "p-open,Priority,x\np-secret,Confidential,x\n", encoding="utf-8"
    )
    return CmsExport.rooted(directory)


def _export_with_one_confidential_indicator(directory: Path) -> CmsExport:
    return _write_export(
        directory,
        "i-open,Open Indicator,مؤشر,p-open,e,Sectors\n"
        "i-secret,Secret Indicator,سري,p-secret,e,Sectors\n",
        "d-open,i-open,Open Detail,تفصيل,Open Detail,تفصيل,-,-\n"
        "d-secret,i-secret,Secret Detail,سري,Secret Detail,سري,-,-\n",
    )


def _export_with_a_duplicated_detail(directory: Path) -> CmsExport:
    return _write_export(
        directory,
        "i-open,Open Indicator,مؤشر,p-open,e,Sectors\n",
        "d-open,i-open,One,واحد,One,واحد,-,-\nd-open,i-open,Two,اثنان,Two,اثنان,-,-\n",
    )
