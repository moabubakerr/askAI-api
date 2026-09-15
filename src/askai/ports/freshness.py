"""``FreshnessPort`` -- how old the served copy of the published layer is.

Purity: declarations only.

NFR-7 asks for two things that look like one: republished content must reach readers
with no code change and no deployment, and the *age* of what they are reading must be
visible. The first is a property of the refresh job; the second is this type, and it has
to travel further than the job does -- ``GET /api/health`` reports it, and every answer
package carries the same block, so the health check and the answer can never disagree
about what the engine is serving.

So the type is declared here rather than in ``refresh/``. ``refresh/`` is IO and never
on the answer path; a pure layer that had to import it to name the block it carries
would put an out-of-band job in the answer path's import graph for the sake of a
dataclass. The producer lives in ``refresh/`` and the value is handed in.

``stale`` is computed once, by the producer, against the threshold in
``rules/data/refresh-freshness.yaml``, and carried -- not recomputed per caller. Two
call sites each applying their own threshold is how health reports green while the
answer says stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["Freshness", "FreshnessPort"]


@dataclass(frozen=True, slots=True)
class Freshness:
    """How old the copy being served is, and whether that is too old.

    ``refreshed_at`` is the moment the last *successful* refresh committed, never the
    moment the last attempt started: a failed attempt leaves the previous contents in
    place, and reporting its clock would say the engine is serving something newer than
    it is. ``None`` means no refresh has ever succeeded against this read model, which
    is stale rather than fresh -- an empty copy is not an up-to-date one.
    """

    refreshed_at: datetime | None
    stale: bool
    #: Seconds between ``refreshed_at`` and the moment the block was built. ``None``
    #: exactly when ``refreshed_at`` is, so the two fields cannot disagree.
    age_seconds: float | None

    def __post_init__(self) -> None:
        if (self.refreshed_at is None) != (self.age_seconds is None):
            raise ValueError(
                "freshness carries an age without a refresh time, or the reverse; the "
                "age is measured from the refresh time and cannot outlive it"
            )
        if self.refreshed_at is None and not self.stale:
            raise ValueError(
                "a read model that has never been refreshed is stale; reporting it as "
                "fresh would make an empty copy indistinguishable from a current one"
            )


@runtime_checkable
class FreshnessPort(Protocol):
    """Where the freshness block comes from. Read-only, and takes ``now`` explicitly.

    ``now`` is an argument because the engine's pure layers are forbidden from reading
    the clock and its tests are forbidden from depending on one; an implementation that
    called ``datetime.now()`` inside would make every staleness assertion a race.
    """

    def freshness(self, now: datetime) -> Freshness:
        """The age of the copy being served, as of *now*."""
        ...
