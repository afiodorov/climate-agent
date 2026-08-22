"""Where conversations live between requests — and between restarts.

Two things are stored per session id, and they are not the same thing:

  * the **history**: the LangChain messages the model sees, including
    tool-call/tool-result pairs. This is what makes a follow-up a follow-up.
  * the **conversation**: question, answer and caveats — what the human saw.
    Caveats are attached downstream and never travel back to the model, so this
    cannot be reconstructed from the history.

Both hang off one `Store`, so they share a TTL and cannot drift apart: a
conversation can never be listed after the model has forgotten it.

`MemoryStore` is the whole implementation for tests, and is what the old
in-process dicts used to be. `RedisStore` is the one that survives a restart.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

log = logging.getLogger(__name__)

# Bump to orphan every stored record. Old keys are simply ignored on read and
# expire on their own, so there is no migration code to write — see `_unpack`.
# v2: history moved from Anthropic content-block dicts to LangChain messages
# (the LangGraph rewrite), so v1 records are deliberately made unreadable.
SCHEMA_VERSION = 2

PREFIX = f"climate:v{SCHEMA_VERSION}"

# Refreshed on every write, so an active conversation keeps itself alive. This
# replaces the old per-store LRU caps; one TTL on both keys means they expire
# together.
SESSION_TTL = 7 * 24 * 3600

TITLE_CHARS = 60


@dataclass
class Exchange:
    """One question and the answer the human actually saw."""

    question: str
    answer: str
    caveats: list[str] = field(default_factory=list)


def title_for(question: str) -> str:
    """Label a conversation by its opening question.

    Shared with conversations that have no stored exchange yet — one whose first
    answer is still coming is titled by the question in flight.
    """
    opener = " ".join(question.split())
    if len(opener) <= TITLE_CHARS:
        return opener
    return opener[: TITLE_CHARS - 1].rstrip() + "…"


@dataclass
class Conversation:
    id: str
    exchanges: list[Exchange] = field(default_factory=list)
    updated_at: float = 0.0

    @property
    def title(self) -> str:
        """Derived, not stored: the opening question is a better label than
        anything a summariser would invent, and costs no model call."""
        if not self.exchanges:
            return "New conversation"
        return title_for(self.exchanges[0].question)


# --------------------------------------------------------------------------
# Encoding
#
# A history is a list of LangChain `BaseMessage` objects. `messages_to_dict` /
# `messages_from_dict` are LangChain's own round-trip helpers, so this layer
# doesn't need to know anything about message shapes itself.
# --------------------------------------------------------------------------


def encode_history(history: list[BaseMessage]) -> list[dict]:
    return messages_to_dict(history)


def decode_history(payload: list[dict]) -> list[BaseMessage]:
    return messages_from_dict(payload)


def _pack(payload: dict) -> str:
    return json.dumps({"v": SCHEMA_VERSION, **payload})


def _unpack(raw: str | bytes | None) -> dict | None:
    """Decode a stored record, or None if it is unusable.

    Anything we cannot read is treated as absent rather than raised: a record
    written by an older (or newer) build should cost the user their history, not
    a 500.
    """
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        log.warning("discarding unparseable record")
        return None
    if not isinstance(payload, dict):
        log.warning("discarding non-object record")
        return None
    if payload.get("v") != SCHEMA_VERSION:
        log.info("discarding record from schema v%s", payload.get("v"))
        return None
    return payload


def _to_conversation(payload: dict) -> Conversation | None:
    try:
        return Conversation(
            id=payload["id"],
            updated_at=payload["updated_at"],
            exchanges=[
                Exchange(e["question"], e["answer"], list(e.get("caveats", [])))
                for e in payload["exchanges"]
            ],
        )
    except (KeyError, TypeError):
        log.warning("discarding malformed conversation record")
        return None


class Store(Protocol):
    async def ping(self) -> None: ...

    async def history(self, session_id: str, model: str) -> list[BaseMessage]: ...

    async def save_history(
        self, session_id: str, history: list[BaseMessage], model: str
    ) -> None: ...

    async def conversation(self, session_id: str) -> Conversation | None: ...

    async def save_conversation(self, conversation: Conversation) -> None: ...

    async def conversations(self) -> list[Conversation]: ...

    async def delete_session(self, session_id: str) -> None: ...

    async def close(self) -> None: ...


class MemoryStore:
    """In-process. What the tests use, and what the app was before Redis."""

    def __init__(self) -> None:
        self._histories: dict[str, tuple[str, list[BaseMessage]]] = {}
        self._conversations: dict[str, Conversation] = {}

    async def ping(self) -> None:
        return None

    async def history(self, session_id: str, model: str) -> list[BaseMessage]:
        stored = self._histories.get(session_id)
        if stored is None:
            return []
        stored_model, history = stored
        if stored_model != model:
            log.info(
                "history for %s was written by %s; dropping", session_id, stored_model
            )
            return []
        return history

    async def save_history(
        self, session_id: str, history: list[BaseMessage], model: str
    ) -> None:
        self._histories[session_id] = (model, history)

    async def conversation(self, session_id: str) -> Conversation | None:
        return self._conversations.get(session_id)

    async def save_conversation(self, conversation: Conversation) -> None:
        self._conversations[conversation.id] = conversation

    async def conversations(self) -> list[Conversation]:
        return sorted(
            self._conversations.values(), key=lambda c: c.updated_at, reverse=True
        )

    async def delete_session(self, session_id: str) -> None:
        self._histories.pop(session_id, None)
        self._conversations.pop(session_id, None)

    async def close(self) -> None:
        return None


class RedisStore:
    """Survives a restart. Keys carry the schema version and a shared TTL."""

    def __init__(self, url: str | None = None) -> None:
        from redis import asyncio as redis  # imported here so tests need no redis

        self.url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(self.url, decode_responses=True)

    async def ping(self) -> None:
        await self._redis.ping()

    def _history_key(self, session_id: str) -> str:
        return f"{PREFIX}:history:{session_id}"

    def _convo_key(self, session_id: str) -> str:
        return f"{PREFIX}:convo:{session_id}"

    @property
    def _index_key(self) -> str:
        return f"{PREFIX}:convos"

    async def history(self, session_id: str, model: str) -> list[BaseMessage]:
        payload = _unpack(await self._redis.get(self._history_key(session_id)))
        if payload is None:
            return []
        # A model bump resets memory; the conversation record is untouched — the
        # transcript survives even though the context does not.
        if payload.get("model") != model:
            log.info(
                "history for %s was written by %s; dropping",
                session_id,
                payload.get("model"),
            )
            return []
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []
        try:
            return decode_history(messages)
        except (KeyError, TypeError, ValueError):
            log.warning("discarding unparseable history for %s", session_id)
            return []

    async def save_history(
        self, session_id: str, history: list[BaseMessage], model: str
    ) -> None:
        await self._redis.set(
            self._history_key(session_id),
            _pack({"model": model, "messages": encode_history(history)}),
            ex=SESSION_TTL,
        )

    async def conversation(self, session_id: str) -> Conversation | None:
        payload = _unpack(await self._redis.get(self._convo_key(session_id)))
        return _to_conversation(payload) if payload else None

    async def save_conversation(self, conversation: Conversation) -> None:
        payload = _pack(
            {
                "id": conversation.id,
                "updated_at": conversation.updated_at,
                "exchanges": [
                    {"question": e.question, "answer": e.answer, "caveats": e.caveats}
                    for e in conversation.exchanges
                ],
            }
        )
        pipe = self._redis.pipeline()
        pipe.set(self._convo_key(conversation.id), payload, ex=SESSION_TTL)
        pipe.zadd(self._index_key, {conversation.id: conversation.updated_at})
        pipe.expire(self._index_key, SESSION_TTL)
        await pipe.execute()

    async def conversations(self) -> list[Conversation]:
        """Newest first, healing the index as it goes.

        An index entry outlives its key when the TTL fires, so a missing read is
        expected rather than exceptional — drop it and move on. That is why
        there is no sweeper.
        """
        ids = await self._redis.zrevrange(self._index_key, 0, -1)
        if not ids:
            return []
        raws = await self._redis.mget([self._convo_key(i) for i in ids])
        found, stale = [], []
        for session_id, raw in zip(ids, raws):
            payload = _unpack(raw)
            conversation = _to_conversation(payload) if payload else None
            if conversation is None:
                stale.append(session_id)
            else:
                found.append(conversation)
        if stale:
            await self._redis.zrem(self._index_key, *stale)
        return found

    async def delete_session(self, session_id: str) -> None:
        """Both keys and the index entry, in one round trip.

        Deleting what is not there is not an error in Redis, so this is
        idempotent: a session already gone to its TTL deletes like a live one.
        """
        pipe = self._redis.pipeline()
        pipe.delete(self._history_key(session_id), self._convo_key(session_id))
        pipe.zrem(self._index_key, session_id)
        await pipe.execute()

    async def close(self) -> None:
        await self._redis.aclose()


def build(url: str | None = None) -> Store:
    """The store the app runs on. Tests pass a `MemoryStore` instead."""
    return RedisStore(url)


def now() -> float:
    return time.time()
