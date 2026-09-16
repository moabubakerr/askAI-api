"""AD-25's resolution ladder: generate, discriminate, decide.

Stories 2.3, 2.4 and 2.5, asserted as three stages rather than as one pipeline, because
the architecture's central claim about them is that they are *separable* and may not be
collapsed into one scoring pass.

Almost everything here runs on hand-built :class:`Candidate` values and no index at all.
That is not a convenience: stage 2 being pure -- values in, values out, no port, no store,
no model -- is the property that makes NFR-5 true, and a test that could only exercise it
through a built generation would not be testing that property. The stage-1 tests that do
need a real corpus say so and use the published export.

Three assertions below are the ones a plausible wrong implementation would still pass if
they were written the obvious way, and each is written the other way on purpose:

**"A veto is not a heavy weight."** Asserting that a wrong-grain candidate ranks below a
right-grain one passes on a design where grain is merely weighted heavily. So the
assertion is that the candidate is *absent* from the survivors and present in ``vetoed``,
and it is made against a candidate that wins every other signal -- where a weight, however
large, would leave it on top.

**"Discrimination never re-ranks on stage 1's score."** Asserting the right candidate wins
passes when the scores happen to agree. So the assertion is made with the stage-1 scores
deliberately *inverted* against the structural evidence: the candidate with the worst
similarity and the best facts must win, which no implementation that consults ``score``
can do.

**"Several survivors become a disambiguation, not a pick."** Asserting that a tie returns
several candidates passes on an implementation that returns several and then binds the
first anyway. So the assertion is on the *type* of the outcome, and on the fact that the
bound detail is unreachable from it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final

import pytest

from askai.adapters.index.build import build_generation
from askai.adapters.index.facts import detail_facts
from askai.adapters.index.generation import load_generation
from askai.adapters.index.names import name_rows
from askai.adapters.index.resolution import IndexCandidates
from askai.adapters.index.vectors import TrigramVectorSource
from askai.adapters.readmodel.export import CmsExport
from askai.compile.resolve import (
    Disambiguation,
    QuestionSignals,
    Refusal,
    RefusalCause,
    Resolved,
    SignalName,
    decide,
    discriminate,
    generate,
    resolve,
    subject_of,
    window_for,
)
from askai.compile.resolve.generate import admits, content_ngrams
from askai.compile.resolve.tuning import (
    ambiguity_margin,
    fold_unit,
    margin_labelled_set,
    maximum_offered,
    minimum_ngram,
    period_vocabulary,
    unit_shapes,
)
from askai.domain.period import Grain, Period
from askai.domain.spec import Exact, LastN, Latest, Range
from askai.messages.lang import Lang
from askai.ports.index import Collection
from askai.ports.resolution import (
    Candidate,
    CandidateFacts,
    CandidatePort,
    MatchedSurface,
    UnitShape,
)

EXPORT_ROOT: Final = Path("data")
BUILT_AT: Final = "2026-09-16T10:00:00+00:00"
TODAY: Final = date(2026, 9, 16)


# ------------------------------------------------------------------ hand-built candidates


def _candidate(
    detail_id: str,
    *,
    score: float = 1.0,
    surfaces: Sequence[str] = ("gross domestic product",),
    periods: Sequence[str] = (),
    countries: Sequence[str] = (),
    unit: UnitShape = UnitShape.UNKNOWN,
    entities: Sequence[str] = (),
    indicator_id: str = "indicator",
) -> Candidate:
    """One candidate, with only the facts a test cares about populated.

    Every fact defaults to empty, which is the state that makes its signal *silent*. A
    test therefore states exactly the evidence it is about, and a signal it did not
    mention cannot quietly decide the case it is asserting.
    """
    return Candidate(
        detail_id=detail_id,
        indicator_id=indicator_id,
        score=score,
        matched=MatchedSurface(
            kind="detail_name", lang=Lang.EN, text=surfaces[0] if surfaces else detail_id
        ),
        facts=CandidateFacts(
            periods=frozenset(Period(value) for value in periods),
            benchmark_countries=frozenset(countries),
            unit_shape=unit,
            entity_names=tuple(entities),
        ),
        surfaces=tuple(surfaces),
    )


class _Fixed:
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
        return self._candidates if limit is None else self._candidates[:limit]


def test_the_fixed_port_satisfies_the_protocol() -> None:
    """Otherwise every test below is asserting against a shape the real adapter is not."""
    assert isinstance(_Fixed(), CandidatePort)


# =========================================================== Story 2.3: generate


def test_period_vocabulary_is_stripped_before_scoring() -> None:
    """R-158: a period phrase changes *when* a question asks about, never *what*.

    The words asserted gone are the ones that carry the *period*. ``over`` is left in
    deliberately and is not asserted either way: it occurs in nine published surfaces, so
    removing it would strip content from a name, and R-158 licenses removing what says
    when -- not every preposition that happens to stand near it.
    """
    subject = subject_of("inflation over the last 5 years")
    assert "inflation" in subject.words
    for word in ("last", "years", "5", "the"):
        assert word not in subject.words, f"{word!r} says when, not what"


def test_the_stripping_list_is_the_binders_own_list() -> None:
    """R-158 and R-162: the same reviewed vocabulary, not a second copy beside it.

    Asserted by identity of *content* against ``compile.lexicon``, because a second list
    that happened to agree today is exactly the thing that drifts.
    """
    from askai.compile.lexicon import latest_words, relative_back_words

    vocabulary = period_vocabulary()
    assert set(latest_words()) <= vocabulary
    assert set(relative_back_words()) <= vocabulary


def test_a_qatarization_indicator_does_not_rank_on_span_words() -> None:
    """Story 2.3's own worked example, as a property of the subject rather than a ranking.

    The failure it describes is the span words *reaching a candidate at all*. Once they
    are gone from the subject they cannot score, so the assertion is that none of the
    period words survives to be matched against a surface.
    """
    subject = subject_of("inflation over the last 5 years")
    assert set(subject.words) <= {"inflation", "over"}


def test_no_published_name_is_stripped_down_to_nothing() -> None:
    """The invariant that broke ``ambig-en-003``, asserted over the whole corpus.

    Function words like ``of`` and ``the`` *do* occur inside published names and stripping
    them is harmless -- they occur in nearly every name, so they discriminate nothing. What
    is not harmless is stripping a name's **content**, which is what an earlier vocabulary
    containing ``number`` and ``value`` did to *Number of Jobs in the Sector*.

    The checkable form of that is this: a reader who types a published name exactly must
    still have a subject left after stripping. A framing list that ate a name's content
    would leave one of the 1,101 published surfaces with nothing to score.
    """
    export = CmsExport.rooted(EXPORT_ROOT)
    eaten = [
        row.text
        for row in name_rows(export)
        if subject_of(row.text).was_all_framing
    ]
    assert not eaten, (
        "these published surfaces strip to nothing, so a reader typing one exactly has "
        f"no subject left to score: {eaten[:5]}"
    )


def test_a_published_name_keeps_its_content_words_through_stripping() -> None:
    """``ambig-en-003`` itself, named, because it is the case that caught the defect."""
    subject = subject_of("Number of Jobs in the Sector")
    assert "number" in subject.words, "the earlier vocabulary removed this and broke the case"
    assert "jobs" in subject.words
    assert "sector" in subject.words


def test_an_all_framing_question_keeps_its_words_rather_than_scoring_nothing() -> None:
    """Scoring an empty subject returns an arbitrary slice of the collection."""
    subject = subject_of("what is it?")
    assert subject.was_all_framing
    assert subject.text, "an empty subject would be scored against every row equally"


def test_a_multi_word_period_phrase_is_removed_whole() -> None:
    """Removing "most recent" word by word leaves "most" to compete for salience."""
    assert subject_of("most recent inflation").text == "inflation"


def test_the_gate_is_structural_and_refuses_a_shared_short_word() -> None:
    """Story 2.3: *"Obesity Rate"* is not admitted for *"what is the unemployment rate"*.

    Both contain "rate". The gate is four characters of *content*, so the shared "rate"
    is not enough on its own -- and this is the epic's own counter-example.
    """
    subject = subject_of("what is the unemployment rate")
    obesity = _candidate("obesity", surfaces=("obesity rate",))
    unemployment = _candidate("unemployment", surfaces=("unemployment rate",))
    assert admits(subject, unemployment)
    assert not admits(subject, obesity), (
        "'rate' is shared framing-adjacent content; admitting on it alone is the "
        "failure the structural gate exists to prevent"
    )


def test_the_gate_admits_a_surface_shorter_than_one_run() -> None:
    """A two-character name cannot share a four-character run with anything.

    Refusing it would make the gate an unreachability rule for short names rather than a
    relevance test, which is a different thing from what it was reviewed to be.
    """
    subject = subject_of("gdp deflator")
    assert admits(subject, _candidate("short", surfaces=("gp",)))


def test_ngrams_are_taken_within_words_not_across_them() -> None:
    """A run spanning a space is an artefact of word order, not shared content."""
    size = minimum_ngram()
    assert content_ngrams("real gdp", size) == content_ngrams("gdp real", size)


def test_generation_calls_no_model_and_applies_no_threshold() -> None:
    """AD-25 stage 1: high recall, structural gate only.

    A candidate scoring almost nothing still reaches stage 2 provided it shares content:
    dropping it here would be a score threshold, which Story 2.13 measured as unable to
    separate right from wrong.
    """
    subject = subject_of("gross domestic product")
    faint = _candidate("faint", score=0.0001, surfaces=("gross domestic product",))
    assert generate(subject, _Fixed(faint)) == (faint,)


# =========================================================== Story 2.4: discriminate


def test_a_named_grain_removes_a_candidate_rather_than_ranking_it_lower() -> None:
    """Story 2.4 and FR-6: *"a yearly-only detail is out, not merely ranked lower"*.

    The vetoed candidate is given every other advantage -- the named sector, the named
    country, the matching unit shape, the best similarity -- so an implementation that
    weighted grain heavily instead of vetoing it would still rank it first.
    """
    yearly_only = _candidate(
        "yearly-only",
        score=99.0,
        surfaces=("tourism receipts",),
        periods=("2024", "2023"),
        countries=("QA-BENCH",),
        unit=UnitShape.AMOUNT,
        entities=("tourism",),
    )
    monthly = _candidate("monthly", score=0.1, periods=("2024-01",))
    asked = QuestionSignals(
        grain=Grain.MONTHLY, subject=subject_of("tourism receipts in Tourism")
    )

    result = discriminate((yearly_only, monthly), asked)

    assert [entry.candidate.detail_id for entry in result.vetoed] == ["yearly-only"]
    assert all(entry.by is SignalName.GRAIN for entry in result.vetoed)
    assert [scored.candidate.detail_id for scored in result.survivors] == ["monthly"]


def test_period_coverage_removes_a_candidate_publishing_nothing_in_the_window() -> None:
    """*"a chart of the national GDP from 2022 to 2025"* -- which publish that span."""
    covering = _candidate("covers", periods=("2022", "2023", "2024", "2025"))
    elsewhere = _candidate("elsewhere", periods=("2015", "2016"))
    asked = QuestionSignals(
        grain=Grain.YEARLY,
        window=window_for(Range(start=Period("2022"), end=Period("2025"))),
        subject=subject_of("a chart of GDP from 2022 to 2025"),
    )

    result = discriminate((covering, elsewhere), asked)

    assert [scored.candidate.detail_id for scored in result.survivors] == ["covers"]
    assert [entry.candidate.detail_id for entry in result.vetoed] == ["elsewhere"]


def test_a_gap_inside_the_window_does_not_veto() -> None:
    """A detail with one missing year can still answer, with the gap noted downstream.

    The veto is for "cannot answer this as asked at all", not for "answers it
    incompletely" -- which is a completeness question and not the resolver's to decide.
    """
    gapped = _candidate("gapped", periods=("2022", "2025"))
    asked = QuestionSignals(
        grain=Grain.YEARLY,
        window=window_for(Range(start=Period("2022"), end=Period("2025"))),
        subject=subject_of("gdp from 2022 to 2025"),
    )
    assert discriminate((gapped,), asked).survivors[0].candidate is gapped


def test_a_deferred_period_produces_no_window_and_vetoes_nothing() -> None:
    """``Latest`` is deferred (AD-1): which period it names is a fact about the rows.

    Expanding it here would veto candidates for failing a test nobody could pass, and it
    is the commonest question there is.
    """
    assert window_for(Latest()) is None
    assert window_for(LastN(n=5, grain=Grain.YEARLY)) is None
    assert window_for(Exact(period=Period("2024"))) is not None


def test_a_named_sector_separates_details_sharing_one_name() -> None:
    """Story 2.4's ``Sector Contribution To GDP``, which eight sectors publish.

    Only the entity tells them apart, which is why it carries the most weight of the four.
    """
    shared = ("sector contribution to gdp",)
    tourism = _candidate("tourism-detail", surfaces=shared, entities=("tourism",))
    health = _candidate("health-detail", surfaces=shared, entities=("health and social services",))
    asked = QuestionSignals(subject=subject_of("tourism sector contribution to GDP"))

    result = discriminate((health, tourism), asked)

    assert result.survivors[0].candidate.detail_id == "tourism-detail"
    assert SignalName.ENTITY in result.survivors[0].spoke


def test_naming_no_sector_leaves_the_eight_unseparated() -> None:
    """Story 2.4: it *"does not resolve it, and it proceeds to disambiguation"*.

    Every one of the eight scores identically, so the stage returns all of them rather
    than breaking a tie it has no evidence to break.
    """
    eight = tuple(
        _candidate(
            f"sector-{n}",
            surfaces=("sector contribution to gdp",),
            entities=(f"sector {n}",),
        )
        for n in range(8)
    )
    asked = QuestionSignals(subject=subject_of("sector contribution to GDP"))

    result = discriminate(eight, asked)

    assert len(result.survivors) == 8
    assert len({scored.score for scored in result.survivors}) == 1, (
        "no signal separates them, so no score may"
    )


def test_an_empty_benchmark_set_is_silent_rather_than_disagreeing() -> None:
    """Only 21 of 289 details declare one. Reading absence as "does not match this
    country" would eliminate 268 details on any question naming one."""
    declares_none = _candidate("no-benchmarks")
    asked = QuestionSignals(countries=frozenset({"FR"}), subject=subject_of("gdp in France"))

    scored = discriminate((declares_none,), asked).survivors[0]

    country = next(s for s in scored.signals if s.name is SignalName.COUNTRY)
    assert not country.spoke
    assert country.contribution == 0.0


