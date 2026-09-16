"""Retrieval is measured, and the floor comes out of the measurement (AD-30, Story 2.13).

Three things are asserted here, and they are the three the story is made of.

**The labelled set is real.** 186 pairs, both languages, every expected detail id present
in the published export -- checked against `data/`, not against a fixture, because a
labelled set that has drifted from the corpus reports its own drift as a retrieval
failure. Twenty-two of the pairs expect *nothing*, and without them no floor above zero
could ever be derived: every threshold would cost recall and buy nothing measurable.

**The harness measures a port, not an implementation.** `evaluate` takes a `NamesIndex`
over whatever `VectorSourcePort` built it. The baseline below is the shipped
character-trigram source; the same call against an embedding-backed source is the
comparison, and nothing in the harness needs to change for it.

**The floor in `rules/` is the floor this set derives, and it knows what it was derived
against.** That is AD-30's staleness gate, and it is asserted in both directions: the
recorded value equals the derived one, and reading the value against a vector source it
was not derived against raises rather than returning a number.

The recall figures below are measurements taken on 2026-09-16 against the export in
`data/` (2026-08-11). A disagreement between one of them and a run is evidence about a
change in retrieval, which is what a baseline is for. They are asserted exactly, not
loosely, because AD-17 makes the whole path deterministic: the same question returns the
same list on every run, ties broken on the row id.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.index.evaluation import (
    Derivation,
    QualityReport,
    as_percent,
    derive_floor,
    derive_threshold,
    percentile,
)
from askai.adapters.index.floors import (
    CRITERION_RULE,
    CUT_RULE,
    FLOOR_RULE,
    StaleDerivationError,
    derivation_criterion,
    derived_from_set,
    floor_is_sufficient,
    relative_cut,
    resolution_floor,
)
from askai.adapters.index.labelled import (
    CASE_SUFFIX,
    SET_FILE,
    LabelKind,
    LabelledSet,
    LabelledSetError,
    load_labelled_set,
)
from askai.adapters.index.names import name_surfaces
from askai.adapters.index.quality import Measured, main, render, render_derivation, report_for
from askai.adapters.index.tuning import candidate_limit
from askai.adapters.index.vectors import TrigramVectorSource
from askai.adapters.readmodel.export import CmsExport
from askai.messages.lang import Lang
from askai.rules import rules

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
LABELLED_ROOT: Final = PROJECT_ROOT / "labelled" / "names"
EXPORT_ROOT: Final = PROJECT_ROOT / "data"

#: The composition of the set, asserted so that a file deleted or a block of pairs lost
#: in a merge fails here rather than quietly shrinking every number the harness reports.
EXPECTED_CASES: Final = 186
EXPECTED_BY_KIND: Final = {
    LabelKind.EXACT: 50,
    LabelKind.PARAPHRASE: 42,
    LabelKind.SYNONYM: 20,
    LabelKind.TYPO: 18,
    LabelKind.PARTIAL: 20,
    LabelKind.AMBIGUOUS: 14,
    LabelKind.NONE: 22,
}
EXPECTED_BY_LANG: Final = {Lang.EN: 110, Lang.AR: 76}

#: Measured, 2026-09-16, `trigram-blake2b/w3/d256/pad1` over the export in `data/`.
#: Recall at 1, over the 164 positive pairs and over each kind of naming.
TRIGRAM_RECALL_AT_1: Final = 0.7195121951219512
TRIGRAM_RECALL_BY_KIND: Final = {
    LabelKind.EXACT: 0.96,
    LabelKind.TYPO: 0.9444444444444444,
    LabelKind.PARTIAL: 1.0,
    LabelKind.AMBIGUOUS: 1.0,
    LabelKind.SYNONYM: 0.5,
    LabelKind.PARAPHRASE: 0.21428571428571427,
}

A_SET = """
# a labelled set built by a test
set: test
version: 3
built_at: 2026-09-16
"""

A_CASE = """
[t-001]
lang: en
kind: exact
question: Inflation
expect: an-id
why: a reason a reviewer could check
"""


@dataclass(frozen=True, slots=True)
class OtherSource:
    """A second vector source, identical in every way but its identity.

    Satisfies ``VectorSourcePort`` structurally. It exists to stand in for the embedding
    model being built in parallel: the assertion it supports is that a floor derived
    against trigrams cannot be read against it, and that assertion has to be makeable
    without the model.
    """

    dimensions: int = 8

    @property
    def identity(self) -> str:
        return "a-model-that-did-not-derive-this-floor"

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        return (float(len(normalised_text)),) + (0.0,) * (self.dimensions - 1)


def write_set(directory: Path, manifest: str = A_SET, cases: str = A_CASE) -> Path:
    (directory / SET_FILE).write_text(manifest, encoding="utf-8")
    (directory / f"one{CASE_SUFFIX}").write_text(cases, encoding="utf-8")
    return directory


@pytest.fixture(scope="module")
def labelled() -> LabelledSet:
    return load_labelled_set(LABELLED_ROOT)


@pytest.fixture(scope="module")
def export() -> CmsExport:
    return CmsExport.rooted(EXPORT_ROOT)


@pytest.fixture(scope="module")
def measured(
    labelled: LabelledSet, export: CmsExport, tmp_path_factory: pytest.TempPathFactory
) -> Measured:
    """One whole run of the harness against the shipped vector source.

    Module-scoped: it builds a generation over all 1,101 surfaces and puts 186 questions
    through it, and nothing in this file needs a second one.
    """
    workspace = tmp_path_factory.mktemp("names-quality")
    return report_for(labelled, export, TrigramVectorSource(), workspace=workspace)


@pytest.fixture(scope="module")
def report(measured: Measured) -> QualityReport:
    return measured.report


# ------------------------------------------------------------------ the labelled set


def test_the_labelled_set_is_versioned_and_says_which_version_it_is(
    labelled: LabelledSet,
) -> None:
    """AD-30: anything derived from a set records the version it was derived from."""
    assert labelled.name == "names"
    assert labelled.version >= 1
    assert labelled.identity == f"names-v{labelled.version}"


def test_the_labelled_set_is_the_size_and_composition_it_claims(labelled: LabelledSet) -> None:
    assert len(labelled) == EXPECTED_CASES
    assert {kind: len(labelled.by_kind(kind)) for kind in LabelKind} == EXPECTED_BY_KIND


def test_both_languages_are_first_class_rather_than_one_being_a_translation(
    labelled: LabelledSet,
) -> None:
    """Arabic is a path, not a rendering of the English path.

    Asserted as two things: there are enough Arabic pairs to measure, and they are not
    the English questions transliterated -- the Arabic set names surfaces the English set
    never reaches, so a retrieval that answered every English question and no Arabic one
    could not pass by symmetry.
    """
    by_lang = {lang: [case for case in labelled if case.lang is lang] for lang in Lang}
    assert {lang: len(cases) for lang, cases in by_lang.items()} == EXPECTED_BY_LANG
    english = {case.question for case in by_lang[Lang.EN]}
    arabic = {case.question for case in by_lang[Lang.AR]}
    assert not english & arabic
    for lang in Lang:
        kinds = {case.kind for case in by_lang[lang]}
        assert kinds == set(LabelKind), f"{lang.value} does not exercise every kind of naming"


def test_every_expected_detail_exists_in_the_published_export(
    labelled: LabelledSet, export: CmsExport
) -> None:
    """Ground truth, grounded. A pair naming a detail that does not exist measures nothing."""
    published = {surface.detail_id for surface in name_surfaces(export)}
    missing = sorted(labelled.expected_details() - published)
    assert not missing, f"{len(missing)} expected details are not in the export: {missing[:5]}"


def test_the_set_carries_negatives_because_a_floor_cannot_be_located_without_them(
    labelled: LabelledSet,
) -> None:
    """AD-30: *recall alone would reward a system that always returns its nearest neighbour*."""
    assert len(labelled.negatives) == EXPECTED_BY_KIND[LabelKind.NONE]
    assert all(case.expected == frozenset() for case in labelled.negatives)
    assert all(case.expected for case in labelled.positives)
    assert len(labelled.positives) + len(labelled.negatives) == len(labelled)


def test_every_pair_records_why_it_is_evidence(labelled: LabelledSet) -> None:
    """A pair nobody can check against the export is a pair that quietly stops being true."""
    for case in labelled:
        assert case.why.strip(), case.case_id
        assert case.question.strip(), case.case_id


def test_an_ambiguous_pair_names_more_than_one_detail(labelled: LabelledSet) -> None:
    """The kind exists because the export publishes one name on several details.

    Labelling one arbitrary member as the answer would report a one-in-eight accident as
    a retrieval failure, so an ambiguous case that names a single detail is mis-labelled.
    """
    for case in labelled.by_kind(LabelKind.AMBIGUOUS):
        assert len(case.expected) > 1, f"{case.case_id} is labelled ambiguous and names one detail"


# ------------------------------------------------------------ the loader refuses, never limps


def test_a_missing_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert SET_FILE in str(excinfo.value)


def test_a_set_with_no_version_is_refused(tmp_path: Path) -> None:
    write_set(tmp_path, manifest=A_SET.replace("version: 3", "about_version: 3"))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "version" in str(excinfo.value)


def test_a_manifest_with_no_cases_is_refused(tmp_path: Path) -> None:
    (tmp_path / SET_FILE).write_text(A_SET, encoding="utf-8")
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "no cases" in str(excinfo.value)


def test_a_duplicated_case_id_is_refused(tmp_path: Path) -> None:
    write_set(tmp_path, cases=A_CASE + A_CASE)
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "t-001" in str(excinfo.value)


def test_a_misspelled_key_is_refused(tmp_path: Path) -> None:
    """The way a case silently stops asserting what its author thought it asserted."""
    write_set(tmp_path, cases=A_CASE.replace("expect:", "expects:"))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "expects" in str(excinfo.value)


def test_a_case_expecting_nothing_must_be_labelled_as_a_negative(tmp_path: Path) -> None:
    write_set(tmp_path, cases=A_CASE.replace("expect: an-id", "expect:"))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "none" in str(excinfo.value)


def test_a_negative_case_may_not_also_expect_a_detail(tmp_path: Path) -> None:
    write_set(tmp_path, cases=A_CASE.replace("kind: exact", "kind: none"))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "cannot disagree" in str(excinfo.value)


def test_a_field_stated_twice_is_refused(tmp_path: Path) -> None:
    """Two questions in one case is a case that asserts whichever line came last."""
    write_set(tmp_path, cases=A_CASE + "question: Real GDP\n")
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "twice" in str(excinfo.value)


def test_a_field_before_any_case_is_refused(tmp_path: Path) -> None:
    """A field outside a block would silently belong to nothing."""
    write_set(tmp_path, cases="lang: en\n" + A_CASE)
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "before any" in str(excinfo.value)


def test_a_case_missing_a_field_is_refused_rather_than_defaulted(tmp_path: Path) -> None:
    write_set(tmp_path, cases=A_CASE.replace("why: a reason a reviewer could check\n", ""))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "why" in str(excinfo.value)


def test_an_unknown_kind_names_the_kinds_there_are(tmp_path: Path) -> None:
    write_set(tmp_path, cases=A_CASE.replace("kind: exact", "kind: nearly"))
    with pytest.raises(LabelledSetError) as excinfo:
        load_labelled_set(tmp_path)
    assert "paraphrase" in str(excinfo.value)


# ---------------------------------------------------------------- the trigram baseline


def test_the_harness_measures_the_source_the_index_was_built_with(
    report: QualityReport, labelled: LabelledSet
) -> None:
    """A report is only meaningful as a pair: one labelled set, one vector source."""
    assert report.labelled_identity == labelled.identity
    assert report.source_identity == TrigramVectorSource().identity
    assert report.limit == candidate_limit()
    assert len(report.measurements) == len(labelled)


def test_the_trigram_baseline_recall_is_what_was_measured(report: QualityReport) -> None:
    """The number an embedding model has to beat, pinned so that beating it is visible."""
    assert report.recall_at(1) == pytest.approx(TRIGRAM_RECALL_AT_1)
    assert report.recall_at(1) <= report.recall_at(5) <= report.recall_at(10)


def test_the_trigram_baseline_by_kind_shows_what_it_can_and_cannot_do(
    report: QualityReport,
) -> None:
    """The breakdown is the finding, not the aggregate.

    Character trigrams match spelling. They resolve every exact name, every typo and
    every partial name in the set, and they reach fewer than a quarter of the paraphrases
    at rank one -- because a paraphrase shares no characters with the surface it means.
    """
    measured = {kind: report.recall_at_for(1, kind) for kind in TRIGRAM_RECALL_BY_KIND}
    for kind, expected in TRIGRAM_RECALL_BY_KIND.items():
        assert measured[kind] == pytest.approx(expected), kind.value
    assert measured[LabelKind.PARAPHRASE] < measured[LabelKind.TYPO] / 2


def test_the_arabic_path_is_not_the_weaker_one(report: QualityReport) -> None:
    """Finding 121's failure would show up here first, as Arabic recall well below English."""
    assert report.recall_at_in(1, Lang.AR) >= report.recall_at_in(1, Lang.EN) - 0.1
    assert report.counted_in(Lang.AR) > 0


