"""``Composed`` -- what every composer in this package returns, and nothing else does.

Purity: pure.

One type for four compositions, so that a caller wiring a comparison into an answer
handles one shape rather than four, and so that the two states a composition can be in
are the same two everywhere: it produced elements, or it refused and said why.

The invariant is checked rather than documented. A composition carrying neither is the
silent failure -- an answer that is simply shorter, with nothing saying so -- and a
composition carrying both is an answer that shows a comparison and a refusal of it at
once. Both are constructible without the check, and both read as plausible until someone
looks at the JSON.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.assemble.roles import Placed

__all__ = ["Composed"]


@dataclass(frozen=True, slots=True)
class Composed:
    """What a comparison composed: its elements, or the statement standing in for them.

    Exactly one of the two is filled. A composition that produced elements has no
    ``reason``; one that refused has no elements and always says why, because a refusal
    with nothing stated is the silent failure AD-15 exists to prevent.
    """

    elements: tuple[Placed, ...] = ()
    reason: str | None = None

    row_ids: tuple[str, ...] = ()
    """The published rows this composition was computed from, for the answer record. It
    matters most where there is more than one: FR-19 requires a derived figure to state
    its inputs, and a spread's two endpoints are two rows behind one element -- which an
    element's single ``source_ref`` has nowhere to carry."""

    def __post_init__(self) -> None:
        if bool(self.elements) is (self.reason is not None):
            raise ValueError(
                "a composition carries elements or a stated reason, never both and never "
                f"neither; it has {len(self.elements)} elements and reason {self.reason!r}"
            )

    @property
    def refused(self) -> bool:
        return self.reason is not None
