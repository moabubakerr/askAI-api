"""``GroupsPort`` -- the catalogue's own group layer and metadata, as a composer sees it.

Purity: declaration only. No implementation lives here and none may.

Epic 1 gave ``compile/`` a ``CataloguePort`` (names, for binding) and ``execute/`` a
``DatapointsPort`` (figures, by exact key). Neither answers the questions Epic 5 asks,
and neither should be widened to: a binder that could count a group would be a binder
that could reach the data before AD-1 says it may, and a datapoints port that could
return a classification would be a second figure source.

So this is a third, narrow port, read *after* binding, by ``assemble/meta/``:

* **The group layer.** Every indicator in the published catalogue carries exactly one
  classification and exactly one entity -- 189/189, measured. The two levels are a real
  hierarchy and are modelled as one type with a ``level``, because the answer to *"the
  indicators in Sectors"* and the answer to *"the indicators in Tourism"* differ only in
  which level the name bound to (FR-30). A port with one method per level would let a
  caller ask the wrong one and get a plausible answer 105 indicators too large.
* **Published definitions**, so FR-33 can quote rather than generate.
* **What the read model actually holds**, so FR-32's capability answer is counted rather
  than written down. A hand-maintained list of capabilities drifts from the truth the
  moment an indicator is added; a count cannot.

**Nothing here returns a value, a target or a baseline.** The port carries counts and
names and no figure column, so a catalogue question cannot become a back door to a
datapoint that ``execute/`` did not fetch by its exact key.

**Nothing here returns anything unpublished.** ``ports/unpublished_catalogue.py`` is the
only route to the base CMS layer and it exposes names and existence only; no type
declared here has a field one could be put in.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

__all__ = [
    "Coverage",
    "Group",
    "GroupLevel",
    "GroupedIndicator",
    "GroupsPort",
    "PublishedDefinition",
]


class GroupLevel(StrEnum):
    """Which level of the group layer a name bound to.

    Two members, and the distinction is the whole of Story 5.2: *"Sectors"* is a
    classification holding 105 indicators across 8 entities, and *"Tourism"* is one of
    those entities holding 7. One word apart, ninety-eight indicators apart.
    """

    CLASSIFICATION = "classification"
    """The published ``EntityClassificationName`` -- 7 of them, covering all 189."""

    ENTITY = "entity"
    """The published entity a classification is divided into -- 22 of them, measured
    across ``Sectors.csv`` and ``General Entities.csv``, and all 189 resolve to one."""


@dataclass(frozen=True, slots=True)
class Group:
    """One group of the published catalogue, at either level, with its size.

    ``indicator_count`` is a field rather than something a caller derives by listing and
    counting, and that is deliberate: FR-50 requires a confidential indicator to be
    *excluded from the count*, not merely hidden from the list, so the count and the list
    have to come from the same filtered query. A caller that could count a list it was
    handed could count a list something had already trimmed.

    ``classification`` is carried on both levels. On an entity it names the classification
    the entity sits in, which is what lets an ambiguous name state both readings without
    a second lookup; on a classification it is the classification's own key, so the field
    is never empty and no caller has to branch on which level it is holding.
    """

    level: GroupLevel
    key: str
    """The classification's published name, or the entity's published id."""

    name_en: str
    name_ar: str
    indicator_count: int
    classification: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("a group is identified by its key; a blank key names nothing")
        if self.indicator_count < 0:
            raise ValueError(
                f"a group holds {self.indicator_count} indicators, which is not a count; "
                "an empty group holds none and says so"
            )


@dataclass(frozen=True, slots=True)
class GroupedIndicator:
    """One published indicator, as a member of a group: an id and its two names.

    No unit, no period, no value. A list of what a group contains is a catalogue answer,
    and an indicator that arrived here carrying a figure would be a figure that reached
    the reader without going through ``execute/``.
    """

    indicator_id: str
    name_en: str
    name_ar: str


@dataclass(frozen=True, slots=True)
class PublishedDefinition:
    """A detail's published definition, exactly as published, in both languages.

    Carried as published -- the placeholder ``-`` included. 88 of the 289 published
    details carry ``-`` as their English definition and 89 carry it in Arabic, and
    cleaning that at the boundary would put the *"state that none is published"* decision
    in the adapter, where no reviewer would look for it. ``assemble/meta/`` decides, and
    fires a named rule doing it.
    """

    detail_id: str
    definition_en: str
    definition_ar: str
    source_id: str
    """The detail's publishing source, so a quoted definition is attributed (FR-46)."""


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the loaded read model actually holds, counted.

    Every field is a count of rows in the file the engine answers from, so the capability
    answer FR-32 asks for is a reading of the data rather than a description of the
    product. Nothing here is a ceiling someone wrote down; a refresh that adds an
    indicator changes the answer without anyone editing a sentence.

    There is deliberately **no field for analyst commentary or articles**. The read model
    has no table for either (Story 1.6 creates none, and Epic 6 is blocked on it), so a
    count would be a zero that reads like a measurement. The capability answer states
    what it cannot do instead.
    """

    indicators: int
    indicators_with_data: int
    details: int
    details_with_data: int
    datapoints: int
    countries: int
    details_with_country_data: int
    classifications: int
    entities: int


class GroupsPort(Protocol):
    """The published catalogue as a catalogue question sees it. Read-only by construction."""

    def classifications(self) -> tuple[Group, ...]:
        """Every published classification, in a stable order, with its size."""
        ...

    def entities_in(self, classification: str) -> tuple[Group, ...]:
        """The entities inside *classification*, largest first, then by name.

        Largest first because ``R-165`` answers a category with the groups inside it and
        their counts -- the level above the list -- and a reader scanning that list is
        looking for where the weight is.
        """
        ...

    def groups_named(self, normalised_name: str) -> tuple[Group, ...]:
        """Every group published under exactly this normalised name, at either level.

        More than one is not an error and is not resolved here: a name that reads as both
        a classification and an entity is FR-2's clarification, and picking is the defect
        AD-25 exists to stop. Ordered, so the same question clarifies the same way on
        every run (AD-17).
        """
        ...

    def indicators_in(self, level: GroupLevel, key: str) -> tuple[GroupedIndicator, ...]:
        """The published indicators in the group *key* at *level*, in a stable order."""
        ...

    def details_of(self, indicator_id: str) -> tuple[str, ...]:
        """The ids of the details published under *indicator_id*, main detail first.

        The overview needs one figure per indicator and a figure belongs to a detail, so
        the main detail is the one it reads. Ordering rather than filtering, because an
        indicator whose details are all non-main still has details, and returning nothing
        would make it look unpublished.
        """
        ...

    def definition(self, detail_id: str) -> PublishedDefinition | None:
        """The published definition of *detail_id*, or ``None`` when no such detail exists.

        ``None`` means *no such detail*. A detail that exists and publishes ``-`` returns
        a ``PublishedDefinition`` carrying the ``-``; the two are different answers and
        collapsing them would tell a reader their indicator does not exist.
        """
        ...

    def coverage(self) -> Coverage:
        """What the loaded read model holds, counted now rather than recorded earlier."""
        ...