def test_the_same_run_twice_gives_the_same_numbers(
    labelled: LabelledSet, export: CmsExport, report: QualityReport, tmp_path: Path
) -> None:
    """AD-17: a measurement that moved between runs would not be a baseline at all."""
    again = report_for(labelled, export, TrigramVectorSource(), workspace=tmp_path).report
    assert [entry.rank for entry in again.measurements] == [
        entry.rank for entry in report.measurements
    ]
    assert again.relevant_scores == report.relevant_scores


# ------------------------------------------------------------------ the derivation itself


def _derive(relevant: Sequence[float], irrelevant: Sequence[float]) -> Derivation:
    return derive_threshold(
        relevant, irrelevant, high_share=0.95, false_negative_budget=0.1, false_positive_budget=0.1
    )


def test_the_derivation_finds_the_gap_in_two_separated_distributions() -> None:
    """The estimator, driven directly on distributions whose answer is known.

    Two distributions with a clean gap between them: the derived threshold sits at the
    bottom of the relevant one, costs nothing on either side, and is declared sufficient.
    """
    derivation = _derive(relevant=(0.8, 0.9, 1.0), irrelevant=(0.1, 0.2, 0.3))
    assert derivation.value == 0.8
    assert derivation.false_negative_rate == 0.0
    assert derivation.false_positive_rate == 0.0
    assert derivation.separation > 0
    assert derivation.sufficient


