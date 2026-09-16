"""Searching the ``names`` collection: hybrid per surface, maximum across surfaces.

Purity: IO -- it reads one generation's file for the lexical half; the arithmetic is pure.

This is the query side of Story 2.2, and it is three rules stacked in a fixed order.

**1. Each surface is scored on its own, by both halves.** A surface's score fuses its
embedding cosine with its FTS5 lexical rank over the *same* row
(:mod:`askai.adapters.index.lexical`). The union matters, not the intersection: a name
typed exactly matches lexically and may score modestly on trigrams, and a paraphrase does
the reverse, so a row found by either half is a candidate. AD-14's pre-filter is applied
to both halves through the one ``in_scope`` the cosine scan uses -- a row admitted by the
lexical half that the scope excludes is not a candidate, and never becomes one.

**2. A detail takes the maximum across its surfaces, never a blend.** This is the whole
reason the collection is shaped as it is. A detail publishing a two-word Arabic name and
a nine-word English one scores as whichever of them the reader's question actually
resembles. Averaging, summing or concatenating would make the Arabic name unreachable in
an Arabic question, which is finding 121's shape and the failure Story 2.2 exists to end.

**3. Name and definition are two spaces, combined at the end.** The maximum over the name
surfaces and the maximum over the definition surfaces are computed separately and then
added, with the definition weighted down by ``rules/``. The alternative -- one field
holding name and definition together -- was measured on this corpus: it lost four
first-place answers and doubled the false positives over fifty real questions. The weight
and that reason live together in ``rules/`` rather than here.

**What matched is returned, not just that something did.** Finding 32's disclosure rule
needs the answer to be able to say *the Arabic label matched*, so every candidate carries
the surface that won it and the full set of surfaces that scored. The combined score is a
**ranking quantity**, not a similarity: with the definition space added it can exceed one,
and nothing compares it to a threshold. There is no relevance floor, by AD-30 -- only an
exact zero, meaning no shared feature at all, is excluded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from askai.adapters.index.generation import IndexGeneration, in_scope
from askai.adapters.index.lexical import lexical_scores
from askai.adapters.index.surfaces import NameSurface, surface_of
from askai.adapters.index.tuning import candidate_limit, definition_weight, lexical_weight
from askai.ports.index import Collection, IndexRow, IndexScope

__all__ = ["NameCandidate", "NamesIndex", "SurfaceScore"]


@dataclass(frozen=True, slots=True)
class SurfaceScore:
    """One surface, and how it scored -- both halves kept, not just the fused number.

    The halves are carried separately because they mean different things to a reader: a
    candidate found only lexically was *typed*, and one found only semantically was
    *paraphrased*, and an answer that can tell the difference can say which.
    """

    surface: NameSurface
    cosine: float
    lexical: float
    score: float


@dataclass(frozen=True, slots=True)
class NameCandidate:
    """One indicator detail a question reached, and the surface it reached it by."""

    detail_id: str
    indicator_id: str

    #: The maximum over the detail's *name* surfaces, and over its *definition* surfaces.
    #: Kept apart on the value as well as in the arithmetic, so a reviewer can see which
    #: space carried a candidate rather than inferring it from a total.
    name_score: float
    definition_score: float

    #: ``name_score`` plus the weighted ``definition_score``. A ranking quantity.
    score: float

    #: The surface that actually carried the candidate, judged on the same terms the
    #: combined score is: the best name surface, unless the weighted definition space
    #: contributed more, in which case it is the definition. This is finding 32's
    #: disclosure -- which surface matched, recorded with the candidate that matched on
    #: it -- and it would be a misstatement if a name surface scoring trigram noise were
    #: named in front of the definition that did the work.
    matched: SurfaceScore

    #: Every surface of this detail that scored above zero, best first.
    surfaces: tuple[SurfaceScore, ...]


@dataclass(frozen=True, slots=True)
class NamesIndex:
    """Hybrid search over one generation's ``names`` collection.

    Frozen and holding one generation, so it inherits AD-13's guarantee unchanged: the
    object cannot come to hold a different index, and a request that took one keeps
    answering out of it. Constructed per generation, not per request.
    """

    generation: IndexGeneration

    def candidates(
        self,
        question: str,
        *,
        scope: IndexScope,
        limit: int | None = None,
    ) -> tuple[NameCandidate, ...]:
        """The details *question* reaches within *scope*, best first.

        *scope* is mandatory (AD-14) even though candidate generation usually passes an
        unrestricted one: a port whose filter is optional makes the filter a correctness
        question at every call site instead of a property of the call.

        *limit* of ``None`` takes the reviewed candidate count from ``rules/``. It counts
        **details**, not rows: ten candidates for the discrimination stage means ten
        things to discriminate, not ten surfaces of three of them.
        """
        scored = self._surface_scores(question, scope)
        candidates = [self._candidate(detail_id, surfaces) for detail_id, surfaces in scored]
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.detail_id))
        return tuple(candidates[: candidate_limit() if limit is None else limit])

    def _surface_scores(
        self, question: str, scope: IndexScope
    ) -> list[tuple[str, list[SurfaceScore]]]:
        """Every in-scope surface that scored, grouped by detail, each group best first."""
        loaded = self.generation.collections[Collection.NAMES]
        cosines = {
            match.row.id: match.score
            for match in self.generation.search(
                question,
                collection=Collection.NAMES,
                scope=scope,
                # The whole collection: this stage ranks *details*, so it must see every
                # surface before it can take a maximum over them. The reviewed candidate
                # limit is applied to the details at the end, where it belongs.
                limit=len(loaded),
            )
        }
        lexical = lexical_scores(self.generation.path, question)
        weight = lexical_weight()
        grouped: dict[str, list[SurfaceScore]] = {}
        for row in loaded.rows:
            # Scope first, always: an out-of-scope row is not a candidate and is not
            # scored, so no number computed here can ever surface one (AD-14).
            if not in_scope(row, scope):
                continue
            scored = _score(row, cosines, lexical, weight)
            if scored is None:
                continue
            grouped.setdefault(scored.surface.detail_id, []).append(scored)
        for surfaces in grouped.values():
            surfaces.sort(key=lambda scored: (-scored.score, scored.surface.row_id))
        return sorted(grouped.items(), key=lambda item: item[0])

    def _candidate(self, detail_id: str, surfaces: Sequence[SurfaceScore]) -> NameCandidate:
        names = [scored for scored in surfaces if not scored.surface.is_definition]
        definitions = [scored for scored in surfaces if scored.surface.is_definition]
        name_score = max((scored.score for scored in names), default=0.0)
        definition_score = max((scored.score for scored in definitions), default=0.0)
        weight = definition_weight()
        # Disclosed on the same terms as the score: the definition is named only when its
        # weighted contribution exceeds the best name surface's, so a candidate carried by
        # its definition says so and one carried by a name is never attributed to prose.
        carried_by_definition = names == [] or weight * definition_score > name_score
        matched = definitions[0] if carried_by_definition and definitions else names[0]
        return NameCandidate(
            detail_id=detail_id,
            indicator_id=matched.surface.indicator_id,
            name_score=name_score,
            definition_score=definition_score,
            score=name_score + weight * definition_score,
            matched=matched,
            surfaces=tuple(surfaces),
        )


def _score(
    row: IndexRow,
    cosines: Mapping[str, float],
    lexical: Mapping[str, float],
    weight: float,
) -> SurfaceScore | None:
    """*row*'s fused score, or ``None`` when neither half reached it at all.

    A row absent from the cosine scan scored zero there, not "unknown": the scan is
    exhaustive over the collection, so absence is a measured zero and fusing it as one is
    correct rather than a default.
    """
    cosine = cosines.get(row.id, 0.0)
    rank = lexical.get(row.id, 0.0)
    fused = (1.0 - weight) * cosine + weight * rank
    if fused <= 0.0:
        return None
    return SurfaceScore(surface=surface_of(row), cosine=cosine, lexical=rank, score=fused)
