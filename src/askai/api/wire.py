"""The response on the wire: the spine's JSON, built from the finished values.

Purity: edge.

The shape is the spine's and is not negotiable here -- ``{conversation_id, packages[],
freshness}``, a package carrying ``{provenance, kind, spec, elements[], chartable,
caveat, degradations[]}``, and every element carrying a ``class``, a ``role`` and a
``source_ref``.

**``class`` and ``role`` are two fields and stay two fields** (AD-6). They answer
different questions -- where the content came from, and what job it does -- and an
``analysis`` role filled from a datapoint note is class ``attributed`` while the same role
filled from an article is class ``article``. A single ``kind`` field on the wire would
collapse them at the last possible moment, which is the worst place to lose the
distinction FR-96 exists to keep.

**The ``spec`` block is echoed deliberately.** It is what the corpus asserts on and what
the record stores -- one artifact, several jobs (AD-1) -- so it is serialised from the
same frozen value the record serialises, never re-derived from the answer.

**No number is written here.** Every figure a reader sees is already inside an element's
composed text, written once by the single ``Formatter`` (AD-18). This module moves strings
and enum values; the one numeric field it emits, ``age_seconds``, is a diagnostic on the
freshness block and not a published value.
"""

from __future__ import annotations

from collections.abc import Callable

from askai.domain.scope import DeclaredBenchmarks, Named, National
from askai.domain.spec import (
    Bound,
    Deferred,
    Exact,
    LastN,
    Latest,
    QuerySpec,
    Range,
    Unbound,
)
from askai.narrate.package import AnswerPackage
from askai.ports.freshness import Freshness
from askai.ports.store_health import StoreHealth
from askai.respond.response import Response

__all__ = ["ask_response", "freshness_block", "health_response", "package_block", "spec_block"]

type Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]


def ask_response(response: Response[AnswerPackage]) -> dict[str, Json]:
    """``{conversation_id, packages[], freshness}`` -- the whole of ``POST /api/ask``."""
    return {
        "conversation_id": response.conversation_id,
        "packages": [package_block(package) for package in response.packages],
        "freshness": freshness_block(response.freshness),
    }


def package_block(package: AnswerPackage) -> dict[str, Json]:
    """One package. Ordered by ``respond/``, built by ``narrate/``, serialised here."""
    return {
        "provenance": package.source.value,
        "kind": package.kind.value,
        "spec": spec_block(package.spec, package),
        "elements": [
            {
                "class": placed.element.element_class.value,
                "role": placed.role.value,
                "text": placed.element.content,
                "source_ref": placed.element.source_ref,
            }
            for placed in package.elements
        ],
        "chartable": {
            "available": package.chartable.available,
            "default_view": package.chartable.default_view,
            "alternate_views": list(package.chartable.alternate_views),
        },
        "caveat": package.caveat,
        "reason": package.reason,
        "degradations": [
            {
                "kind": degradation.kind,
                "where": degradation.where,
                "detail": degradation.detail,
            }
            for degradation in package.degradations
        ],
    }


def spec_block(spec: QuerySpec, package: AnswerPackage) -> dict[str, Json]:
    """The frozen spec, plus what a deferred period actually resolved to.

    Both, and labelled differently: ``period`` is the request as ``compile/`` froze it and
    ``resolved_period`` is what ``execute/`` answered it at. Reporting only the second
    would hide that the reader said "now"; reporting only the first would leave the
    commonest question about an old answer -- *which period is this?* -- unanswerable.
    """
    scope = spec.country_scope
    block: dict[str, Json] = {
        "spec_version": spec.spec_version,
        "today": spec.today.isoformat(),
        "detail_id": _state(spec.detail, _identity),
        "period": _state(spec.period, _period_request),
        "country_scope": _state(scope, _scope),
        "measure": _state(spec.measure, _identity),
        "operation": _state(spec.operation, _identity),
        "bound_by": {
            binding.field.value: binding.precedence.value for binding in package.bindings
        },
        "resolved_period": _resolved(package),
    }
    if isinstance(scope, Bound) and isinstance(scope.value, Named):
        block["countries"] = [country for country in sorted(scope.value.countries)]
    return block


def freshness_block(freshness: Freshness) -> dict[str, Json]:
    """NFR-7's visible staleness. The same block ``GET /api/health`` reports, from the
    same port, so the answer and the health check can never disagree about the copy."""
    return {
        "refreshed_at": (
            None if freshness.refreshed_at is None else freshness.refreshed_at.isoformat()
        ),
        "stale": freshness.stale,
        "age_seconds": freshness.age_seconds,
    }


def health_response(stores: tuple[StoreHealth, ...], freshness: Freshness) -> dict[str, Json]:
    """Liveness plus read-model freshness (AD-21), reported as two separable facts.

    ``status`` is ``ok`` only when every store answered. Staleness does **not** make the
    service unhealthy: a stale copy is being served correctly and the freshness block
    already says how old it is, whereas a store that will not answer is an outage. An
    endpoint that folded the two would page the wrong person.
    """
    return {
        "status": "ok" if all(store.reachable for store in stores) else "unavailable",
        "stores": [
            {"name": store.name, "reachable": store.reachable, "detail": store.detail}
            for store in stores
        ],
        "freshness": freshness_block(freshness),
    }


# --------------------------------------------------------------------------- helpers


def _state(state: object, written: Callable[[object], Json]) -> Json:
    """One field, in whichever of AD-1's three states it is in.

    The state is on the wire rather than flattened away: ``Deferred`` and ``Unbound`` mean
    entirely different things -- *"perfectly clear, needs the data"* and *"not specific
    enough"* -- and a client shown a bare ``null`` for both would render a clarification
    where an answer was coming.
    """
    match state:
        case Bound(value=value):
            return {"bound": written(value)}
        case Deferred(request=request):
            return {"deferred": written(request)}
        case Unbound(reason=reason):
            return {"unbound": reason}
        case _:
            raise TypeError(f"{type(state).__name__} is not a spec field state")


def _identity(value: object) -> Json:
    return str(value)


def _period_request(request: object) -> Json:
    """The period the reader asked for, in the shape they asked for it."""
    match request:
        case Exact(period=period):
            return {"exact": period.value}
        case Range(start=start, end=end):
            return {"range": {"start": start.value, "end": end.value}}
        case Latest():
            return {"latest": True}
        case LastN(n=count, grain=grain):
            return {"last_n": {"n": count, "grain": grain.value}}
        case _:
            raise TypeError(f"{type(request).__name__} is not a period request")


def _scope(scope: object) -> Json:
    """The country scope as a query shape, never as a country value (AD-5)."""
    match scope:
        case National():
            return "national"
        case Named():
            return "named"
        case DeclaredBenchmarks():
            return "benchmarks"
        case _:
            raise TypeError(f"{type(scope).__name__} is not a country scope")


def _resolved(package: AnswerPackage) -> Json:
    resolution = package.resolution
    if resolution is None or resolution.period is None:
        return None
    return resolution.period.value