def test_the_derivation_declares_overlapping_distributions_insufficient() -> None:
    """AD-30: *a flat score cannot carry a distinction the index never encoded*."""
    derivation = _derive(relevant=(0.2, 0.5, 0.9), irrelevant=(0.3, 0.6, 1.0))
    assert not derivation.sufficient
    assert derivation.false_negative_rate > 0.1 or derivation.false_positive_rate > 0.1


def test_a_derivation_with_no_negatives_is_insufficient_rather_than_free() -> None:
    """Without negatives every threshold costs recall and buys nothing; that is not a floor."""
    derivation = _derive(relevant=(0.8, 0.9), irrelevant=())
    assert derivation.value == 0.0
    assert not derivation.sufficient


def test_the_derivation_is_a_maximum_and_not_the_lowest_relevant_score() -> None:
    """A floor set at the bottom of the relevant distribution would be a choice about
    which error to prefer, not a measurement: here one relevant observation sits inside
    the irrelevant range, and the derived value leaves it behind rather than admitting
    every irrelevant score to save it."""
    derivation = _derive(relevant=(0.2, 0.8, 0.9, 1.0), irrelevant=(0.1, 0.2, 0.3))
    assert derivation.value > 0.2
    assert derivation.false_negative_rate == pytest.approx(0.25)


