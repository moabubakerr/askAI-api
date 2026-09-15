"""``VectorSourcePort`` -- the one thing the index asks of an embedding runtime.

Purity: declaration only.

Story 2.1 leaves the embedding model undecided and requires the decision to stay
reversible: *"the embedding runtime sits behind a port so that changing the model is a
rebuild rather than a migration."* This is that port, and it is deliberately the
smallest surface that can be either a hashed character-trigram vectoriser or a hosted
768-dimension model: text in, a vector out, plus the two facts an index must record
about whatever produced it.

Those two facts are the whole of the migration story. ``identity`` is written into the
index file at build time and compared at load; ``dimensions`` is written beside it. An
index built by one source and queried by another is refused at load rather than
producing plausible nonsense -- which is what a cosine between two unrelated vector
spaces is, and what makes "a rebuild, not a migration" enforceable instead of aspirational.

The port takes **already-normalised** text. AD-26 gives the engine exactly one
``normalise()``; a vector source that folded text itself would be the second fold, and
finding 121 is what a second fold costs. The adapter normalises once, on both the index
path and the query path, and hands the result here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["VectorSourcePort"]


@runtime_checkable
class VectorSourcePort(Protocol):
    """Whatever turns text into a vector -- a local hash, or a model behind a runtime.

    Implementations are required to be deterministic: the same normalised text yields
    the same vector in this process and in the next one (AD-17). A source seeded from
    ``PYTHONHASHSEED``, a clock or a sampled decode is not implementable behind this
    port, because an index built on Monday would not be searchable on Tuesday.
    """

    @property
    def identity(self) -> str:
        """What produced the vector, specific enough to forbid a mismatched query.

        A model name and revision, or -- for the shipped fallback -- the vectoriser and
        every parameter that changes its output. Recorded in the index file; an index
        whose identity is not this one is refused rather than searched.
        """
        ...

    @property
    def dimensions(self) -> int:
        """The width of every vector this source returns. Constant for its lifetime."""
        ...

    def vectorise(self, normalised_text: str) -> tuple[float, ...]:
        """The vector for *normalised_text*, exactly ``dimensions`` long.

        The argument has already been through ``askai.domain.normalise``. It may be the
        empty string -- collapsed punctuation leaves nothing behind -- and an
        implementation returns the zero vector for it rather than raising: a surface
        with no comparable content is unmatchable, not an error.

        Normalisation to unit length is **not** required here. The index does it once,
        at build, so that cosine is a plain dot product at query time and so that one
        place decides what an all-zero vector means.
        """
        ...
