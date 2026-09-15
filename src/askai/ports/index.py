"""``IndexPort`` -- the semantic index as a caller sees it, plus the values it trades in.

Purity: declarations only.

AD-13 makes one promise about this port's future: *"should the corpus grow an order of
magnitude, the migration is an ANN index behind the same ``IndexPort``, changing no
contract."* So nothing here mentions cosine, brute force, a file, a table or a vector
width. What it does mention is the two things a caller may never lose:

**A search is filtered before it is ranked (AD-14).** ``IndexScope`` is a mandatory
argument, not an optional refinement, and it is applied as a pre-filter: an out-of-scope
row is not a candidate and cannot be surfaced by a high score. A port whose scope was
optional would make the December-analysis-for-a-May-question failure (F-015) a
correctness question about every call site instead of a property of the interface.

**A holder of this port cannot observe a mixture (AD-13, AD-20).** The implementation is
an *immutable snapshot*: the object satisfying ``IndexPort`` is one generation of the
index and can never become another. A refresh builds a new generation and swaps the
reference; a request that took a reference at its start keeps answering out of the
generation it took, for its whole lifetime, because there is no representable state in
which that object's contents changed underneath it.

``IndexRow`` is the build side of the same contract: what a collection stores per row,
including the scope columns the pre-filter needs. Both directions are values, so a
caller can build an index in a test without a file, a service, or a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from askai.domain.period import Period
from askai.messages.lang import Lang

__all__ = ["Collection", "IndexPort", "IndexRow", "IndexScope", "Match"]


class Collection(StrEnum):
    """The collections the index holds, each scored in its own space.

    Closed, and closed for the same reason ``DegradationKind`` is: a collection invented
    at a call site is a collection with no chunking rule, no ground-truth set (AD-30) and
    no derived floor. Adding one is a story, not an argument.
    """

    #: One vector per published *surface* -- indicator name, detail name, label, alias --
    #: in each language (AD-25 stage 1, Story 2.2). Never one combined vector per
    #: indicator: a short Arabic name must not be diluted by a long English one.
    NAMES = "names"

    #: Analyst passages, chunked at the author's own boundaries (AD-27). Every passage is
    #: datapoint-bound, so its scope columns are always populated and AD-14's pre-filter
    #: is always available.
    ANALYST = "analyst"

    #: Article paragraphs. They carry no indicator key, which is exactly why AD-30 gives
    #: this collection a hand-labelled set and a floor rather than a nearest neighbour.
    ARTICLES = "articles"


@dataclass(frozen=True, slots=True)
class IndexRow:
    """One indexable unit: the text to embed, its identity, and its scope.

    The text is stored as well as embedded -- AD-13 wants *"the exact text embedded, for
    audit"* -- so a retrieved row can be shown, quoted and defended without re-deriving
    what the build actually saw.
    """

    id: str
    """Stable within its collection: a detail id, a datapoint key plus field, an article
    id plus chunk number. Opaque here; the index never parses it."""

    lang: Lang
    text: str

    #: The scope columns. Each is the pre-filter of AD-14, never a post-filter, and each
    #: is genuinely absent for some rows: an article has no detail and no period, a
    #: national figure has no country, and only an article carries a date.
    detail_id: str | None = None
    period: Period | None = None
    country_id: str | None = None
    article_date: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("an index row needs an id; an anonymous row cannot be retrieved")


@dataclass(frozen=True, slots=True)
class IndexScope:
    """The hard pre-filter a search runs under. Every field left unset means unfiltered.

    ``country_id`` and ``national`` are two fields rather than one for the reason AD-5
    gives: in the published layer a national figure is a row with **no** country, so
    "the national row" and "any country" are different filters that a single nullable
    field would spell identically. Asking for both at once is refused here rather than
    resolved by precedence.
    """

    detail_id: str | None = None
    period: Period | None = None
    country_id: str | None = None
    lang: Lang | None = None

    #: Match only rows with no country -- the published spelling of national scope.
    national: bool = False

    def __post_init__(self) -> None:
        if self.national and self.country_id is not None:
            raise ValueError(
                "a scope is national or names a country, never both; national scope is "
                "the absence of a country in the published layer, not a country value"
            )


@dataclass(frozen=True, slots=True)
class Match:
    """One row the index returned, with the score it returned it on.

    ``float`` and not ``Decimal``, deliberately: a similarity is a computed ranking
    quantity, never a published value, and the convention that bans float is about the
    latter. Nothing formatted for a reader is derived from this number.
    """

    row: IndexRow
    score: float


@runtime_checkable
class IndexPort(Protocol):
    """One generation of the semantic index, searchable and immutable."""

    @property
    def source_identity(self) -> str:
        """The ``VectorSourcePort.identity`` this generation was built with.

        Carried so a caller can record *which* vector space an answer was retrieved
        from. Changing the model changes this string, and the index that carries the old
        one is refused rather than queried -- a rebuild, not a migration.
        """
        ...

    def search(
        self,
        question: str,
        *,
        collection: Collection,
        scope: IndexScope,
        limit: int | None = None,
    ) -> tuple[Match, ...]:
        """The best rows of *collection* within *scope*, most similar first.

        *question* is raw reader text; the implementation puts it through the engine's
        one ``normalise()`` -- the same call the build made -- before comparing anything
        (AD-26). *limit* of ``None`` takes the reviewed candidate count from ``rules/``.

        Returns an empty tuple when the scope admits nothing or nothing resembles the
        question. That is a well-founded absence and not a degradation: the index worked
        and there was nothing there.
        """
        ...