def test_percentile_is_nearest_rank_over_the_observations() -> None:
    values = (0.1, 0.2, 0.3, 0.4, 0.5)
    assert percentile(values, 0.0) == 0.1
    assert percentile(values, 0.5) == 0.3
    assert percentile(values, 1.0) == 0.5
    assert percentile((), 0.5) == 0.0


def test_a_percentage_clause_rounds_a_floor_down_and_never_up() -> None:
    """A floor rounded up would refuse a candidate the measurement admitted."""
    assert as_percent(0.838) == 83
    assert as_percent(0.999) == 99


# ------------------------------------------------- the floor in rules/ is the derived one


def test_the_recorded_floor_is_the_floor_this_set_derives(measured: Measured) -> None:
    """AD-30's gate: the value in ``rules/`` is a measurement, re-taken here."""
    assert rules().value(FLOOR_RULE, "floor_percent") == as_percent(measured.floor.value)
    assert rules().value(CUT_RULE, "relative_cut_percent") == as_percent(measured.cut.value)


def test_the_recorded_floor_names_the_labelled_set_it_came_from(
    labelled: LabelledSet,
) -> None:
    """The staleness check. A recorded set that is not the one on disk was derived from
    distributions that no longer exist, and CI fails rather than answering by it."""
    for rule_id in (FLOOR_RULE, CUT_RULE):
        assert derived_from_set(rule_id) == labelled.identity


