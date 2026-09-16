"""The three routes, and nothing else. ``POST /api/ask`` is the one that composes.

Purity: edge.

The spine's HTTP surface is three routes; this epic ships two of them --
``POST /api/ask`` and ``GET /api/health`` -- because ``POST /api/read`` is the on-request
long-form reading and there is no long-form reading in an epic with no prose. Nothing
under ``/api/backoffice/*`` exists, and the refresh is deliberately **not** a route: it is
a scheduled command, never reader-reachable (AD-21).

**The engine authenticates nothing** (AD-24). It owns no session, no login and no user
store. The caller identity is read off a header the surrounding platform sets, recorded
with the answer, and a request arriving without one is answered normally and recorded as
anonymous *with the reason* -- there is no 401 here to write, because there is nothing
here that could issue a credential.

**The request carries no lens** (AD-23). ``AskRequest`` has no such field and the schema
FastAPI publishes therefore has none either, which is how "the lens is a view over one
answer, never an input to it" reaches the client rather than staying an internal rule.

**The app is built around an engine, not around a module global.** ``create_app`` takes
the engine, so a test drives the real routes over a real provisioned database with no
environment variable set and no process-wide state to reset between cases.

**Both handlers are ``async def``, and that is a storage decision rather than a style
one.** A sqlite connection belongs to the thread that opened it, and Starlette runs a
plain ``def`` handler on a worker thread from a pool -- which would hand the read model
and the record store to whichever thread the pool happened to pick, and sqlite would
refuse. ``async def`` keeps every store access on the one thread running the loop, which
is also what AD-20's single-writer record store wants: one writer, in one place, in one
order. The engine answers from a local file with no socket on the answer path (AD-9a), so
there is no call here long enough to be worth a thread.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import FastAPI, Header
from pydantic import BaseModel, Field, field_validator

from askai.api.ask import Ask, answer_question
from askai.api.engine import Engine
from askai.api.wire import Json, ask_response, health_response
from askai.messages.lang import Lang
from askai.narrate.package import PackageSource

__all__ = ["ASK_ROUTE", "HEALTH_ROUTE", "IDENTITY_HEADER", "AskRequest", "create_app"]

ASK_ROUTE: Final = "/api/ask"
HEALTH_ROUTE: Final = "/api/health"

#: The header the surrounding platform asserts a caller on. A header rather than a body
#: field on purpose: the identity is asserted *about* the request by the platform in
#: front of the engine, and a client that could put it in the body could choose it.
IDENTITY_HEADER: Final = "X-Caller-Id"


class AskRequest(BaseModel):
    """``{question, lang, sources, conversation_id}`` -- and no lens (AD-23).

    ``sources`` defaults to the approved layer alone. The default is the published data
    rather than "everything available": external content is always caveated and never
    unasked-for, so selecting it is a thing the caller does deliberately (FR-84, FR-88).
    """

    question: str = Field(min_length=1)
    lang: Lang
    sources: tuple[PackageSource, ...] = (PackageSource.APPROVED,)
    conversation_id: str | None = None

    @field_validator("sources")
    @classmethod
    def _at_least_one_source(cls, sources: tuple[PackageSource, ...]) -> tuple[PackageSource, ...]:
        if not sources:
            raise ValueError(
                "select at least one source; selecting none is not a narrower question"
            )
        # De-duplicated rather than refused: asking for the approved layer twice is a
        # client quirk, and answering it twice would return two identical packages and
        # write their row ids into the record twice.
        return tuple(dict.fromkeys(sources))


def create_app(engine: Engine) -> FastAPI:
    """The application, wired to *engine*. One engine per process; one app per engine."""
    app = FastAPI(
        title="Ask AI answer engine",
        # The structured answer package is the contract; a version here would be a second
        # place for the shape's version to live, and `spec_version` already carries it.
        docs_url=None,
        redoc_url=None,
    )

    @app.post(ASK_ROUTE)
    async def ask(
        request: AskRequest,
        caller: Annotated[str | None, Header(alias=IDENTITY_HEADER)] = None,
    ) -> dict[str, Json]:
        """The answer, and the only route that composes anything."""
        answered = answer_question(
            engine,
            Ask(
                question=request.question,
                lang=request.lang,
                sources=request.sources,
                conversation_id=request.conversation_id,
                asserted_identity=caller,
            ),
        )
        return ask_response(answered.response)

    @app.get(HEALTH_ROUTE)
    async def health() -> dict[str, Json]:
        """Liveness, plus read-model freshness (AD-21).

        Both facts, separately. Reachability answers *is the engine there*; the freshness
        block answers *how old is what it is serving*, and a copy that is stale is being
        served correctly rather than being an outage.
        """
        return health_response(
            tuple(store.health() for store in engine.stores),
            engine.freshness.freshness(engine.now()),
        )

    return app
