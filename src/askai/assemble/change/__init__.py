"""Figures over time: a series, a change, a comparison, a target.

Purity: pure.

A subpackage rather than four modules in ``assemble/`` because three sessions are adding
composers at once and the directory is what keeps them out of each other's way. What is
here is Epic 3's half: the compositions that answer about *movement* rather than about a
single reading.

Four guarantees live in this subpackage and nowhere else.

* **A published change is selected, never recomputed** (AD-4, FR-19, DATA-CONTRACT FACT
  2). ``selection.py`` picks the column matching ``(grain x basis)``; a change is computed
  only where no column matches, and a computed one is classed ``derived`` and states its
  inputs. The two are separate types, so an element classed ``measured`` cannot carry a
  computed change -- there is no constructor that would let it.
* **Percent and percentage points never convert** (FR-21, AD-4). The quantity is decided
  by the detail's published unit and by the selected column's declared flavour, never by
  the value's magnitude, and nothing in this package constructs either type -- the one
  constructor is ``domain/change.py``, which ``tests/test_assemble.py`` scans to keep true.
* **A gap is stated, never skipped** (FR-17, FR-45). ``series.py`` builds the run a span
  *ought* to contain from the span alone and matches the rows against it, so a missing
  quarter is an element of class ``absent`` naming the period rather than a period that
  quietly is not there.
* **A change names its basis and both periods** (FR-20, R-167, R-168). The composer reads
  ``R-CHANGE-CARRIES-BASIS-AND-PERIODS`` and refuses to build an element that would breach
  it, which is what makes an unlabelled growth figure a failing test rather than a
  cosmetic one.

No module here names a ``FormatMode`` or a ``Lens``: a composer holds a ``Role`` and asks
``Placement``. No module here writes a numeral: every figure goes through the single
``Formatter``. Both are asserted as scans over the whole of ``assemble/``.
"""

from __future__ import annotations

from askai.assemble.change.compare import (
    CompareMessage,
    ComparisonDimension,
    ComparisonError,
    PeriodComparison,
    compare_periods,
    comparison_dimension,
    named_periods,
)
from askai.assemble.change.delta import (
    ChangeComposition,
    ChangeMessage,
    ChangeRefusal,
    ComposedChange,
    NoChangePublished,
    UnlabelledChange,
    basis_words,
    change_composition,
    no_change_published,
)
from askai.assemble.change.selection import (
    Change,
    ChangeClause,
    ChangeRule,
    ChangeTableError,
    ChangeTables,
    ComputedChange,
    PublishedChange,
    SelectedChange,
    column_identity,
    compute_change,
    paired_with,
    select_change,
)
from askai.assemble.change.series import (
    ComposedSeries,
    NotASeries,
    PlacedPoint,
    Series,
    SeriesClause,
    SeriesComposition,
    SeriesError,
    SeriesMessage,
    SeriesPoint,
    SeriesRefusal,
    SeriesRule,
    SeriesTables,
    series_composition,
    series_over,
)
from askai.assemble.change.targets import (
    ComposedDeclared,
    DeclaredTarget,
    NotPublished,
    TargetClause,
    TargetComposition,
    TargetError,
    TargetMessage,
    TargetRule,
    TargetTables,
    baseline_element,
    declared_element,
    target_element,
)

__all__ = [
    "Change",
    "ChangeClause",
    "ChangeComposition",
    "ChangeMessage",
    "ChangeRefusal",
    "ChangeRule",
    "ChangeTableError",
    "ChangeTables",
    "CompareMessage",
    "ComparisonDimension",
    "ComparisonError",
    "ComposedChange",
    "ComposedDeclared",
    "ComposedSeries",
    "ComputedChange",
    "DeclaredTarget",
    "NoChangePublished",
    "NotASeries",
    "NotPublished",
    "PeriodComparison",
    "PlacedPoint",
    "PublishedChange",
    "SelectedChange",
    "Series",
    "SeriesClause",
    "SeriesComposition",
    "SeriesError",
    "SeriesMessage",
    "SeriesPoint",
    "SeriesRefusal",
    "SeriesRule",
    "SeriesTables",
    "TargetClause",
    "TargetComposition",
    "TargetError",
    "TargetMessage",
    "TargetRule",
    "TargetTables",
    "UnlabelledChange",
    "baseline_element",
    "basis_words",
    "change_composition",
    "column_identity",
    "compare_periods",
    "comparison_dimension",
    "compute_change",
    "declared_element",
    "named_periods",
    "no_change_published",
    "paired_with",
    "select_change",
    "series_composition",
    "series_over",
    "target_element",
]
