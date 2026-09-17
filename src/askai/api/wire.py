"""The response on the wire: the spine's JSON, built from the finished values.

Purity: edge.

The shape is the spine's and is not negotiable here -- ``{conversation_id, packages[],
freshness}``, a package carrying ``{provenance, agent, kind, spec, elements[], chartable,
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
from askai.respond.external import ExternalAnswer
from askai.respond.response import Response

__all__ = [
    "ask_response",
    "external_block",
    "freshness_block",
    "health_response",
    "package_block",
    "spec_block",
]

type Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]


def ask_response(
    response: Response[AnswerPackage], external: ExternalAnswer | None = None
) -> dict[str, Json]:
    """``{conversation_id, packages[], external, freshness}`` -- the whole of ``/api/ask``.

    **Two answers, under two headings** (FR-85, Story 9.7). The approved half is
    ``packages`` and the external half is ``external``, and they are separate keys of
    separate shapes because they are separate types all the way down: there is no
    serialiser here that could put an external figure in a package or a package's figure
    in the external block, since neither type has a field the other's content would fit.
    Approved first, in the object and in the reading order.

    ``external`` is **absent** when the admission admitted no external agent, exactly as
    the external package is absent from ``packages``. The key's presence is the statement
    that an external agent was asked; an external agent that was asked and could not
    answer is present, saying so, with its caveat and its reason -- which is a different
    fact and reads as one.
    """
    body: dict[str, Json] = {
        "conversation_id": response.conversation_id,
        "packages": [package_block(package) for package in response.packages],
        "freshness": freshness_block(response.freshness),
    }
    if external is not None:
        body["external"] = external_block(external)
    return body


def external_block(external: ExternalAnswer) -> dict[str, Json]:
    """The third party's half. Serialised, never merged.

    Every field is copied across verbatim. Nothing here reads a package, computes a
    difference, reconciles a disagreement or decides which half is right -- the two
    arguments this function could take to do any of that are not both available to it,
    because it takes one (FR-86).

    ``caveat`` is emitted before ``prose`` and is never conditional: a client that renders
    the object in key order shows the warning above the text, and a client that renders
    only some keys has to go out of its way to drop it.
    """
    check = external.check
    return {
        "provenance": external.source.value,
        "agent": external.agent,
        "caveat": external.caveat,
        "outcome": external.outcome.value,
        "prose": external.prose or None,
        "reason": external.reason or None,
        # `null` means **no check ran**, and a client may not read it as a clean result.
        # When one does run it carries its own limits (FR-88a), which travel with it
        # rather than being looked up by a client that might not.
        "check": None
        if check is None
        else {
            "band": check.band,
            "limits": check.limits,
            "found": list(check.found),
            "beyond": list(check.beyond),
            "flagged": check.flagged,
        },
        # A diagnostic, like ``freshness.age_seconds`` and for the same reason: it is
        # how long the engine waited, never a published value, so it is emitted as the
        # number it is rather than composed by the ``Formatter`` that owns every figure
        # a reader sees (AD-18). It is the measurement ``[ASSUMPTION A4]`` is tested
        # against (NFR-3).
        "elapsed_seconds": external.elapsed_seconds,
        "degradations": [
            {
                "kind": degradation.kind,
                "where": degradation.where,
                "detail": degradation.detail,
            }
            for degradation in external.degradations
        ],
    }


def package_block(package: AnswerPackage) -> dict[str, Json]:
    """One package. Ordered by ``respond/``, built by ``narrate/``, serialised here."""
    return {
        "provenance": package.source.value,
        # FR-83, Story 9.5. Two fields, not one: `provenance` is the machine-readable
        # code a client routes on, and `agent` is the rendered sentence a reader reads,
        # already in their language. A client that had only the code would have to hold
        # its own bilingual label table -- a second place for wording to live, outside
        # the one reviewable catalogue (FR-63a) and free to drift from it.
        "agent": package.agent,
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
        **_refusal(package),
        "degradations": [
            {
                "kind": degradation.kind,
                "where": degradation.where,
                "detail": degradation.detail,
            }
            for degradation in package.degradations
        ],
    }


def _refusal(package: AnswerPackage) -> dict[str, Json]:
    """The machine-readable half of a refusal or a clarification (FR-38, Story 2.7).

    ``reason`` is the sentence the reader reads, already in their language. These two are
    what a *client* acts on: ``reason_id`` is the catalogue id the sentence was worded
    from, so a wording fix in ``messages/data`` does not move it, and ``refusal_code`` is
    which of FR-38's six causes this is -- what refusals are counted by. A code that never
    reaches the client is not a stable machine code; it is an internal label.

    **Present exactly when they are populated, rather than as two nulls on every answer.**
    A refusal carries both, a clarification carries the id and no code (a question asked
    well is not a failure and is not counted as one), and an answer carries neither. That
    is the same conditional shape ``spec_block`` uses for ``countries`` -- and it keeps
    the key set of an answer package exactly what the schema test already pins.

    No ``spec_version`` bump goes with this. That field versions the *``QuerySpec``*
    shape -- the fields ``compile/`` binds -- and is asserted at 1 by the corpus and by
    the record store's schema; these two fields are on the package beside the spec, not
    in it, and nothing already on the wire changes meaning or disappears.
    """
    block: dict[str, Json] = {}
    if package.reason_id is not None:
        block["reason_id"] = package.reason_id
    if package.refusal_code is not None:
        block["refusal_code"] = package.refusal_code.value
    return block


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