def test_the_recorded_floor_names_the_vector_source_it_was_derived_against() -> None:
    source = TrigramVectorSource()
    assert rules().value(FLOOR_RULE, "vector_source_identity") == source.identity
    assert resolution_floor(source) == pytest.approx(0.83)
    assert relative_cut(source) == pytest.approx(0.74)


def test_a_floor_derived_against_trigrams_cannot_be_read_against_another_source() -> None:
    """The confusion the story asks to be made impossible.

    A threshold measured in one scoring space and applied in another does not fail --
    it admits and refuses the wrong candidates, confidently, and every symptom looks like
    a retrieval problem somewhere else. So it raises, naming both identities, exactly as a
    generation refuses to load against a source that did not build it.
    """
    other = OtherSource()
    for read in (resolution_floor, relative_cut):
        with pytest.raises(StaleDerivationError) as excinfo:
            read(other)
        assert other.identity in str(excinfo.value)
        assert TrigramVectorSource().identity in str(excinfo.value)


def test_the_recorded_derivation_carries_its_evidence_and_not_just_its_value() -> None:
    """*A future change is an argument with evidence rather than a preference* (AD-30)."""
    for rule_id in (FLOOR_RULE, CUT_RULE):
        rule = rules().fire(rule_id)
        for clause in (
            "labelled_set",
            "vector_source_identity",
            "derived_on",
            "separation_percent",
            "relevant_observations",
            "irrelevant_observations",
            "sufficient",
        ):
            assert clause in rule.values, f"{rule_id} records no `{clause}`"
        assert rule.note is not None and len(rule.note) > 200


def test_the_criterion_was_declared_before_the_measurement_judged_itself(
    measured: Measured,
) -> None:
    """A budget agreed in advance can declare a result insufficient; one read off the
    result cannot. So the criterion is its own rule, and the verdict is computed from it."""
    high_share, false_negative_budget, false_positive_budget = derivation_criterion()
    assert rules().value(CRITERION_RULE, "maximum_false_negative_percent") == 10
    again = derive_floor(
        measured.report,
        high_share=high_share,
        false_negative_budget=false_negative_budget,
        false_positive_budget=false_positive_budget,
    )
    assert again.sufficient is measured.floor.sufficient
    assert again.value == measured.floor.value


