"""The human end of the graph.

A question runs as its own background `asyncio.Task` driving the LangGraph
graph, pushing events into a private queue as they happen. `stream()` just
reads that queue — deliberately not the thing driving the graph — so a browser
that disconnects mid-answer stops the *reading*, not the *answering*: the task
keeps running, and the finished turn still gets recorded. That decoupling used
to be a side effect of the bus being fire-and-forget; here it's explicit.

It is a queue rather than a single future because a question produces a stream —
many `StepEvent`s, then one `AnswerFinal`. `ask()` is just `stream()` with the
progress thrown away.

The gateway also writes the *readable* record of each conversation. That belongs
here rather than in the climate node because only this end sees the finished
answer: caveats are attached downstream by the caveats node and never travel
back to the model, so the history — which is what the model sees — cannot
reconstruct what the human was shown.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Literal

from langgraph.graph.state import CompiledStateGraph

from . import climate, store
from .schemas import Final, Step
from .store import Conversation, Exchange, Store

ASK_TIMEOUT = 300.0

# Entries are removed when the answer arrives, so this only grows if an answer
# never comes at all. A ceiling is cheaper than a sweeper.
MAX_INFLIGHT = 1000

Event = tuple[Literal["step", "final"], Step | Final]


class Gateway:
    def __init__(
        self,
        graph: CompiledStateGraph | None = None,
        store_: Store | None = None,
    ) -> None:
        self._graph = graph if graph is not None else climate.build_graph()
        # What each outstanding question belongs to, kept apart from the task
        # queues because it must outlive a disconnected HTTP stream: a browser
        # that walks away mid-answer still produced a turn, and the answer is
        # still coming.
        # subject -> (session id, question, started at)
        self._inflight: OrderedDict[str, tuple[str, str, float]] = OrderedDict()
        self._store = store_ if store_ is not None else store.build()

    async def stream(
        self,
        text: str,
        session_id: str | None = None,
        *,
        timeout: float = ASK_TIMEOUT,
    ) -> AsyncIterator[Event]:
        """Ask, and yield each step as it happens, then the finished answer.

        `session_id` is what makes a follow-up a follow-up — pass the same one
        again to keep the context. Omitting it starts a fresh conversation, so a
        caller that never passes one gets the old one-shot behaviour.
        """
        # Distinct from `session_id`: this one exists only to key this question
        # in `_inflight`, and dies with it.
        subject = uuid.uuid4().hex
        session_id = session_id or uuid.uuid4().hex
        self._remember(subject, session_id, text)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        # Deliberately not awaited here and never cancelled below: a reader that
        # stops early must not stop the answer, since the turn still needs
        # recording when it finishes.
        asyncio.create_task(self._run(subject, session_id, text, queue))

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"no answer within {timeout:.0f}s")
            kind, payload = await asyncio.wait_for(queue.get(), remaining)
            yield kind, payload
            if kind == "final":
                return

    async def _run(
        self, subject: str, session_id: str, text: str, queue: asyncio.Queue[Event]
    ) -> None:
        history = await self._store.history(session_id, climate.MODEL)
        state = {"question": text, "messages": history, "answer": "", "caveats": []}
        final_state: dict | None = None
        async for mode, chunk in self._graph.astream(
            state, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                await queue.put(("step", Step(**chunk)))
            else:
                final_state = chunk
        assert final_state is not None  # the graph always reaches END
        final = Final(answer=final_state["answer"], caveats=final_state["caveats"])
        await self._store.save_history(
            session_id, final_state["messages"], climate.MODEL
        )
        await self._record(subject, final)
        await queue.put(("final", final))

    def _remember(self, subject: str, session_id: str, question: str) -> None:
        self._inflight[subject] = (session_id, question, store.now())
        while len(self._inflight) > MAX_INFLIGHT:
            self._inflight.popitem(last=False)

    def pending(self, session_id: str) -> list[str]:
        """Questions still being answered for this session, oldest first."""
        return [q for sid, q, _ in self._inflight.values() if sid == session_id]

    def pending_sessions(self) -> dict[str, tuple[list[str], float]]:
        """Session id -> (questions in flight, when the first of them started).

        A session appears here before it appears in the store: nothing is written
        until an answer lands, so this is the only way to list a conversation
        whose *first* answer is still coming.
        """
        found: dict[str, tuple[list[str], float]] = {}
        for session_id, question, started_at in self._inflight.values():
            questions, first = found.get(session_id, ([], started_at))
            questions.append(question)
            found[session_id] = (questions, min(first, started_at))
        return found

    async def _record(self, subject: str, final: Final) -> None:
        """Append a finished exchange to its conversation.

        Driven by the background task rather than by a still-connected
        `stream()` caller, so a browser that closed, refreshed or switched
        conversations mid-answer still gets its turn — the climate node saved
        the history either way, and the two must not disagree.

        A turn that failed still arrives as a `Final` carrying the error text,
        and is recorded like any other — the transcript should show what the
        human was shown.
        """
        remembered = self._inflight.pop(subject, None)
        if remembered is None:  # stale or foreign subject; invent nothing
            return
        session_id, question, _started_at = remembered
        conversation = await self._store.conversation(session_id) or Conversation(
            session_id
        )
        conversation.exchanges.append(
            Exchange(question, final.answer, list(final.caveats))
        )
        conversation.updated_at = store.now()
        await self._store.save_conversation(conversation)

    async def conversations(self) -> list[Conversation]:
        """Every recorded conversation, most recently answered first."""
        return await self._store.conversations()

    async def conversation(self, session_id: str) -> Conversation | None:
        return await self._store.conversation(session_id)

    async def delete_conversation(self, session_id: str) -> None:
        """Forget a conversation: the transcript, the model's memory of it, and
        any answer still on its way.

        Dropping the in-flight entries is the part that is easy to miss.
        `_record` rebuilds a conversation from one when the answer lands, so a
        delete that left them behind would see the conversation reappear minutes
        later as a one-turn row — exactly the half-finished thing you were
        clearing out. An answer already running keeps running and is still
        delivered to whoever is watching it; it just goes unrecorded. (The
        climate node still writes that turn's history when it finishes, so
        deleting mid-answer can leave one orphaned history key behind. Nothing
        lists it and its TTL collects it, which is cheaper than cancelling the
        background task.)
        """
        for subject, (sid, _question, _started_at) in list(self._inflight.items()):
            if sid == session_id:
                del self._inflight[subject]
        await self._store.delete_session(session_id)

    async def ask(
        self,
        text: str,
        session_id: str | None = None,
        *,
        timeout: float = ASK_TIMEOUT,
    ) -> Final:
        # `timeout` is keyword-only so that a second positional argument can only
        # ever be the session id, never a timeout meant for the old signature.
        async for kind, payload in self.stream(text, session_id, timeout=timeout):
            if kind == "final":
                return payload  # type: ignore[return-value]
        raise TimeoutError(f"no answer within {timeout:.0f}s")


def render(final: Final) -> str:
    out = [final.answer]
    if final.caveats:
        out.append("")
        out.append("Caveats")
        out.extend(f"  - {c}" for c in final.caveats)
    return "\n".join(out)


async def repl(gateway: Gateway) -> None:
    print("Ask about city comfort. Ctrl-D or 'quit' to exit.\n")
    # One session for the whole repl, so follow-ups keep their context.
    session_id = uuid.uuid4().hex
    while True:
        try:
            text = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return

        print()
        try:
            async for kind, payload in gateway.stream(text, session_id):
                if kind == "step" and payload.status == "done":  # type: ignore[union-attr]
                    print(f"  · {payload.label:<28} {payload.ms:>7.0f}ms")  # type: ignore[union-attr]
                elif kind == "final":
                    print(f"\n{render(payload)}\n")  # type: ignore[arg-type]
        except TimeoutError:
            print("(no answer came back in time)\n")
