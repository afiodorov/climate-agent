"""Message payloads carried between the graph and the outside world.

`Step` and `Final` are what `Gateway.stream()` yields and what the SSE endpoint
serializes — that wire shape is unchanged from before the LangGraph rewrite, so
the frontend needed no changes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Question(BaseModel):
    text: str
    session_id: str


class Step(BaseModel):
    """One timed stage of answering, for the progress log."""

    step: str
    label: str
    status: Literal["start", "done"]
    ms: float | None = None
    detail: str | None = None


class Final(BaseModel):
    answer: str
    caveats: list[str] = []
