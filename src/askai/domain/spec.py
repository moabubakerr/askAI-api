"""``QuerySpec`` -- the single binding artifact, and the three states a field can be in.

Purity: pure, imports nothing outside ``domain/``.

A ``QuerySpec`` is produced exactly once per answerable question, before any data
access, and no layer past ``compile/`` may set, widen or reinterpret a field (AD-1).
Both halves of that are types here: the spec is frozen, and every field is a closed
set rather than an open string.

**A field has three states, not two.** ``Bound`` -- the reader was specific and it is
resolved. ``Unbound(reason)`` -- the reader was not specific enough, so the answer is a
clarification or a refusal. ``Deferred`` -- the reader was perfectly clear and the value
simply cannot be known without the data. *"What is inflation now?"* names ``Latest``,
which is determinate yet unresolvable in a pure layer; ``execute/`` resolves it against
FR-8 and records what it resolved to (Story 1.12).

Collapsing ``Deferred`` into ``Unbound`` would make the commonest question in the system
look ambiguous; collapsing it into ``Bound`` would drag a data dependency into
``compile/``. ``period_field`` below is the one place that decides which state a period
request takes, and ``QuerySpec.__post_init__`` re-checks it, so a spec built by hand
cannot carry the collapse either -- unrepresentable rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from askai.domain.period import Grain, Period
from askai.domain.scope import CountryScope

__all__ = [
    "SPEC_VERSION",
    "Bound",
    "Deferred",
    "Exact",
    "FieldState",
    "LastN",
    "Latest",
    "Measure",
    "Operation",
    "PeriodSpec",
    "QuerySpec",
    "Range",
    "Unbound",
    "period_field",
    "requires_data_to_resolve",
]

#: The serialised spec's shape version -- monotonic, and on the response, the answer
#: record and the corpus entry alike. A shape change increments it, and the corpus
#: runner rejects an entry whose version it does not recognise, so stale entries fail
#: loudly instead of passing quietly.
SPEC_VERSION: Final = 1


# --------------------------------------------------------------------- field states


@dataclass(frozen=True, slots=True)
class Bound[T]:
    """The reader was specific, and the value is resolved."""

    value: T


@dataclass(frozen=True, slots=True)
class Unbound:
    """The reader was not specific enough. The answer is a clarification or a refusal."""

    reason: str

    def __post_init__(self) -> None:
        # The reason *is* the answer in this state: a clarification or a refusal with
        # nothing stated is the silent failure AD-15 exists to prevent.
        if not self.reason.strip():
            raise ValueError(
                "Unbound requires a reason; it is what the clarification or refusal says"
            )


@dataclass(frozen=True, slots=True)
class Deferred[T]:
    """The reader was perfectly clear; the value needs data to resolve.

    Carries the *request* -- ``Latest()``, ``LastN(5, Grain.YEARLY)`` -- because the
    request is determinate even though its answer is not. This is what keeps
    ``Deferred`` from being a third flavour of missing.
    """

    request: T


type FieldState[T] = Bound[T] | Unbound | Deferred[T]


# --------------------------------------------------------------------- period request


@dataclass(frozen=True, slots=True)
class Exact:
    """One named period."""

    period: Period


@dataclass(frozen=True, slots=True)
class Range:
    """A named span, inclusive at both ends, at one grain."""

    start: Period
    end: Period

    def __post_init__(self) -> None:
        # Compared through the derived calendar bounds rather than by giving `Period`
        # an ordering: a `Period` is only orderable against another of the same grain,
        # and `start.start` is already the unambiguous way to say "when does it begin".
        if self.start.grain is not self.end.grain:
            raise ValueError(
                f"Range needs one grain, got {self.start.grain} to {self.end.grain}; "
                "a span that changes grain part-way is not a period range"
            )
        if self.start.start > self.end.start:
            raise ValueError(f"Range runs backwards: {self.start} to {self.end}")


@dataclass(frozen=True, slots=True)
class Latest:
    """The most recent actual at or before ``today`` (FR-8). Resolved in ``execute/``."""


@dataclass(frozen=True, slots=True)
class LastN:
    """The last *n* periods at *grain* -- "over the last 5 years".

    This carries a grain, which reads like a violation of "no signature takes a period
    and a grain". It is not. The prohibition is about ``Period``, a *resolved* value
    that owns its grain; ``LastN`` is an unresolved *request*, and the grain is the
    thing being asked for rather than a second opinion about a period that already has
    one. Recorded here because the spine never says it, and someone would otherwise
    rediscover it and "fix" it.
    """

    n: int
    grain: Grain

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError(f"LastN needs at least one period, got n={self.n}")


type PeriodSpec = Exact | Range | Latest | LastN


def requires_data_to_resolve(request: PeriodSpec) -> bool:
    """Does resolving *request* need the published data?

    ``Latest`` is the canonical case. ``LastN`` is grouped with it deliberately: "the
    last five years" is anchored on the most recent published period, so it is exactly
    as unresolvable in a pure layer, and AD-1 reserves ``Deferred`` for precisely that.
    ``Exact`` and ``Range`` name their periods outright and need nothing.

    Exhaustive on purpose. A default of ``False`` would make a ``PeriodSpec`` member
    added later silently ``Bound`` -- which is AD-1's forbidden collapse arriving
    through an omission rather than a decision. A new member fails loudly here instead.
    """
    match request:
        case Latest() | LastN():
            return True
        case Exact() | Range():
            return False
        case _:
            raise TypeError(
                f"{type(request).__name__} is not a PeriodSpec member, or is one that "
                "requires_data_to_resolve has not been told about; say whether it "
                "needs data before it can be put on a spec"
            )


def period_field(request: PeriodSpec) -> FieldState[PeriodSpec]:
    """Wrap *request* in the field state AD-1 requires for it.

    Being a function rather than a convention is the point: there is one place that
    decides, so ``Latest`` cannot arrive at a later layer as ``Bound`` in one code path
    and ``Unbound`` in another.
    """
    if requires_data_to_resolve(request):
        return Deferred(request)
    return Bound(request)


# --------------------------------------------------------------------- closed enums


class Measure(StrEnum):
    """Which quantity is wanted (PRD glossary; the spine's response ``spec.measure``)."""

    ACTUAL = "actual"
    TARGET = "target"
    BASELINE = "baseline"
    CHANGE = "change"


class Operation(StrEnum):
    """What is being asked for over a bound scope. Closed: an operation the bound query
    does not support is refused, never approximated (PRD F2)."""

    VALUE = "value"
    SERIES = "series"
    CHANGE = "change"
    COMPARISON = "comparison"
    EXTREMUM = "extremum"
    RANK = "rank"
    SPREAD = "spread"
    LIST = "list"
    COUNT = "count"
    DEFINITION = "definition"
    EXPLANATION = "explanation"


# --------------------------------------------------------------------- the spec


@dataclass(frozen=True, slots=True)
class QuerySpec:
    """The one artifact an answer is computed from.

    Frozen, and every field closed. There is no API to set, widen or reinterpret a
    field because none is offered -- not because downstream layers are asked not to.

    ``today`` is an explicit field rather than a clock read, so the same question and
    history compile to the same spec on every run (AD-17) and a corpus entry can pin
    the date it was written against.

    Note there is no ``grain`` field. ``Period`` owns its grain.
    """

    detail: FieldState[str]
    period: FieldState[PeriodSpec]
    country_scope: FieldState[CountryScope]
    measure: FieldState[Measure]
    operation: FieldState[Operation]
    today: date
    spec_version: int = SPEC_VERSION

    def __post_init__(self) -> None:
        if self.spec_version != SPEC_VERSION:
            raise ValueError(
                f"spec_version {self.spec_version} does not exist; this build "
                f"serialises version {SPEC_VERSION}"
            )
        # `datetime` is a `date` subclass, so an isinstance check would admit one, and
        # two specs for the same question would then differ by time of day -- AD-17's
        # "the same question compiles to the same QuerySpec" lost to a field nobody
        # looked at. An exact type is the only thing that excludes the subclass.
        if type(self.today) is not date:
            raise TypeError(
                f"today must be a date, not {type(self.today).__name__}; a datetime "
                "carries a time of day and would make the same question compile twice"
            )
        self._check_period_state()

    def _check_period_state(self) -> None:
        """The one field whose state is not the binder's free choice.

        ``period_field`` decides ``Bound`` vs ``Deferred``, but nothing stopped a caller
        constructing ``Bound(Latest())`` directly and collapsing ``Deferred`` into
        ``Bound`` -- the exact thing AD-1 forbids and the docstring above claims is
        unrepresentable. Re-checking here is what makes the claim true.
        """
        match self.period:
            case Bound(value=request) if requires_data_to_resolve(request):
                raise ValueError(
                    f"{type(request).__name__} needs the data to resolve, so it is "
                    "Deferred, never Bound; build the field with period_field()"
                )
            case Deferred(request=request) if not requires_data_to_resolve(request):
                raise ValueError(
                    f"{type(request).__name__} names its periods outright, so it is "
                    "Bound, never Deferred; build the field with period_field()"
                )
            case _:
                return