def test_an_unknown_unit_shape_neither_rules_in_nor_out() -> None:
    """54 details publish the unit ``NA``; the publisher recorded no shape for them."""
    unknown = _candidate("na-unit", unit=UnitShape.UNKNOWN)
    asked = QuestionSignals(subject=subject_of("what share of gdp"))

    scored = discriminate((unknown,), asked).survivors[0]

    unit = next(s for s in scored.signals if s.name is SignalName.UNIT_SHAPE)
    assert not unit.spoke


def test_a_question_naming_two_shapes_names_neither() -> None:
    """*"what share of the total"* holds a share word and an amount word.

    Guessing between them makes the signal fire on a coin toss, so it goes silent.
    """
    share = _candidate("share", unit=UnitShape.SHARE)
    asked = QuestionSignals(subject=subject_of("what share of the total"))

    scored = discriminate((share,), asked).survivors[0]

    unit = next(s for s in scored.signals if s.name is SignalName.UNIT_SHAPE)
    assert not unit.spoke


def test_unit_shape_prefers_the_shape_the_reader_asked_for() -> None:
    """Amount against share against rank -- *how much*, *what share*, *where do we rank*."""
    amount = _candidate("amount", surfaces=("gdp",), unit=UnitShape.AMOUNT)
    share = _candidate("share", surfaces=("gdp",), unit=UnitShape.SHARE)
    asked = QuestionSignals(subject=subject_of("where do we rank on gdp"))
    ranked = _candidate("rank", surfaces=("gdp",), unit=UnitShape.RANK)

    result = discriminate((amount, share, ranked), asked)

    assert result.survivors[0].candidate.detail_id == "rank"


