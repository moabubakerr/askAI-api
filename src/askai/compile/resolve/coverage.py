"""The span a question asks about, as the coverage signal reads it.

Purity: pure.

Story 2.4's period-coverage signal asks *"does the candidate publish rows spanning the
asked range"*. Turning that into something a veto may act on takes two decisions, and both
are about how *not* to be wrong.

**A window of dates, not an enumerated list of periods.** A ``Range`` is expanded by
comparing calendar bounds -- the same way ``execute/`` selects rows for one (``latest.py``)
-- rather than by walking from one period to the next. Two spellings of "which periods
does this range contain" is how the resolver comes to disagree with the executor about
what the reader asked for, and the comparison here is deliberately the comparison there.

**The veto fires on publishing *nothing* in the window, not on publishing it
incompletely.** A detail with a one-year gap in the middle of a four-year span can still
answer the question -- with the gap noted, which is ``assemble/``'s job -- so removing it
here would be the resolver deciding a completeness question that is not its to decide. A
detail publishing *no* row of the asked grain anywhere in the window is a different case:
it cannot answer the question as asked at all, the catalogue knows that definitely, and
that is what a veto is for.

**A deferred period expands to no window.** ``Latest`` and ``LastN`` are ``Deferred``
(AD-1): the reader was perfectly clear and *which* period they name is a fact about the
rows, which ``execute/`` resolves against FR-8. Expanding them here would mean guessing
which periods exist, and a candidate vetoed for not publishing a period this module
invented would be removed for failing a test nobody could pass. So they produce no window,
the signal stays silent, and the veto cannot fire on the commonest question there is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from askai.domain.period import Grain, Period
from askai.domain.spec import Exact, LastN, Latest, PeriodSpec, Range

__all__ = ["PeriodWindow", "window_for"]


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    """The calendar span a question asks about, and the grain it asks at.

    ``grain`` is carried because coverage and grain are different questions about the same
    request: a detail may publish rows inside the window and none of them at the interval
    the reader named. The grain veto handles the second; this window is about the first.
    """

    start: date
    end: date
    grain: Grain

    def contains(self, period: Period) -> bool:
        """Does *period* sit at this window's grain and inside its bounds?

        Bounds compared as the executor compares them: the period must fall wholly within
        the window, so a yearly row is not admitted by a question about one of its months.
        """
        return (
            period.grain is self.grain
            and self.start <= period.start
            and period.end <= self.end
        )

    def covered_by(self, published: frozenset[Period]) -> bool:
        """Does *published* contain any period this window admits?

        Any, deliberately, not all -- see this module's docstring. This is the question a
        veto may act on: a detail publishing nothing here cannot answer the question as
        asked, and one publishing some of it can answer with a gap noted.
        """
        return any(self.contains(period) for period in published)


def window_for(request: PeriodSpec | None) -> PeriodWindow | None:
    """The window *request* asks about, or ``None`` when it cannot be known here.

    ``None`` for ``Latest``, ``LastN`` and no request at all: each is either deferred or
    absent, and in every case the honest answer is that this signal has nothing to say.
    """
    match request:
        case Exact(period=period):
            return PeriodWindow(start=period.start, end=period.end, grain=period.grain)
        case Range(start=start, end=end):
            # `Range` already refuses a start and end of different grains and a span that
            # runs backwards, so the bounds are taken as given rather than re-checked.
            return PeriodWindow(start=start.start, end=end.end, grain=start.grain)
        case Latest() | LastN():
            return None
        case _:
            return None
