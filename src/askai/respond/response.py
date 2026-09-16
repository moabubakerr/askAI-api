"""The response: a conversation id, the ordered packages, and one freshness block.

Purity: orchestration; orders packages, never mutates one.

The spine's contract is *"one request shape, one response shape, for all three source
selections; Combined differs only by returning two packages."* This is that shape, and it
is generic in the package type for the same reason ``order.py`` is: ``respond/`` may not
import the layer that builds packages, so the only honest spelling of "a response carries
packages" is one that never says what a package is.

**One freshness block, on the response rather than on each package.** NFR-7 asks for the
age of the served copy to be visible; AD-21 asks health and the answer to agree about it.
A block per package would be two readings of one file taken microseconds apart, which can
differ across a refresh -- and a client seeing two different answers to "how old is this"
has no way to choose between them.

**The conversation id is carried, not owned.** The engine holds no session store (AD-24).
The id is whatever the caller sent, or one minted for this exchange so the client has
something to send next time; nothing here remembers it.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.ports.freshness import Freshness

__all__ = ["Response"]


@dataclass(frozen=True, slots=True)
class Response[T]:
    """One answered request: the ordered packages and the age of what answered it."""

    conversation_id: str
    packages: tuple[T, ...]
    freshness: Freshness

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError(
                "a response carries a conversation id; a blank one is a client with "
                "nothing to send back, which is the follow-up that cannot inherit"
            )
        if not self.packages:
            raise ValueError(
                "a response carries at least one package; an empty list says nothing "
                "about what the engine decided, and every request reaches a decision -- "
                "an answer, a refusal or a clarification"
            )
