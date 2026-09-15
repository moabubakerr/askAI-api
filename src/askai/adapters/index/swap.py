"""The swap: one reference, rebound whole, never blocking a reader or a live write.

Purity: IO by package; in fact it holds one reference and a lock.

"Atomically swapped" is the load-bearing claim of AD-13 and AD-20, and it is worth
saying exactly what carries it, because the word *atomic* is usually a hope:

1. **A generation is already a complete, immutable object before the swap exists.** It
   was built into its own file (:mod:`askai.adapters.index.build`) and read whole into
   memory (:mod:`askai.adapters.index.generation`). Publishing it changes no bytes and
   opens no file.
2. **The swap is one attribute rebinding.** ``self._current = generation`` -- a single
   store of a reference. A reader that read the attribute a moment earlier holds the
   previous generation, which is a frozen object nothing can now alter, and keeps
   answering out of it for as long as it holds it.
3. **Readers take no lock.** The lock here serialises *writers* only: two refreshes
   finishing at once must not each believe they superseded the same generation. A reader
   never waits for a swap, so a rebuild cannot stall a request -- and a rebuild takes no
   database write lock that a live request could be waiting on either, because it wrote
   a different file entirely.

What this deliberately does **not** do is reference counting. A generation is retired
when the caller that superseded it says so, and the file is only removed then. Anything
holding the old generation is holding a fully-loaded in-memory object and does not read
the file again, so retiring a file never affects a reader mid-request -- which is the
property that lets retirement be a simple, explicit call rather than a lifetime puzzle.

``hold()`` is the shape a request should use: one reference taken at the start, used for
the whole request, and no way to accidentally re-read the holder halfway through and get
a different index than the one the earlier half of the answer came from.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from askai.adapters.index.generation import IndexGeneration

__all__ = ["SwappableIndex"]


class SwappableIndex:
    """Holds the current generation and lets a refresh replace it by reference.

    Not a dataclass and not frozen, because its whole purpose is the one mutable
    reference in the design. It is a *cell*, not shared mutable state in AD-2's sense:
    what it holds is only ever replaced whole with another immutable value, never
    mutated, and nothing reads it expecting to accumulate anything.
    """

    __slots__ = ("_current", "_lock")

    def __init__(self, generation: IndexGeneration) -> None:
        self._current = generation
        self._lock = threading.Lock()

    def current(self) -> IndexGeneration:
        """The generation in force right now.

        Lock-free and constant-time: one attribute read, which the interpreter performs
        as a single load of a reference. The value returned is frozen, so what a caller
        does with it afterwards is unaffected by any swap that follows.
        """
        return self._current

    @contextmanager
    def hold(self) -> Iterator[IndexGeneration]:
        """One generation, for the lifetime of the block. The shape a request uses.

        Deliberately a context manager rather than a plain getter used twice: the failure
        it prevents is a request reading the holder again halfway through and composing
        half an answer from one index and half from the next.
        """
        yield self._current

    def swap(self, generation: IndexGeneration) -> IndexGeneration:
        """Publish *generation* and return the one it superseded.

        The lock is held for the rebinding alone -- no IO, no loading, no scanning -- so
        two refreshes finishing together are ordered rather than interleaved, and each is
        told exactly which generation it replaced. The caller decides when to retire the
        superseded file; readers still holding it are unaffected either way.
        """
        with self._lock:
            previous = self._current
            self._current = generation
            return previous

    def retire(self, generation: IndexGeneration) -> None:
        """Delete a superseded generation's file. Refuses to delete the current one.

        A caller that retired the live generation would leave the process answering
        correctly from memory and unable to reload after a restart -- a fault that would
        not surface until the worst possible moment.
        """
        if generation is self._current:
            raise ValueError(
                "that generation is the one in force; retire the generation `swap` "
                "returned, never the one it published"
            )
        generation.path.unlink(missing_ok=True)
