"""Comparison: countries against countries, indicators against each other, and the
extrema, ranks and spreads over one bound scope.

Purity: pure.

Epic 4. Three things live here and nowhere else:

* **The union of a national selection and a benchmark selection** (AD-5, FR-11b), formed
  in one place, in ``selection.py``. The home country is declared in all 21 benchmark
  sets and named in none of the 8,127 published rows, so a comparison that looks
  countries up by name retrieves every benchmark and silently drops the country the
  reader asked about. The union is two fields of two different types -- a flag and a set
  of codes ``filter_values()`` structurally cannot put the home country into -- and
  never one widened filter.
* **Four different refusals, where a lesser engine would have one.** Cross-country
  comparison reaches 21 of 289 details, so refusing is the normal and correct outcome,
  and the refusals are worth telling apart: this indicator declares no benchmark
  countries; the countries you named are not among the ones it declares; it declares
  them and publishes no country rows at all; it declares them and this particular one
  published nothing at this period. The first two are configuration gaps and the last
  two are data gaps, and a QC tester is entitled to tell which from the answer.
* **One ordering behind every superlative, rank and spread** (``extrema.py``). Three
  compositions read off one ``ordered()``, so a "highest" and the rank beside it cannot
  disagree -- the F-015 and finding-43 shape, where a figure is composed once and then
  quietly recomputed.

Nothing in this package fetches anything. It is handed the readings -- including the
ones that came back empty, which is the point -- and every constant it applies comes
from ``rules/data/comparison.yaml`` and every word from ``messages/``.
"""

from __future__ import annotations

from askai.assemble.compare.composed import Composed
from askai.assemble.compare.countries import (
    CompareMessage,
    compare_countries,
    country_line,
    refusal_statement,
)
from askai.assemble.compare.extrema import (
    Candidate,
    Direction,
    ExtremumMessage,
    Scope,
    best_direction,
    extremum,
    ordered,
    ranking,
    spread,
)
from askai.assemble.compare.indicators import (
    IndicatorMessage,
    compare_indicators,
    units_differ,
)
from askai.assemble.compare.ordinals import (
    OrdinalMessage,
    named_positions,
    ordinal,
    rank_format,
)
from askai.assemble.compare.readings import (
    CountryReading,
    IndicatorReading,
    at_period,
    with_figures,
)
from askai.assemble.compare.selection import (
    CompareClause,
    CompareRule,
    Declaration,
    NotComparable,
    Selection,
    SelectionOutcome,
    SelectionRefusal,
    SelectionRuleError,
    fan_out_bound,
    named_countries_may_expand,
    select,
)

__all__ = [
    "Candidate",
    "CompareClause",
    "CompareMessage",
    "CompareRule",
    "Composed",
    "CountryReading",
    "Declaration",
    "Direction",
    "ExtremumMessage",
    "IndicatorMessage",
    "IndicatorReading",
    "NotComparable",
    "OrdinalMessage",
    "Scope",
    "Selection",
    "SelectionOutcome",
    "SelectionRefusal",
    "SelectionRuleError",
    "at_period",
    "best_direction",
    "compare_countries",
    "compare_indicators",
    "country_line",
    "extremum",
    "fan_out_bound",
    "named_countries_may_expand",
    "named_positions",
    "ordered",
    "ordinal",
    "rank_format",
    "ranking",
    "refusal_statement",
    "select",
    "spread",
    "units_differ",
    "with_figures",
]
