"""FastAPI app: an SSE ask endpoint over the graph, plus the built React UI.

The HTTP layer owns no logic. It builds the same graph the CLI builds and
forwards `Gateway.stream()` onto the wire — every step timing you see in the
browser is a custom event some node emitted, not something this file measured.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette import EventSourceResponse, ServerSentEvent

from .. import climate, gateway, query, store
from ..main import _load_env

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _load_env()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is not set. Put it in .env or export it.")
    query.run_sql("SELECT 1")  # fail at boot, not on the first question

    sessions = store.build()
    try:
        await sessions.ping()
    except Exception as exc:  # same treatment as the two checks above
        raise RuntimeError(
            f"Redis unreachable at {getattr(sessions, 'url', '?')} — run `make redis`"
        ) from exc

    app.state.gateway = gateway.Gateway(climate.build_graph(), store_=sessions)
    log.info("graph up")
    try:
        yield
    finally:
        await sessions.close()


app = FastAPI(title="Climate Agent", lifespan=lifespan)


def _sse(event: str, payload: dict) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=json.dumps(payload))


async def _events(
    human: gateway.Gateway, question: str, session_id: str
) -> AsyncIterator[ServerSentEvent]:
    try:
        async for kind, item in human.stream(question, session_id):
            yield _sse(kind, item.model_dump())
    except TimeoutError as exc:
        yield _sse("error", {"message": str(exc)})
    except Exception as exc:
        log.exception("ask failed")
        yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
    # EventSource reconnects on an unclosed stream, which would re-ask the
    # question, so every path must terminate with `done`.
    yield _sse("done", {})


@app.get("/api/ask")
async def ask(q: str = "", session: str = "") -> EventSourceResponse:
    """One turn of a conversation.

    `session` ties this question to the previous ones; the browser mints it and
    sends the same value every turn. It stays a GET because EventSource cannot
    POST — and there is no body to send anyway, since the history lives server
    side, keyed by this id.
    """
    question = q.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")
    return EventSourceResponse(
        _events(app.state.gateway, question, session.strip() or uuid.uuid4().hex)
    )


@app.get("/api/sessions")
async def list_sessions() -> list[dict]:
    """Every conversation the process remembers, newest first.

    Deliberately unscoped: this is a shared demo, so one visitor sees everyone's
    conversations. Add a per-user key here if that ever stops being acceptable.
    """
    human = app.state.gateway
    in_flight = human.pending_sessions()

    rows = [
        {
            "id": c.id,
            "title": c.title,
            "turns": len(c.exchanges),
            "updated_at": c.updated_at,
            # Additive, so an older frontend simply ignores it.
            "pending": len(in_flight.get(c.id, ((), 0.0))[0]),
        }
        for c in await human.conversations()
    ]

    # A conversation is only stored once an answer lands, so one whose *first*
    # answer is still coming exists nowhere else. Without this it would be
    # invisible in the rail for as long as it takes to answer — no way to see it
    # working, and no row to click your way back to.
    stored = {row["id"] for row in rows}
    for session_id, (questions, started_at) in in_flight.items():
        if session_id in stored:
            continue
        rows.append(
            {
                "id": session_id,
                "title": store.title_for(questions[0]),
                "turns": 0,
                "updated_at": started_at,
                "pending": len(questions),
            }
        )

    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """One conversation's transcript, for resuming it in the UI."""
    human = app.state.gateway
    conversation = await human.conversation(session_id)
    pending = human.pending(session_id)
    if conversation is None and not pending:
        raise HTTPException(status_code=404, detail="No such conversation")
    return {
        "id": session_id,
        "title": conversation.title if conversation else "New conversation",
        "exchanges": [
            {"question": e.question, "answer": e.answer, "caveats": e.caveats}
            for e in (conversation.exchanges if conversation else [])
        ],
        # Questions still being answered — the UI shows these as running turns
        # so a conversation you return to mid-answer has no hole in it.
        "pending": pending,
    }


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> Response:
    """Forget a conversation — transcript, model history and all. No undo.

    Idempotent, and deliberately never 404s: the rail is a snapshot, so the row
    you clicked may already have expired or been deleted from another tab.
    Reporting that as a failure would leave a row nobody can get rid of.
    """
    await app.state.gateway.delete_conversation(session_id)
    return Response(status_code=204)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


_static_dir = Path(
    os.environ.get("STATIC_DIR", Path(__file__).parents[3] / "frontend" / "dist")
)
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
else:  # dev: `npm run dev` serves the UI on :5173 and proxies /api here
    log.warning(
        "no built frontend at %s; run `make build`, or `make ui` for the Vite dev "
        "server on :5173",
        _static_dir,
    )