def test_discrimination_never_re_ranks_on_the_generation_score() -> None:
    """The measurement that put this stage here: score cannot carry the distinction.

    The structural evidence is set *against* the similarity, so an implementation that
    consults ``score`` at all cannot produce this ordering.
    """
    best_score_no_facts = _candidate("loud", score=1000.0, surfaces=("tourism receipts",))
    worst_score_all_facts = _candidate(
        "quiet",
        score=0.0001,
        surfaces=("tourism receipts",),
        unit=UnitShape.AMOUNT,
        entities=("tourism",),
    )
    asked = QuestionSignals(subject=subject_of("total tourism receipts for the tourism sector"))

    result = discriminate((best_score_no_facts, worst_score_all_facts), asked)

    assert result.survivors[0].candidate.detail_id == "quiet"


def test_the_same_candidates_discriminate_identically_on_every_run() -> None:
    """NFR-1 and AD-17: the same question resolves to the same candidate every time."""
    candidates = tuple(_candidate(f"d{n}", surfaces=("gross domestic product",)) for n in range(6))
    asked = QuestionSignals(subject=subject_of("gross domestic product"))
    once = discriminate(candidates, asked)
    again = discriminate(candidates, asked)
    assert [s.candidate.detail_id for s in once.survivors] == [
        s.candidate.detail_id for s in again.survivors
    ]


