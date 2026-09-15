"""Constructing an element -- the only place in the engine that does.

Purity: pure.

AD-6: *"The class is set at construction in ``assemble/`` and is immutable."* ``Element``
enforces the immutability by being frozen and the sourcing by having no constructor that
omits a ``source_ref``; what is added here is that the reference is **derived from a
``Provenance``** rather than passed as a string beside it. A caller cannot hand in a
reference that describes something other than the figure it is attached to, because it
does not hand in a reference at all.

``absent`` gets its own function, and not because it is convenient. *"No value published
for this period"* is a class carrying content, not a missing element: at 8% analysis
coverage the absence is the common case, and an engine that expresses it by returning
nothing produces an answer that is silently shorter. A named constructor makes saying it
the easy path and leaving a hole the deliberate one.
"""

from __future__ import annotations

from askai.assemble.provenance import Provenance
from askai.domain.element import Element, ElementClass

__all__ = ["absent", "build", "derived", "measured"]


def build(content: str, element_class: ElementClass, provenance: Provenance) -> Element:
    """One element of *element_class*, carrying *content*, sourced to *provenance*.

    The class is an argument because it is a fact about where the content came from,
    which the caller knows and this function cannot infer. It is set here, at
    construction, and ``Element`` is frozen, so it is the class the element dies with.
    """
    return Element(
        content=content, element_class=element_class, source_ref=provenance.source_ref
    )


def measured(content: str, provenance: Provenance) -> Element:
    """A published row, said in words."""
    return build(content, ElementClass.MEASURED, provenance)


def derived(content: str, provenance: Provenance) -> Element:
    """Computed here, from published inputs, with the inputs stated in the content."""
    return build(content, ElementClass.DERIVED, provenance)


def absent(content: str, provenance: Provenance) -> Element:
    """*"Nothing is published for this period"* -- content, with the provenance of the
    lookup that found nothing, so a reader can see exactly what was asked for."""
    return build(content, ElementClass.ABSENT, provenance)
