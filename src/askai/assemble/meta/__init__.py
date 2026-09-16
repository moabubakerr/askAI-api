"""Composing an answer *about the catalogue* -- groups, metadata, coverage, charts.

Purity: pure. Asks ``ports/`` and imports no adapter.

Epic 1's composers answer *"what is the figure"*. The composers here answer *"what
exists"*: how many indicators a group holds and what they are called, what an indicator
means, what periods it publishes at, what this engine can do at all, and whether an
answer can be charted. They live in their own package under ``assemble/`` rather than
beside ``scope.py`` because they share one thing nothing else in the tree shares -- a
provenance that points at the catalogue rather than at a datapoint.

**A count is a figure and obeys the same rules** (Story 5.3, AD-3, AD-6). A group's size
is a ``Measured`` element carrying a ``source_ref``, admitted against the loaded published
layer like any other, and refused with a typed degradation when it does not resolve. What
it cannot carry is a ``Provenance``: that type requires a period and a country scope, and
a count of a classification has neither. ``reference.py`` is the answer -- a second,
catalogue-shaped envelope with the same guarantee, that no element exists without one.

**Nothing unpublished reaches an answer from here.** No module in this package imports
``ports/unpublished_catalogue``, and none can: its types carry names and existence only,
with no field a count, a definition or a period could be put in.

**What is not here, and why.** Four of Epic 5's stories need read-model tables that do not
exist -- the champion that owns a group (Story 5.4), the sub-indicator membership behind a
components answer (5.8), and the published chart configuration (5.10). The CMS export
carries all three (``data/Champions.csv``, ``P07a``, ``P07``/``P07b``); the ingest of Story
1.8 materialises none of them, and adding a table is a schema change with an owner. So
``residual.py`` and ``chart.py`` are written over the values those tables would supply and
are tested directly against them, and the adapters that would fill them are named in the
handoff rather than invented here.
"""

from __future__ import annotations

from askai.assemble.meta.capability import CapabilityMessage, capability_elements
from askai.assemble.meta.chart import ChartOffer, ChartRule, PublishedChart, chartable_for
from askai.assemble.meta.definitions import (
    DefinitionMessage,
    DefinitionRule,
    definition_element,
    published_definition,
)
from askai.assemble.meta.groups import (
    GroupClause,
    GroupMessage,
    GroupRule,
    ambiguous_group_statement,
    group_breakdown_element,
    group_count_element,
    group_members_element,
    is_answered_at_classification_level,
)
from askai.assemble.meta.overview import (
    OverviewMember,
    OverviewMessage,
    OverviewReading,
    OverviewRule,
    overview_elements,
)
from askai.assemble.meta.periods import PeriodsMessage, calendars_by_grain, periods_element
from askai.assemble.meta.reference import (
    CatalogueReference,
    ReferenceKind,
    catalogue_element,
)
from askai.assemble.meta.residual import (
    Residual,
    ResidualMessage,
    ResidualRule,
    residual_element,
    residual_of,
)

__all__ = [
    "CapabilityMessage",
    "CatalogueReference",
    "ChartOffer",
    "ChartRule",
    "DefinitionMessage",
    "DefinitionRule",
    "GroupClause",
    "GroupMessage",
    "GroupRule",
    "OverviewMember",
    "OverviewMessage",
    "OverviewReading",
    "OverviewRule",
    "PeriodsMessage",
    "PublishedChart",
    "ReferenceKind",
    "Residual",
    "ResidualMessage",
    "ResidualRule",
    "ambiguous_group_statement",
    "calendars_by_grain",
    "capability_elements",
    "catalogue_element",
    "chartable_for",
    "definition_element",
    "group_breakdown_element",
    "group_count_element",
    "group_members_element",
    "is_answered_at_classification_level",
    "overview_elements",
    "periods_element",
    "published_definition",
    "residual_element",
    "residual_of",
]
