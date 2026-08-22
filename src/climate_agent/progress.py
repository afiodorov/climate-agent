"""Step timings, streamed out through LangGraph's custom stream channel.

Emitting is ambient rather than threaded through call signatures: `timed()`
fetches the writer for whichever graph run is currently executing via
`get_stream_writer()`, so the SQL tool — called several frames down, inside the
climate agent's own nested tool-calling loop — needs no reference to the graph,
the session, or the node that is running it. LangGraph gives us this ambient
shape for free via its own `ContextVar`-backed run context.

`get_stream_writer()` raises outside an active graph run (e.g. a test calling a
tool directly), so `_writer()` falls back to a no-op rather than making every
caller guard for that.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from langgraph.config import get_stream_writer

from .schemas import Step

Writer = Callable[[dict], None]


def _noop(_chunk: dict) -> None:
    return None


def writer() -> Writer:
    try:
        return get_stream_writer()
    except RuntimeError:  # not inside a graph run
        return _noop


@asynccontextmanager
async def timed(
    step: str, label: str, detail: str | None = None
) -> AsyncIterator[None]:
    """Bracket a stage: emit `start`, then `done` with the elapsed time.

    The `done` event fires even when the body raises, so a failed stage shows
    its duration in the log instead of hanging on a spinner forever.
    """
    write = writer()
    write(Step(step=step, label=label, status="start", detail=detail).model_dump())
    started = time.perf_counter()
    try:
        yield
    finally:
        write(
            Step(
                step=step,
                label=label,
                status="done",
                ms=round((time.perf_counter() - started) * 1e3, 1),
                detail=detail,
            ).model_dump()
        )
