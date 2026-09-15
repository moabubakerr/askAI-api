"""The reader's words, folded once and read as spans.

Purity: pure.

Everything the binders ask of a question is "does it name this?", and the honest way to
answer that is to compare the engine's one normal form of the question against the
engine's one normal form of the thing -- a catalogue name, a month, a grain word. So the
question is folded exactly once, here, by ``askai.domain.normalise``, and every lookup
downstream is an equality test against a *span* of it.

A span is a run of adjacent words. Comparing spans rather than substrings is what keeps
"gdp" out of "gdp deflator" and stops a two-word name matching across a comma; comparing
them longest-first is what makes the longer published name win when both are published,
which is the only preference this module has and the only one Epic 1 is allowed (exact
normalised-name lookup, no scoring).

The raw words are kept alongside the folded ones because the fold collapses punctuation
to spaces, and ``2026-04`` folded is ``2026 04`` -- no longer a published period. Period
spellings are therefore read off the raw words and handed to ``Period``, which is the one
thing that decides whether a string is a published period.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from askai.domain.normalise import normalise

__all__ = ["Question", "Span"]


@dataclass(frozen=True, slots=True)
class Span:
    """A run of adjacent words in the folded question, and the text it spells."""

    start: int
    stop: int
    text: str

    @property
    def length(self) -> int:
        return self.stop - self.start

    def overlaps(self, other: Span | None) -> bool:
        if other is None:
            return False
        return self.start < other.stop and other.start < self.stop


def _trimmed(word: str) -> str:
    """A raw word with its surrounding punctuation removed and its insides intact.

    ``2026-04?`` has to lose the question mark and keep the hyphen, so this trims from
    the ends rather than filtering throughout: a filter would also take the hyphen and
    turn a published monthly period into a six-digit number.
    """
    start, stop = 0, len(word)
    while start < stop and not word[start].isalnum():
        start += 1
    while stop > start and not word[stop - 1].isalnum():
        stop -= 1
    return word[start:stop]


@dataclass(frozen=True, slots=True)
class Question:
    """One question, folded once, with the raw words kept for period spellings."""

    asked: str
    words: tuple[str, ...]
    raw_words: tuple[str, ...]

    @classmethod
    def parse(cls, asked: str) -> Question:
        return cls(
            asked=asked,
            words=tuple(normalise(asked).split()),
            raw_words=tuple(trimmed for trimmed in map(_trimmed, asked.split()) if trimmed),
        )

    def spans(self) -> tuple[Span, ...]:
        """Every run of adjacent words, longest first and leftmost within a length.

        The order *is* the preference: the first span a lookup matches is the one that
        wins, so a longer published name beats the shorter one inside it without anything
        having to score them.
        """
        found = [
            Span(start=start, stop=stop, text=" ".join(self.words[start:stop]))
            for start in range(len(self.words))
            for stop in range(start + 1, len(self.words) + 1)
        ]
        found.sort(key=lambda span: (-span.length, span.start))
        return tuple(found)

    def names(self, phrases: Iterable[str], *, excluding: Span | None = None) -> Span | None:
        """The span naming one of *phrases*, or ``None``. Longest match wins.

        *excluding* takes a span out of consideration -- the span the detail bound from,
        so that a word inside the indicator's own published name cannot also be read as
        a measure or a grain.
        """
        wanted = frozenset(phrases)
        for span in self.spans():
            if span.overlaps(excluding):
                continue
            if span.text in wanted:
                return span
        return None

    def names_one_of[K](
        self, table: Mapping[K, frozenset[str]], *, excluding: Span | None = None
    ) -> tuple[K, Span] | None:
        """The key whose phrases the question names, with the span that named it.

        Spans are walked longest-first and the keys in the order the table gives them, so
        two keys sharing a phrase resolve the same way on every run (AD-17).
        """
        for span in self.spans():
            if span.overlaps(excluding):
                continue
            for key, phrases in table.items():
                if span.text in phrases:
                    return key, span
        return None

    def numbered(
        self, table: Mapping[str, int], *, excluding: Span | None = None
    ) -> tuple[int, Span] | None:
        """The number the question names in words -- a month, a quarter -- and its span."""
        for span in self.spans():
            if span.overlaps(excluding):
                continue
            number = table.get(span.text)
            if number is not None:
                return number, span
        return None
