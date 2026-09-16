"""``StoreHealthPort`` -- can this store be reached at all?

Purity: declaration only.

``GET /api/health`` reports two independent facts and must not confuse them: whether the
stores answer, and how old the copy in them is (AD-21, NFR-7). Freshness has its own port
already; this is the other half, and it is separate on purpose. A read model that is
perfectly fresh and a read model that cannot be opened are different incidents, and an
endpoint that folded them into one word would tell an operator to go looking in the wrong
place.

The method returns a value rather than raising. Reachability is the question, so "no" is
an answer: an implementation that let a driver error escape would make the health check
itself the thing that fails, which is the one endpoint that must always respond.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["StoreHealth", "StoreHealthPort"]


@dataclass(frozen=True, slots=True)
class StoreHealth:
    """Whether one store answered, and what it said if it did not."""

    name: str
    reachable: bool
    #: Why it did not answer. Empty exactly when ``reachable`` is true, so the two
    #: fields cannot disagree about whether anything went wrong.
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reachable != (not self.detail):
            raise ValueError(
                f"{self.name} is reported reachable={self.reachable} with detail "
                f"{self.detail!r}; a store that did not answer says why, and one that "
                "did has nothing to say"
            )


@runtime_checkable
class StoreHealthPort(Protocol):
    """One store, asked whether it is there."""

    def health(self) -> StoreHealth:
        """Ask the store the cheapest question it can answer, and report what happened."""
        ...