def test_stage_one_order_is_the_tie_break_when_no_signal_separates() -> None:
    """Stage 2 refines stage 1; where it has no evidence it changes nothing.

    Reversing the candidate list legitimately reverses the result, and that is the
    property rather than a violation of determinism: stage 1's ranking is *input*, and it
    is the ranking measured at 96% recall@1 on exactly-typed names. Ordering by
    ``detail_id`` instead -- an accident of the export -- was measured dropping exact
    recall@1 to 80.0% and the overall figure from 73.2% to 63.4%.
    """
    candidates = tuple(_candidate(f"d{n}", surfaces=("gross domestic product",)) for n in range(4))
    asked = QuestionSignals(subject=subject_of("gross domestic product"))

    forward = discriminate(candidates, asked)
    backward = discriminate(tuple(reversed(candidates)), asked)

    assert [s.candidate.detail_id for s in forward.survivors] == ["d0", "d1", "d2", "d3"]
    assert [s.candidate.detail_id for s in backward.survivors] == ["d3", "d2", "d1", "d0"]


def test_a_signal_true_of_every_candidate_separates_nothing() -> None:
    """The rule that makes the stage deserve its name.

    A question about medical tourism reaches candidates that are *all* in the Tourism
    sector. "Names the sector" is then true of all of them and tells none of them apart,
    and letting it contribute hands the ordering to whatever is left -- which is the
    lightest and least reliable signal there is. Measured over ``names-v1``: this cost
    ``exact-ar-021`` and ``exact-ar-023`` their rank-one answers.
    """
    all_tourism = tuple(
        _candidate(f"t{n}", surfaces=("visitor nights",), entities=("tourism",))
        for n in range(3)
    )
    asked = QuestionSignals(subject=subject_of("tourism visitor nights"))

    result = discriminate(all_tourism, asked)

    assert SignalName.ENTITY not in result.survivors[0].separating
    assert all(SignalName.ENTITY not in scored.spoke for scored in result.survivors)