def test_the_trigram_floor_is_recorded_as_insufficient_because_it_measures_so(
    measured: Measured,
) -> None:
    """The finding, asserted rather than described.

    At the derived floor the trigram space admits none of the 22 known-irrelevant scores
    and discards over a fifth of the relevant ones -- and the wrong candidates that
    outrank right ones score, in the median, within a few thousandths of the floor itself.
    A flat score cannot separate them, which is what Story 2.4's structural discriminator
    is for.
    """
    assert not measured.floor.sufficient
    assert floor_is_sufficient() is False
    assert rules().value(FLOOR_RULE, "sufficient") is False
    assert measured.floor.false_negative_rate > 0.1
    displacing = measured.report.displacing_scores
    assert displacing, "no wrong candidate outranked a right one; the finding would be stale"
    assert percentile(displacing, 0.5) == pytest.approx(measured.floor.value, abs=0.05)


def test_the_relative_cut_derives_to_a_negative_separation(measured: Measured) -> None:
    """*A good first suggestion is not followed by two bad ones* -- measured, and it is.

    The cut is derived from the same set and recorded with the same evidence, and its
    separation comes out below zero: the typical correct candidate below rank one sits
    under the upper tail of the incorrect ones. It is recorded and not applied, because
    applying it would drop right answers faster than wrong ones.
    """
    assert measured.cut.separation < 0
    assert not measured.cut.sufficient
    assert rules().value(CUT_RULE, "sufficient") is False


# ------------------------------------------------------------------------ the command


def test_the_harness_renders_every_number_a_reviewer_needs(measured: Measured) -> None:
    out = StringIO()
    render(measured, out)
    printed = out.getvalue()
    for expected in (
        measured.report.labelled_identity,
        measured.report.source_identity,
        "recall over candidate generation",
        "score distributions",
        "derived floor",
        "derived relative cut",
        "INSUFFICIENT",
    ):
        assert expected in printed
    for kind in LabelKind:
        if kind is not LabelKind.NONE:
            assert kind.value in printed


def test_the_derivation_output_is_the_rule_clauses_it_supports(measured: Measured) -> None:
    """Printed rather than written: AD-11 makes a rule file a reviewed artefact, and a
    command that edited one would turn a measurement into a deployment."""
    out = StringIO()
    render_derivation(measured, "2026-09-16", out)
    printed = out.getvalue()
    assert FLOOR_RULE in printed
    assert CUT_RULE in printed
    assert f"floor_percent: {as_percent(measured.floor.value)}" in printed
    assert f"labelled_set: {measured.report.labelled_identity}" in printed


def test_the_command_runs_here_with_no_model_and_exits_zero() -> None:
    """The instrument has to work today, on a laptop, against the shipped vector source."""
    out = StringIO()
    assert main(LABELLED_ROOT, EXPORT_ROOT, out, today="2026-09-16") == 0
    printed = out.getvalue()
    assert "names-v1" in printed
    assert FLOOR_RULE in printed


def test_the_command_reports_a_missing_labelled_set_rather_than_measuring_nothing(
    tmp_path: Path,
) -> None:
    out = StringIO()
    assert main(tmp_path, EXPORT_ROOT, out) == 1
    assert SET_FILE in out.getvalue()
    assert "recall" not in out.getvalue()


def test_the_command_leaves_no_generation_behind_it() -> None:
    """The harness builds an index to measure and is not a way of publishing one."""
    here = Path.cwd()
    before = set(here.iterdir())
    assert main(LABELLED_ROOT, EXPORT_ROOT, StringIO()) == 0
    assert set(here.iterdir()) == before


def test_the_harness_runs_as_a_command() -> None:
    """``python -m askai.adapters.index`` -- what an operator, or CI, actually types."""
    result = subprocess.run(
        [sys.executable, "-m", "askai.adapters.index"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "derived floor" in result.stdout


