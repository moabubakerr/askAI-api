"""The freshness block: how old the served copy is, and whether that is too old.

Purity: IO, never on the answer path.

NFR-7's visible-staleness half. The block itself is declared in
:mod:`askai.ports.freshness` so health and the answer package can both carry it without
importing an out-of-band job; this module is the producer, and it is the only place the
threshold is applied.

The threshold is read from ``rules/data/refresh-freshness.yaml`` through
``rules().value(...)`` rather than written here (AD-11). That is what makes "the engine
considers a copy stale after a day and a bit" a sentence a steward can change in a data
file, next to the reason it says so, instead of a number in a diff.

``now`` is always an argument. A producer that read the clock itself would make every
staleness test a race, and would make the answer package's block and the health check's
block disagree by however long the request took.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from askai.ports.freshness import Freshness
from askai.refresh.state import RefreshState, read_state
from askai.rules.loader import rules

__all__ = [
    "NEVER_REFRESHED",
    "STALE_AFTER_RULE",
    "FreshnessRuleError",
    "StateFileFreshness",
    "freshness_of",
    "stale_after",
]

#: The rule carrying the staleness threshold. Named so a rename in the data file fails
#: loudly at startup rather than reporting everything fresh.
STALE_AFTER_RULE: Final = "R-REFRESH-STALE-AFTER"
_HOURS_KEY: Final = "stale_after_hours"

#: What a read model that has never been refreshed reports. Stale, with no age: there is
#: no moment to measure from, and "fresh by default" over an empty copy is the failure
#: the flag exists to prevent.
NEVER_REFRESHED: Final = Freshness(refreshed_at=None, stale=True, age_seconds=None)


class FreshnessRuleError(RuntimeError):
    """The staleness threshold is not a number of hours, so no copy can be judged."""


def stale_after() -> timedelta:
    """How long a copy may go unrefreshed before it is stale, from the rule file."""
    hours = rules().value(STALE_AFTER_RULE, _HOURS_KEY)
    if not isinstance(hours, int) or isinstance(hours, bool):
        raise FreshnessRuleError(
            f"{STALE_AFTER_RULE} carries `{_HOURS_KEY}` as {hours!r}; it is a number of "
            "hours and must be an integer"
        )
    return timedelta(hours=hours)


def freshness_of(
    state: RefreshState | None, now: datetime, threshold: timedelta | None = None
) -> Freshness:
    """The freshness block for *state* as of *now*.

    *state* of ``None`` is a read model no refresh has ever succeeded against, which is
    stale. *threshold* of ``None`` reads the rule; it is injectable so a test can state
    the threshold it means rather than depending on the shipped one.
    """
    if state is None or state.refreshed_at is None:
        return NEVER_REFRESHED
    window = stale_after() if threshold is None else threshold
    age = now - state.refreshed_at
    return Freshness(
        refreshed_at=state.refreshed_at,
        stale=age > window,
        age_seconds=age.total_seconds(),
    )


@dataclass(frozen=True, slots=True)
class StateFileFreshness:
    """A :class:`askai.ports.freshness.FreshnessPort` over the refresh state file.

    Reads the file on every call rather than caching it. That is the whole mechanism
    behind NFR-7's "no code change and no deployment": the scheduled job replaces the
    file, the next health check reads the new one, and no process restarts.
    """

    path: Path
    #: Injectable for a test; ``None`` reads the rule.
    threshold: timedelta | None = None

    def freshness(self, now: datetime) -> Freshness:
        return freshness_of(read_state(self.path), now, self.threshold)