def test_a_signal_true_of_only_some_candidates_does_separate() -> None:
    """The other half of the rule, or it would just be a way of ignoring evidence."""
    mixed = (
        _candidate("other", surfaces=("visitor nights",), entities=("health",)),
        _candidate("tourism", surfaces=("visitor nights",), entities=("tourism",)),
    )
    asked = QuestionSignals(subject=subject_of("tourism visitor nights"))

    result = discriminate(mixed, asked)

    assert result.survivors[0].candidate.detail_id == "tourism"
    assert SignalName.ENTITY in result.survivors[0].separating


def test_stage_two_runs_with_no_model_reachable() -> None:
    """NFR-5, asserted structurally: nothing in the ladder imports a model.

    A test that took a model away would be testing a fallback. There is nothing to take
    away, and that is the stronger statement.
    """
    import askai.compile.resolve as package

    for module in _modules_under(Path(str(package.__path__[0]))):
        text = module.read_text(encoding="utf-8")
        assert "ports.model" not in text and "adapters.model" not in text, (
            f"{module.name} reaches a model; AD-25 stage 1 and 2 run without one"
        )


def _modules_under(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.py"))


# =========================================================== Story 2.5: decide


def test_exactly_one_survivor_binds_as_the_detail() -> None:
    """FR-1: it binds as the resolved **detail**, not an indicator and not a substring."""
    alone = _candidate("the-one", surfaces=("gross domestic product",), entities=("economy",))
    asked = QuestionSignals(subject=subject_of("gross domestic product for the economy"))

    outcome = decide(discriminate((alone,), asked))

    assert isinstance(outcome, Resolved)
    assert outcome.detail_id == "the-one"


def test_several_survivors_become_a_disambiguation_naming_them() -> None:
    """FR-2, and a *primary* path: the outcome has no bound detail to reach at all."""
    pair = (
        _candidate("first", surfaces=("total expenditure",)),
        _candidate("second", surfaces=("total expenditure",)),
    )
    asked = QuestionSignals(subject=subject_of("total expenditure"))

    outcome = decide(discriminate(pair, asked))

    assert isinstance(outcome, Disambiguation)
    assert {offered.detail_id for offered in outcome.candidates} == {"first", "second"}
    assert not hasattr(outcome, "detail_id"), (
        "a disambiguation that also carries a chosen detail is a silent pick"
    )


def test_the_ambiguity_threshold_is_a_rule_and_carries_its_labelled_set() -> None:
    """FR-2 requires both: reviewable in ``rules/``, and recording where it came from."""
    assert 0.0 < ambiguity_margin() < 1.0
    assert margin_labelled_set() == "names-v1"


def test_a_leader_clear_by_the_margin_binds_alone() -> None:
    """The margin is what separates "one answer" from "a question"."""
    clear = _candidate("clear", surfaces=("tourism receipts",), entities=("tourism",))
    behind = _candidate("behind", surfaces=("tourism receipts",))
    asked = QuestionSignals(subject=subject_of("tourism receipts tourism"))

    outcome = decide(discriminate((clear, behind), asked))

    assert isinstance(outcome, Resolved)
    assert outcome.detail_id == "clear"


def test_no_candidate_at_all_is_refused_with_a_stated_cause() -> None:
    """FR-38: a refusal states *which* cause."""
    outcome = decide(discriminate((), QuestionSignals()))
    assert isinstance(outcome, Refusal)
    assert outcome.cause is RefusalCause.NOTHING_MATCHED


def test_every_candidate_ruled_out_is_a_different_refusal_from_nothing_matching() -> None:
    """*"I hold nothing like that"* and *"it does not publish that"* are different facts.

    The second is much the more useful, and collapsing them is the silent failure AD-15
    exists to prevent.
    """
    wrong_grain = _candidate("wrong-grain", periods=("2024",))
    asked = QuestionSignals(grain=Grain.MONTHLY, subject=subject_of("gdp monthly"))

    outcome = decide(discriminate((wrong_grain,), asked))

    assert isinstance(outcome, Refusal)
    assert outcome.cause is RefusalCause.ALL_CANDIDATES_RULED_OUT
    assert SignalName.GRAIN in outcome.vetoed_by


def test_a_tie_wider_than_a_closed_question_is_reported_not_truncated() -> None:
    """Eight details named *Sector Contribution To GDP*; offering all eight restates
    the problem rather than helping."""
    many = tuple(
        _candidate(f"d{n}", surfaces=("sector contribution to gdp",))
        for n in range(maximum_offered() + 2)
    )
    asked = QuestionSignals(subject=subject_of("sector contribution to GDP"))

    outcome = decide(discriminate(many, asked))

    assert isinstance(outcome, Refusal)
    assert outcome.cause is RefusalCause.TOO_MANY_TO_NAME


def test_all_scores_zero_disambiguates_rather_than_binding_the_first() -> None:
    """When no signal spoke, every survivor is equally unseparated.

    A relative margin against a zero leader is meaningless, and binding whichever sorted
    first would make an arbitrary pick look like a decision.
    """
    pair = (_candidate("aaa", surfaces=("xxxx",)), _candidate("bbb", surfaces=("xxxx",)))
    asked = QuestionSignals(subject=subject_of("yyyy"))

    outcome = decide(discriminate(pair, asked))

    assert isinstance(outcome, Disambiguation)


# =========================================================== the ladder, end to end


def test_the_ladder_runs_all_three_stages_in_order() -> None:
    """One entry point, so no caller can reach stage 3 with raw candidates."""
    port = _Fixed(
        _candidate("gdp", surfaces=("gross domestic product",), entities=("economy",)),
    )
    outcome = resolve("what is the gross domestic product", port)
    assert isinstance(outcome, Resolved)
    assert outcome.detail_id == "gdp"


def test_the_ladder_is_deterministic(
) -> None:
    """NFR-1: the same question resolves to the same candidate on every run."""
    port = _Fixed(
        _candidate("a", surfaces=("gross domestic product",)),
        _candidate("b", surfaces=("gross domestic product",)),
    )
    first = resolve("gross domestic product", port)
    second = resolve("gross domestic product", port)
    assert type(first) is type(second)
    assert isinstance(first, Disambiguation) and isinstance(second, Disambiguation)
    assert [c.detail_id for c in first.candidates] == [c.detail_id for c in second.candidates]


# =========================================================== the reviewed unit table


def test_every_published_unit_the_table_names_exists_in_the_export() -> None:
    """A unit absent from the export is a row nobody reviewed against anything."""
    export = CmsExport.rooted(EXPORT_ROOT)
    published = {fold_unit(row.get("UnitEN", "")) for row in export.published_details()}
    missing = {unit for unit in unit_shapes() if unit and unit not in published}
    assert not missing, f"the shape table names units the export does not publish: {missing}"


def test_the_percent_unit_survives_folding_and_is_a_share() -> None:
    """The commonest unit in the export, and the one the engine's prose fold destroys.

    ``normalise()`` collapses punctuation, so ``%`` folds to the empty string -- and ``%``
    is the published unit of 63 details. Keying the shape table on a prose fold would make
    the single commonest unit unclassifiable while looking entirely correct.
    """
    from askai.domain.normalise import normalise

    assert normalise("%") == "", "the prose fold destroys it; that is why fold_unit exists"
    shapes = unit_shapes()
    assert shapes[fold_unit("%")] is UnitShape.SHARE
    assert shapes[fold_unit("Rank")] is UnitShape.RANK
    assert shapes[fold_unit("bn QAR")] is UnitShape.AMOUNT


def test_unit_folding_keeps_symbols_that_distinguish_two_units() -> None:
    """``MT/ha`` and ``M3/MT`` are different units and differ only by punctuation."""
    assert fold_unit("MT/ha") != fold_unit("M3/MT")
    assert fold_unit("bn QAR") == fold_unit("  BN   qar ")


# =========================================================== against the real corpus


@pytest.fixture(scope="module")
def published_candidates(tmp_path_factory: pytest.TempPathFactory) -> IndexCandidates:
    """The whole published corpus, built once: stage 1 against real data."""
    export = CmsExport.rooted(EXPORT_ROOT)
    source = TrigramVectorSource()
    directory = tmp_path_factory.mktemp("resolve-corpus")
    path = build_generation(
        directory,
        {Collection.NAMES: name_rows(export)},
        source,
        built_at=BUILT_AT,
        facts=detail_facts(export),
    )
    return IndexCandidates.over(load_generation(path, source))


def test_candidates_carry_their_facts_from_the_same_generation(
    published_candidates: IndexCandidates,
) -> None:
    """AD-13 and AD-20, extended to discrimination: one generation, one set of facts."""
    found = published_candidates.candidates("gross domestic product")
    assert found, "the published corpus reaches something for GDP"
    with_periods = [c for c in found if c.facts.periods]
    assert with_periods, "a real candidate publishes periods, and the facts travel with it"
    assert all(isinstance(period, Period) for period in with_periods[0].facts.periods)


def test_a_real_candidate_carries_a_unit_shape_and_an_entity(
    published_candidates: IndexCandidates,
) -> None:
    """The two signals that do the most work, present on the real corpus rather than
    only on hand-built values."""
    found = published_candidates.candidates("gross domestic product")
    assert any(c.facts.unit_shape is not UnitShape.UNKNOWN for c in found)
    assert any(c.facts.entity_names for c in found)


def test_the_facts_hold_no_published_value(
    published_candidates: IndexCandidates,
) -> None:
    """The port's central promise: coverage, never content.

    Asserted on the type rather than by inspecting numbers -- ``CandidateFacts`` has no
    field that could hold a figure, so there is nowhere for one to be.
    """
    from dataclasses import fields

    names = {field.name for field in fields(CandidateFacts)}
    assert names == {
        "periods",
        "benchmark_countries",
        "unit_shape",
        "entity_names",
        "classification",
    }, "a field added here could carry a figure into the stage that picks the indicator"
