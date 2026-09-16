"""Everything one process needs to answer, assembled once and handed to the routes.

Purity: edge.

Every layer below has been written to be handed its collaborators rather than to reach
for them -- ``Formatter`` takes the catalogue and the rules, ``Placement`` takes the
rules, ``compile_question`` takes a ``CataloguePort``, ``StateFileFreshness`` takes a
path -- and none of them has a module-level anything. ``Engine`` is what they are handed
*in*: one frozen value holding the loaded data and every port, so a route has one
argument rather than a dozen, and a reviewer reads the whole graph in one type.

Three things are deliberate.

**Held once, per process, not per request.** The message catalogue, the rule set and the
name snapshot are fields on a frozen value built at startup, so no route can reload one.
A snapshot rebuilt per request would make the same question bind differently depending on
what a concurrent refresh had committed -- AD-17's determinism lost to a convenience.

**The clock is injected.** ``now`` is a field, so a test states the moment it means. An
engine that read the clock inside would make every staleness assertion a race, and would
make "the same question compiles to the same spec" untestable at the only layer where the
clock is legitimately read at all.

**Nothing here reads the environment, and nothing here reaches ``refresh/``.** Where the
databases live is a typed setting read once in ``config/``, and the freshness producer is
an out-of-band job's module that no route may reach (AD-21) -- so both arrive as
already-built values. ``FreshnessPort`` is declared in ``ports/`` for exactly this reason:
the block travels to health and to every answer without the answer path importing the job
that produces it. The process composition root that builds them is
:mod:`askai.adapters.readmodel.startup`, and it is deliberately not part of this package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from askai.assemble.format import Formatter
from askai.assemble.roles import Placement
from askai.compile.catalogue import SnapshotCatalogue
from askai.execute.readmodel import ReadModelDatapoints
from askai.messages import Catalogue
from askai.ports.freshness import FreshnessPort
from askai.ports.presentation import PresentationPort
from askai.ports.provenance_source import SourceCatalogue
from askai.ports.record import RecordPort
from askai.ports.store_health import StoreHealthPort
from askai.rules import RuleSet

__all__ = ["READ_MODEL_STORE", "RECORD_STORE", "Engine"]

#: The names the health endpoint reports each store under. Operator-facing labels on a
#: diagnostic endpoint, not reader-facing answer text, so they are spelled here rather
#: than in the bilingual catalogue -- an operator reads one language and a reader reads
#: the other, and conflating them would put log vocabulary in front of the Council.
READ_MODEL_STORE = "read_model"
RECORD_STORE = "record_store"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Engine:
    """One process's answer path: the loaded data, the ports, and the clock.

    Frozen. Every field is either an immutable value loaded at startup or a port over a
    connection opened at startup; there is nothing here a request can change, so two
    concurrent requests share this object without sharing any state.
    """

    messages: Catalogue
    rule_set: RuleSet
    names: SnapshotCatalogue
    datapoints: ReadModelDatapoints
    presentation: PresentationPort
    sources: SourceCatalogue
    freshness: FreshnessPort
    records: RecordPort
    stores: tuple[StoreHealthPort, ...]
    now: Callable[[], datetime] = _utc_now
    formatter: Formatter = field(init=False)
    placement: Placement = field(init=False)

    def __post_init__(self) -> None:
        # Built from the two already-loaded values rather than taken as arguments: a
        # formatter reading a different catalogue from the one the answer renders in is
        # a defect nobody would spot, and there is no reason for a caller to be able to
        # arrange it.
        object.__setattr__(
            self, "formatter", Formatter(catalogue=self.messages, rule_set=self.rule_set)
        )
        object.__setattr__(self, "placement", Placement(rule_set=self.rule_set))
