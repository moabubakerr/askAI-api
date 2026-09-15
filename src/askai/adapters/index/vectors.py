"""The shipped vector source -- character trigrams -- and the one text-to-vector path.

Purity: IO by package, pure in fact: it reads the rule files and nothing else.

Story 2.1 leaves the embedding model undecided and states the fallback plainly: *"if no
available model beats the existing character-trigram resolver on the finding-42 and
F-014 cases, the trigram scorer ships as the semantic stage."* No model is available
here, so the trigram scorer is not a placeholder standing in for the real thing -- it is
the working implementation, behind ``VectorSourcePort``, and a model that arrives later
replaces it by rebuilding rather than by migrating.

**Why trigrams and not words.** The finding-42 cases are Arabic morphology: a surface
and a query that share a root but not a token. A word-level feature never matches those
at all, while a shared trigram does, and it does so after AD-26's fold has already
removed the orthographic variation that would otherwise split the root three ways.

**Why hashed and not a vocabulary.** A vocabulary would have to be built, stored and
kept in step with the corpus, and a vector's meaning would then depend on which rows
happened to be indexed when. Hashing fixes the space in advance: a vector built today
and a query vectorised in another process land in the same coordinates because
``blake2b`` is the same function everywhere, which ``hash()`` is not -- it is seeded per
process, so an index built with it would be unsearchable after a restart (AD-17).

The cost is collisions: at the reviewed width two unrelated trigrams sometimes share a
column, which inflates a similarity slightly. Counts are kept non-negative rather than
signed, so a collision can only ever add a little, never subtract -- a floor derived from
measured distributions (AD-30) absorbs a known upward bias more safely than it absorbs
noise in both directions.

``unit_vector_for`` is the **single** path from text to vector, and the build and the
query both call it. That is AD-26 at the level this module can enforce it: not "both
call ``normalise()``" as a convention, but one function that folds, vectorises and
normalises to unit length, so the two paths cannot come apart even by accident.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Final

from askai.adapters.index.tuning import pad_boundaries, trigram_size, vector_width
from askai.domain.normalise import normalise
from askai.ports.vectors import VectorSourcePort

__all__ = ["TrigramVectorSource", "unit_length", "unit_vector_for"]

#: The name recorded in every index this source builds. It carries every parameter that
#: changes the output, because that is what makes the recorded identity a usable refusal
#: at load time rather than a label.
_FAMILY: Final = "trigram-blake2b"

#: Eight bytes of digest is far more entropy than the column count needs; taking a
#: prefix rather than the whole digest keeps the integer conversion cheap.
_DIGEST_BYTES: Final = 8

#: The padding character. It is a space because ``normalise()`` has already collapsed
#: every separator to exactly this, so a padded surface is still a string the fold would
#: leave alone -- the pad is a boundary marker, not a new character class.
_PAD: Final = " "


@dataclass(frozen=True, slots=True)
class TrigramVectorSource:
    """Hashed character n-grams over the engine's normal form.

    Satisfies ``VectorSourcePort`` structurally rather than by inheritance: a protocol
    with data members brings its own ``...`` bodies along when it is subclassed, which
    would shadow the fields below with properties returning nothing. The conformance is
    checked by ``mypy`` at every call site that takes the port, and asserted directly in
    ``tests/test_index.py``.

    Every parameter defaults from ``rules/`` rather than from a literal here, so the
    reviewed width and window are what an index is actually built with. They are
    constructor arguments as well, because a test that pins a width needs to say so out
    loud, and because an index records what it was built with regardless.
    """

    dimensions: int = field(default_factory=vector_width)
    window: int = field(default_factory=trigram_size)
    pad: bool = field(default_factory=pad_boundaries)

    def __post_init__(self) -> None:
        if self.dimensions < 1:
            raise ValueError(f"a vector of {self.dimensions} dimensions cannot hold a feature")
        if self.window < 1:
            raise ValueError(f"a character window of {self.window} cuts nothing out of text")

    @property
    def identity(self) -> str:
        """Everything about this source that changes a vector, in one comparable string."""
        return f"{_FAMILY}/w{self.window}/d{self.dimensions}/pad{int(self.pad)}"

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        """Counts of *normalised_text*'s character windows, hashed into fixed columns.

        Not unit length: ``unit_length`` does that once, so that the build and the query
        cannot disagree about what an all-zero vector means.
        """
        counts = [0.0] * self.dimensions
        for gram in self._windows(normalised_text):
            counts[self._column(gram)] += 1.0
        return tuple(counts)

    def _windows(self, text: str) -> tuple[str, ...]:
        padded = f"{_PAD}{text}{_PAD}" if self.pad and text else text
        if len(padded) < self.window:
            # Shorter than one window: the whole string is its own single feature, so a
            # two-letter code is findable instead of being indexed as nothing at all.
            return (padded,) if padded else ()
        return tuple(
            padded[start : start + self.window] for start in range(len(padded) - self.window + 1)
        )

    def _column(self, gram: str) -> int:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=_DIGEST_BYTES).digest()
        return int.from_bytes(digest, "big") % self.dimensions


def unit_length(vector: tuple[float, ...]) -> tuple[float, ...]:
    """*vector* scaled to length 1, or left as zeros when it has no length.

    The zero vector is returned unchanged rather than raising. A surface whose text
    normalises to nothing -- punctuation, an empty cell -- is unmatchable, and it scores
    zero against everything, which is the correct answer and not an error.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return tuple(value / norm for value in vector)


def unit_vector_for(raw: str, source: VectorSourcePort) -> tuple[float, ...]:
    """The unit vector for *raw* text: fold once, vectorise, scale to length 1.

    The one path from text to vector, called by the index build and by every query.
    AD-26 asks for the index and the query to fold text with the same ``normalise()``;
    this goes one step further and gives them the same *function* to call, so the two
    paths cannot drift apart even if a later caller forgets what the rule was for.
    """
    return unit_length(source.vectorise(normalise(raw)))
