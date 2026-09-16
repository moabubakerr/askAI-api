"""``PresentationPort`` -- the published detail as the answer is allowed to present it.

Purity: declaration only.

``CataloguePort`` is deliberately narrow: names in, identifiers out, and nothing that can
return a value, a row or a period (AD-1). That narrowness is what stops a binder reaching
for a figure, and it is also why it cannot supply the two things composing an answer
needs after the figure exists -- the detail's **published unit and Format field**, which
AD-18 makes the formatter's only inputs, and the detail's **publishing source**, which
AD-6 makes part of every element's provenance.

So they arrive through a second port, read after execution rather than before it. The
split is the point: a layer holding ``CataloguePort`` still cannot see a row, and a layer
holding this one still cannot see a value -- there is no method here that returns one.

``Lang`` is an argument on both methods and has no default. The published layer carries
every name in both languages, and choosing between them at the point of use is exactly
the inference AD-11 forbids: a caller that has not been handed the question's language
cannot ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from askai.messages.lang import Lang

__all__ = ["PresentationPort", "PublishedDetail"]


@dataclass(frozen=True, slots=True)
class PublishedDetail:
    """One detail as an answer presents it: its name, its format, and who published it.

    ``unit`` and ``value_format`` are carried **exactly as published**, placeholder units
    and empty Format fields included. Cleaning them here would move the display decision
    into the boundary, and the two rules that handle those cases
    (``R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT``, ``R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT``)
    would have nothing left to fire on.
    """

    detail_id: str
    #: The detail's published name in the requested language -- reader-facing text that
    #: is *data*, read from the published layer, never a literal in a module.
    name: str
    unit: str
    value_format: str
    #: The publishing source's identifier. Part of every element's ``source_ref``, so an
    #: element cannot exist without naming who published the row behind it (AD-6).
    source_id: str

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise ValueError("a published detail is identified by its detail id")
        if not self.source_id.strip():
            raise ValueError(
                "a published detail names its publishing source; an element whose "
                "source cannot be named cannot be defended (AD-6)"
            )


class PresentationPort(Protocol):
    """How a bound identifier becomes the words and the format an answer presents it in."""

    def detail(self, detail_id: str, lang: Lang) -> PublishedDetail | None:
        """The published detail behind *detail_id*, or ``None`` when it names none.

        ``None`` is "the published layer holds no such detail", never "the store did not
        answer": a store that cannot answer raises its adapter's own typed failure, which
        is the distinction AD-15 keeps between absence and breakage.
        """
        ...

    def country(self, country_id: str, lang: Lang) -> str | None:
        """The country's published name in *lang*, or ``None`` when it names none.

        National scope never reaches this method: it is the *absence* of a country
        (AD-5), so there is no id to look up and nothing to name.
        """
        ...
