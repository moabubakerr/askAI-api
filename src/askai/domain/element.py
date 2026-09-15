"""``Element`` -- the provenance envelope every piece of an answer travels in.

Purity: pure, imports nothing in-project.

AD-6: every element is ``Element(content, class, source_ref)``, and **there is no
constructor that produces an element without a source_ref**. That is the whole design.
Provenance stops being a render-time label brevity can drop, and becomes a thing an
element cannot exist without.

``Article`` is deliberately separate from ``Attributed``. An analyst note carries an
indicator, grain, period and country; an article carries none of them. Collapsing the
two is how an opinion piece comes to stand in for a statistic.

**Class and role are independent axes and must stay so.** ``class`` asks where the
content came from and governs what it may contain; ``role`` asks what job it does in
the answer and governs where it goes and which lens shows it. An ``analysis`` role
filled from a datapoint note is class ``attributed``; the same role filled from an
article is class ``article``. A single "kind" field would force those together.
**Role is not modelled here** -- it arrives with the lens mapping in ``rules/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Element", "ElementClass"]


class ElementClass(StrEnum):
    """Where an element's content came from. Set at construction, immutable after."""

    MEASURED = "measured"
    """A published row."""

    DERIVED = "derived"
    """Computed here, with its inputs stated."""

    ATTRIBUTED = "attributed"
    """Analyst text bound to a datapoint."""

    ARTICLE = "article"
    """Published editorial -- dated, authored, and bound to no indicator."""

    EXTERNAL = "external"
    """Third-party content, always caveated."""

    ABSENT = "absent"
    """*"No analyst commentary published for this period."* Content, not a missing
    element: at 8% analysis coverage this is the common case, so it is said rather
    than left as a hole."""


@dataclass(frozen=True, slots=True)
class Element:
    """One piece of an answer, with its provenance attached.

    All three fields are required and none has a default. There is deliberately no
    alternate constructor, no overload and no classmethod -- any of those would be a
    second route to an element, and the guarantee is that no such route exists.
    ``tests/test_type_invariants.py`` asserts under ``mypy --strict`` that omitting
    ``source_ref`` does not type-check.
    """

    content: str
    element_class: ElementClass
    source_ref: str

    def __post_init__(self) -> None:
        # A blank source_ref satisfies the signature and defeats the guarantee: it is
        # exactly the render-time-droppable label AD-6 exists to eliminate, and the
        # type-level fixture cannot see it because `Element(c, k, "")` type-checks.
        if not self.source_ref.strip():
            raise ValueError(
                "Element requires a non-blank source_ref; an element whose provenance "
                "is an empty string is the unsourced content AD-7 rejects"
            )
