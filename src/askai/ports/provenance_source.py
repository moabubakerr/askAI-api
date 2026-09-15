"""``SourceCatalogue`` -- the port ``assemble/`` resolves a ``source_ref`` against.

Purity: declaration only. No implementation lives here and none may.

AD-7 makes ``assemble/`` the closed-world enforcement point: it *"rejects any element
whose source_ref does not resolve against the loaded knowledge base, and the rejection
is a typed Degradation, not a silent drop."* Resolving means asking the loaded published
layer whether that reference names something it actually holds, and the loaded published
layer lives behind an adapter.

``assemble/`` may never import ``adapters/`` (the contract in ``pyproject.toml`` fails
the build on it), so the question is asked through this protocol. The narrowness is the
point: the assembler may ask *does this resolve*, and it may ask nothing else -- it
cannot reach through the port for a value, which would make it a second figure source
and break AD-3.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["SourceCatalogue"]


class SourceCatalogue(Protocol):
    """Whether a ``source_ref`` names something the loaded published layer holds."""

    def resolves(self, source_ref: str) -> bool:
        """``True`` when *source_ref* resolves; ``False`` when it does not.

        Total by contract. An implementation that raises on an unknown reference would
        turn AD-7's typed rejection into an exception the assembler has to guess the
        meaning of, and a bare ``except`` there is the shape AD-15 forbids.
        """
        ...
