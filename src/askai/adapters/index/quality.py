"""``python -m askai.adapters.index`` -- run the retrieval harness and report.

Purity: IO.

The command AD-30's gate is made of. It builds one generation over the published export,
searches it with every pair in the labelled set, and prints what came back: recall at 1,
5 and 10 -- overall, by the kind of naming each question uses, and by language -- the
score distributions, and the floor and relative cut those distributions support.

It runs on a laptop with no model, because the vector source it measures is whichever one
is handed to :func:`report_for`; the shipped trigram source needs nothing but the export.
The same call against an embedding-backed source is the comparison the decision gets made
on, and neither this module nor anything it calls knows which it has.

**No flags, and no environment.** The command takes the labelled set and the export from
the two paths below, relative to the repository root it is run from, and everything else
is a function argument. That is partly NFR-4's import rule -- this package reaches the
standard library and this project, and an argument parser is neither -- and partly that a
harness whose behaviour depends on how it was invoked is a harness whose two runs cannot
be compared.

It prints the rule clauses it supports and does not write them. AD-11 makes a rule file a
reviewed artefact, and a command that edited one would turn a measurement into a
deployment.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from askai.adapters.index.build import build_generation
from askai.adapters.index.evaluation import (
    Derivation,
    LadderReport,
    QualityReport,
    as_percent,
    derive_floor,
    derive_relative_cut,
    evaluate,
    evaluate_ladder,
    percentile,
)
from askai.adapters.index.facts import detail_facts
from askai.adapters.index.floors import CUT_RULE, FLOOR_RULE, derivation_criterion
from askai.adapters.index.generation import load_generation
from askai.adapters.index.labelled import LabelKind, LabelledSet, load_labelled_set
from askai.adapters.index.names import name_rows
from askai.adapters.index.namesearch import NamesIndex
from askai.adapters.index.resolution import IndexCandidates
from askai.adapters.index.tuning import candidate_limit
from askai.adapters.index.vectors import TrigramVectorSource
from askai.adapters.readmodel.export import CmsExport
from askai.messages.lang import Lang
from askai.ports.index import Collection
from askai.ports.vectors import VectorSourcePort

__all__ = [
    "EXPORT_ROOT",
    "LABELLED_ROOT",
    "Measured",
    "main",
    "render",
    "render_derivation",
    "report_for",
]

#: Where the labelled set and the export live, relative to the repository root the
#: command is run from. Arguments override both; neither is read from the environment.
LABELLED_ROOT: Final = Path("labelled") / "names"
EXPORT_ROOT: Final = Path("data")

_RANKS: Final = (1, 5, 10)
_QUANTILES: Final = (0.05, 0.25, 0.5, 0.75, 0.95)
_WORKSPACE: Final = ".names-quality-"


@dataclass(frozen=True, slots=True)
class Measured:
    """One run of the harness: what was measured, and what it supports."""

    labelled: LabelledSet
    report: QualityReport
    floor: Derivation
    cut: Derivation

    #: What AD-25's three stages achieve over the same set. Reported beside the generation
    #: numbers rather than instead of them, because they answer different questions: the
    #: first is the ceiling a vector source imposes, the second is what the answer path
    #: actually returns. A harness reporting only the first describes a path nothing takes.
    ladder: LadderReport


def report_for(
    labelled: LabelledSet,
    export: CmsExport,
    source: VectorSourcePort,
    *,
    workspace: Path,
    limit: int | None = None,
) -> Measured:
    """Build a generation over *export* with *source*, and measure *labelled* against it.

    The generation is built under *workspace* rather than reused from wherever one
    happens to be published: the harness measures a vector source, and a generation built
    on some earlier day by some other source is not that. The caller owns the directory,
    so a failed run leaves the evidence behind rather than deleting it.
    """
    depth = candidate_limit() if limit is None else limit
    # The facts are built even though this harness measures *generation* alone: a
    # generation without them is a different file shape, and measuring one shape while
    # shipping another is how a harness stops describing the thing it is run against.
    path = build_generation(
        workspace,
        {Collection.NAMES: name_rows(export)},
        source,
        facts=detail_facts(export),
    )
    generation = load_generation(path, source)
    report = evaluate(NamesIndex(generation), labelled, limit=depth)
    ladder = evaluate_ladder(IndexCandidates.over(generation), labelled, limit=depth)
    high_share, false_negative_budget, false_positive_budget = derivation_criterion()
    return Measured(
        labelled=labelled,
        report=report,
        ladder=ladder,
        floor=derive_floor(
            report,
            high_share=high_share,
            false_negative_budget=false_negative_budget,
            false_positive_budget=false_positive_budget,
        ),
        cut=derive_relative_cut(
            report,
            high_share=high_share,
            false_negative_budget=false_negative_budget,
            false_positive_budget=false_positive_budget,
        ),
    )


def _percent(value: float) -> str:
    return f"{value * 100:5.1f}%"


def _say(line: str, out: TextIO | None) -> None:
    """Print to *out*, or to wherever ``print`` goes when there is none."""
    if out is None:
        print(line)
    else:
        print(line, file=out)


def render(measured: Measured, out: TextIO | None = None) -> None:
    """Print the whole measurement: recall, distributions, and the derived thresholds."""
    report = measured.report
    _say(f"labelled set   {report.labelled_identity}  ({len(measured.labelled)} cases)", out)
    _say(f"vector source  {report.source_identity}", out)
    _say(f"candidates     {report.limit} per question", out)
    _say("", out)

    _say("recall over candidate generation", out)
    header = "  ".join(f"@{rank:<5}" for rank in _RANKS)
    _say(f"  {'kind':<12} {'cases':>5}   {header}", out)
    positives = len(measured.labelled.positives)
    overall = "  ".join(_percent(report.recall_at(rank)) for rank in _RANKS)
    _say(f"  {'all':<12} {positives:>5}   {overall}", out)
    for kind in LabelKind:
        if kind is LabelKind.NONE or not report.counted(kind):
            continue
        rates = "  ".join(_percent(report.recall_at_for(rank, kind)) for rank in _RANKS)
        _say(f"  {kind.value:<12} {report.counted(kind):>5}   {rates}", out)
    for lang in Lang:
        if not report.counted_in(lang):
            continue
        rates = "  ".join(_percent(report.recall_at_in(rank, lang)) for rank in _RANKS)
        _say(f"  {lang.value:<12} {report.counted_in(lang):>5}   {rates}", out)
    _say("", out)

    _say("score distributions", out)
    _distribution("relevant", report.relevant_scores, out)
    _distribution("irrelevant", report.irrelevant_scores, out)
    _distribution("displacing", report.displacing_scores, out)
    _say(f"  negatives already returning nothing  {_percent(report.empty_negatives)}", out)
    _say("", out)

    _derivation("floor", measured.floor, out)
    _derivation("relative cut", measured.cut, out)
    _say("", out)
    _ladder(measured.ladder, out)


def _ladder(ladder: LadderReport, out: TextIO | None) -> None:
    """AD-25's three stages over the same set: the ceiling, and what is made of it.

    ``gen@10`` is the ceiling stage 1 imposes on everything downstream. ``disc@1`` is what
    stage 2 converts it into. Reading them together is the only way to tell a vector source
    that found the answer from a discriminator that picked it out.
    """
    _say("the resolution ladder (AD-25 stages 1-3, no model)", out)
    _say(f"  {'kind':<12} {'cases':>5}   {'gen@1':>7} {'gen@10':>7}   {'disc@1':>7}", out)
    _say(
        f"  {'all':<12} {ladder.counted():>5}   "
        f"{_percent(ladder.generated_at(1))} {_percent(ladder.generated_at(10))}   "
        f"{_percent(ladder.discriminated_at(1))}",
        out,
    )
    for kind in LabelKind:
        if kind is LabelKind.NONE or not ladder.counted(kind):
            continue
        _say(
            f"  {kind.value:<12} {ladder.counted(kind):>5}   "
            f"{_percent(ladder.generated_at(1, kind))} "
            f"{_percent(ladder.generated_at(10, kind))}   "
            f"{_percent(ladder.discriminated_at(1, kind))}",
            out,
        )
    _say("", out)
    total = ladder.counted()
    outcomes = "   ".join(
        f"{name} {count} ({_percent(count / total if total else 0.0).strip()})"
        for name, count in ladder.outcomes()
    )
    _say(f"  stage 3 over the positives    {outcomes}", out)
    _say(f"  reader reaches the answer     {_percent(ladder.reached())}", out)
    negatives = ladder.negative_outcomes()
    if negatives:
        spelled = "   ".join(f"{name} {count}" for name, count in negatives)
        _say(f"  over the {ladder.negatives} negatives      {spelled}", out)
        _say(
            "    `bound` is the one to read: a question this corpus cannot answer, "
            "answered confidently.",
            out,
        )


def _distribution(name: str, values: Sequence[float], out: TextIO | None) -> None:
    if not values:
        _say(f"  {name:<12} no observations", out)
        return
    quantiles = "  ".join(
        f"p{int(share * 100):02d} {percentile(values, share):.3f}" for share in _QUANTILES
    )
    _say(f"  {name:<12} n={len(values):<4} {quantiles}", out)


def _derivation(name: str, derivation: Derivation, out: TextIO | None) -> None:
    verdict = "sufficient" if derivation.sufficient else "INSUFFICIENT -- overlap is material"
    _say(f"derived {name}: {derivation.value:.3f}  ({verdict})", out)
    _say(
        f"  separation {derivation.separation:+.3f}"
        f"   discards {_percent(derivation.false_negative_rate)} of relevant"
        f"   admits {_percent(derivation.false_positive_rate)} of irrelevant"
        f"   (n={derivation.relevant}/{derivation.irrelevant})",
        out,
    )


def render_derivation(measured: Measured, today: str, out: TextIO | None = None) -> None:
    """Print the rule clauses this measurement supports, for review and for pasting."""
    report = measured.report
    for rule_id, key, derivation in (
        (FLOOR_RULE, "floor_percent", measured.floor),
        (CUT_RULE, "relative_cut_percent", measured.cut),
    ):
        _say(f"  - id: {rule_id}", out)
        _say("    values:", out)
        _say(f"      {key}: {as_percent(derivation.value)}", out)
        _say(f"      labelled_set: {report.labelled_identity}", out)
        _say(f"      vector_source_identity: {report.source_identity}", out)
        _say(f'      derived_on: "{today}"', out)
        _say(f"      separation_percent: {as_percent(derivation.separation)}", out)
        _say(f"      discards_relevant_percent: {as_percent(derivation.false_negative_rate)}", out)
        _say(f"      admits_irrelevant_percent: {as_percent(derivation.false_positive_rate)}", out)
        _say(f"      relevant_observations: {derivation.relevant}", out)
        _say(f"      irrelevant_observations: {derivation.irrelevant}", out)
        _say(f"      sufficient: {str(derivation.sufficient).lower()}", out)


def _discard(workspace: Path) -> None:
    """Remove the generation and the directory it was built in, if both are still there.

    A generation is one file by construction (``build.py`` keeps it out of WAL precisely
    so that it is), so this is an unlink and an rmdir rather than a recursive delete --
    and an rmdir refuses a directory holding anything the harness did not put there.
    """
    if not workspace.is_dir():
        return
    for path in workspace.iterdir():
        path.unlink(missing_ok=True)
    workspace.rmdir()


def main(
    labelled_root: Path | None = None,
    export_root: Path | None = None,
    out: TextIO | None = None,
    *,
    today: str = "",
) -> int:
    """Measure the shipped vector source and print the report. Non-zero if it cannot.

    The paths default to the repository layout; they are arguments so that a test can
    point the harness at a set of its own, and so that nothing here reads an environment.
    """
    labelled_path = LABELLED_ROOT if labelled_root is None else labelled_root
    export_path = EXPORT_ROOT if export_root is None else export_root
    workspace = Path(f"{_WORKSPACE}{uuid.uuid4().hex}")
    try:
        labelled = load_labelled_set(labelled_path)
        measured = report_for(
            labelled,
            CmsExport.rooted(export_path),
            TrigramVectorSource(),
            workspace=workspace,
        )
    except (OSError, RuntimeError) as error:
        _say(f"{error}", out)
        return 1
    finally:
        _discard(workspace)
    render(measured, out)
    _say("", out)
    render_derivation(measured, today, out)
    return 0
