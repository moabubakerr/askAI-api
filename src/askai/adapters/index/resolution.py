"""``CandidatePort`` over one generation: hybrid search joined to structural facts.

Purity: IO to load the facts once; pure to serve a question thereafter.

This is the adapter side of AD-25's stage 1 seam. It takes the hybrid ``names`` search of
Story 2.2 -- FTS5 fused with embedding cosine, scored per surface with the maximum across
surfaces -- and attaches to each candidate the facts of Story 2.4, so that ``compile/``
receives values and never a connection.

**The facts are read once, at construction, from the same generation.** Not per question,
and not from the read model. Both halves matter:

* *once* -- a per-question read would put a live store on the answer path behind a port
  that promises values, and would make the same question resolve differently depending on
  what a concurrent refresh had committed;
* *from the same generation* -- the candidate's score comes from this file's vectors and
  its facts come from this file's tables, so AD-13's "a request can never observe a
  mixture" covers the discrimination as well as the ranking. A candidate scored against
  one build and told apart by another is a defect with no symptom: every number looks
  reasonable and the answer is about a different indicator.

**The unit shape is classified here and the classification lives in ``rules/``.** The
generation stores the unit *as published*; the reviewed table maps it to a shape. So
re-reading ``bn QAR`` as something other than an amount is a rule edit rather than a
rebuild of every index -- which is the way round AD-11 intends.

**Nothing here is a value.** ``CandidateFacts`` can say a detail publishes ``2024``; it
cannot say what it published for it, because the generation never recorded one. The port's
promise that stage 2 cannot peek at a figure while deciding which indicator was meant is
therefore a property of what exists rather than of what this module remembers not to do.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from askai.adapters.index.facts import ENTITY_SEPARATOR
from askai.adapters.index.generation import IndexGeneration
from askai.adapters.index.namesearch import NameCandidate, NamesIndex
from askai.adapters.index.schema import FACT_PERIODS_TABLE, FACTS_TABLE
from askai.compile.resolve.tuning import fold_unit, unit_shapes
from askai.domain.normalise import normalise
from askai.domain.period import Period, PeriodFormatError
from askai.messages.lang import Lang
from askai.ports.index import IndexScope
from askai.ports.resolution import Candidate, CandidateFacts, MatchedSurface, UnitShape

__all__ = ["IndexCandidates", "load_facts"]


@dataclass(frozen=True, slots=True)
class IndexCandidates:
    """``CandidatePort`` over one generation. Frozen, and holding one immutable index.

    Constructed per generation and not per request, so it inherits AD-13's guarantee
    unchanged: the object cannot come to hold a different index, and a request that took
    one keeps resolving out of it for its whole lifetime.
    """

    index: NamesIndex
    facts: Mapping[str, CandidateFacts] = field(default_factory=dict)

    @classmethod
    def over(cls, generation: IndexGeneration) -> IndexCandidates:
        """Build the port over *generation*, reading its facts once."""
        return cls(index=NamesIndex(generation), facts=load_facts(generation.path))

    def candidates(
        self,
        subject: str,
        *,
        lang: Lang | None = None,
        limit: int | None = None,
    ) -> tuple[Candidate, ...]:
        """The details *subject* reaches, best first, each carrying its structural facts.

        The scope is built from *lang* alone. Candidate generation is deliberately
        unrestricted otherwise (AD-14's pre-filter is mandatory but an unrestricted scope
        is a legitimate one): narrowing by period or country here would apply the reader's
        constraints *before* the stage whose job is to weigh them, and a candidate
        filtered out at generation cannot be reported as ruled out by a named grain.
        """
        scope = IndexScope(lang=lang)
        return tuple(
            self._candidate(found)
            for found in self.index.candidates(subject, scope=scope, limit=limit)
        )

    def _candidate(self, found: NameCandidate) -> Candidate:
        return Candidate(
            detail_id=found.detail_id,
            indicator_id=found.indicator_id,
            score=found.score,
            matched=MatchedSurface(
                kind=found.matched.surface.kind.value,
                lang=found.matched.surface.lang,
                text=found.matched.surface.text,
            ),
            # Absent facts are empty facts, never an error. A detail present in the
            # collection and absent from the facts table is a corpus the build saw two
            # ways, and the honest reading is that nothing is known about it: every signal
            # goes silent for that candidate rather than ruling it in or out on a guess.
            facts=self.facts.get(found.detail_id, CandidateFacts()),
            name_surfaces=tuple(
                normalise(scored.surface.text)
                for scored in found.surfaces
                if not scored.surface.is_definition
            ),
            surfaces=tuple(
                normalise(scored.surface.text) for scored in found.surfaces
            ),
        )


def load_facts(path: Path) -> Mapping[str, CandidateFacts]:
    """Read every detail's structural facts out of the generation at *path*.

    Opened read-only, for the reason :func:`~askai.adapters.index.generation.load_generation`
    is: a loader that could write is a second writer to a file whose whole safety argument
    is that it has none.
    """
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        periods = _periods(connection)
        benchmarks = _benchmarks(connection)
        shapes = unit_shapes()
        found = {
            str(detail_id): CandidateFacts(
                periods=frozenset(periods.get(str(detail_id), ())),
                benchmark_countries=frozenset(benchmarks.get(str(detail_id), ())),
                unit_shape=shapes.get(fold_unit(str(unit_name)), UnitShape.UNKNOWN),
                entity_names=tuple(
                    part for part in str(entity).split(ENTITY_SEPARATOR) if part
                ),
                classification=str(classification),
            )
            for detail_id, unit_name, entity, classification in connection.execute(
                "SELECT detail_id, unit_name, entity_folded, classification "
                f"FROM {FACTS_TABLE} ORDER BY detail_id"
            )
        }
    finally:
        connection.close()
    return MappingProxyType(found)


def _periods(connection: sqlite3.Connection) -> Mapping[str, set[Period]]:
    """The periods each detail publishes, as domain values.

    A period the engine cannot classify is skipped rather than raised on, exactly as the
    read model's grain reader skips one: the build writes only what the export carried, so
    this can be reached by an export with a period spelling nothing recognises -- and a
    port that refused to load would take the whole resolution path down for one bad row,
    where a missing period only makes the coverage signal silent for one detail.
    """
    found: dict[str, set[Period]] = defaultdict(set)
    for detail_id, period in connection.execute(
        f"SELECT DISTINCT detail_id, period FROM {FACT_PERIODS_TABLE}"
    ):
        try:
            found[str(detail_id)].add(Period(str(period)))
        except PeriodFormatError:
            continue
    return found


def _benchmarks(connection: sqlite3.Connection) -> Mapping[str, set[str]]:
    """The countries each detail publishes a benchmark row for.

    A national row carries no country (AD-5), so it contributes nothing here and the 268
    details that publish only national rows have an empty set -- which the country signal
    reads as "says nothing", never as "does not match".
    """
    found: dict[str, set[str]] = defaultdict(set)
    for detail_id, country_id in connection.execute(
        f"SELECT DISTINCT detail_id, country_id FROM {FACT_PERIODS_TABLE} "
        "WHERE country_id IS NOT NULL"
    ):
        found[str(detail_id)].add(str(country_id))
    return found
