"""``CataloguePort`` -- everything ``compile/`` is allowed to know before the data.

Purity: declaration only.

AD-1 requires the ``QuerySpec`` to be produced *before any data access*, and the usual
way that guarantee is lost is not by someone reaching for a figure on purpose: it is by
the binder being handed an object that can also read datapoints, and later using it.

So the port is written as the narrow thing binding actually needs -- names, the grains a
detail publishes, and the grain it declares as its default -- and nothing on it can
return a value, a row or a period that exists in the data. A binder holding this port
*cannot* touch a figure, which is a stronger statement than a binder that does not.

Resolution through this port is **exact normalised-name lookup only** (Epic 1). The
three-stage ladder, the lexical index and the semantic index are Epic 2 and arrive as
their own ports; nothing here scores, ranks or approximates, and a name that is not the
catalogue's name returns nothing rather than the nearest thing to it.
"""

from __future__ import annotations

from typing import Protocol

from askai.domain.period import Grain

__all__ = ["CataloguePort"]


class CataloguePort(Protocol):
    """The catalogue as the binder sees it: names in, identifiers out.

    Every argument spelled ``normalised_name`` has already been through the engine's one
    normalisation (``askai.domain.normalise``). An implementation that folds text again,
    or differently, is the defect that single fold exists to prevent -- so implementations
    fold the *catalogue* side with the same function and compare for equality.
    """

    def details_named(self, normalised_name: str) -> tuple[str, ...]:
        """The ids of every detail published under exactly this normalised name.

        Empty when nothing is published under it. More than one when the name is
        genuinely shared -- 257 of 320 published names are ambiguous -- and the binder
        refuses rather than picking, because picking is the defect AD-25 exists to stop.
        Ordered, so that the same question binds the same way on every run (AD-17).
        """
        ...

    def longest_name_words(self) -> int:
        """How many words the longest published name spells.

        The binder reads the question as spans of adjacent words; a span longer than
        this can equal no published name, so it is never built. Without the bound the
        span enumeration is quadratic in the question's length and a long enough
        question exhausts memory before a single name is looked up.
        """
        ...

    def default_grain(self, detail_id: str) -> Grain | None:
        """The grain the detail *declares* as its default, or ``None`` if it declares none.

        FR-5's whole content is that this is not the grain of the detail's most recent
        row. An implementation that computes it from the datapoints has answered a
        different question, and one this port cannot ask.
        """
        ...

    def published_grains(self, detail_id: str) -> frozenset[Grain]:
        """Every grain the detail publishes at. Empty when the catalogue declares none.

        Read so that a grain the reader named and the detail does not publish can be
        *stated* (FR-6). It is never read to find a nearby grain to answer at instead.
        """
        ...

    def country_named(self, normalised_name: str) -> str | None:
        """The id of the country published under exactly this normalised name, or ``None``.

        The home country is published in no datapoint and so is in no country table;
        naming it therefore returns ``None`` and the scope falls to the national default.
        That is AD-5 arriving as an absence rather than as a special case somebody has to
        remember to write.
        """
        ...
