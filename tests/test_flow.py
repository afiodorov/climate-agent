"""End-to-end over the graph, with the model stubbed out.

Each test builds its own graph and its own `MemoryStore`, so tests cannot bleed
state into one another — the LangGraph equivalent of the old per-test channels.
"""

import asyncio
import inspect

import httpx
import openai
from langchain_core.messages import AIMessage, HumanMessage

from climate_agent import climate, gateway, progress, store
from climate_agent.schemas import Final


async def _allow(question, history):
    """The scope filter, stubbed open. Tests here are about the flow, not the
    guard; `test_guard.py` is where refusing is exercised."""
    return True


class Bus:
    """A graph plus the store it shares with the gateway, torn down cleanly."""

    def __init__(self, ask, guard=_allow):
        self.store = store.MemoryStore()
        self.gateway = gateway.Gateway(
            climate.build_graph(ask=ask, guard=guard), store_=self.store
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


async def test_question_reaches_the_agent_and_the_answer_comes_back():
    async def ask(question, history):
        return f"Porto is mild. (asked: {question})", history

    async with Bus(ask) as bus:
        final = await bus.gateway.ask("what about Porto?", timeout=10)

    assert "Porto is mild." in final.answer
    assert "asked: what about Porto?" in final.answer


async def test_caveat_node_annotates_without_the_climate_node_knowing():
    async def ask(question, history):
        return "Lima is the best city on raw comfort hours.", history

    async with Bus(ask) as bus:
        final = await bus.gateway.ask("where is best?", timeout=10)

    assert final.caveats, "expected the caveats node to attach caveats"
    assert any("Microclimate risk" in c for c in final.caveats)
    assert any('"Best" depends' in c for c in final.caveats)
    # The draft itself is untouched — the caveats node appends, it does not rewrite.
    assert final.answer == "Lima is the best city on raw comfort hours."


async def test_concurrent_questions_do_not_cross_wires():
    """Each `stream()` call drives its own graph run, so replies cannot cross."""

    async def ask(question, history):
        # Answer the slow question first, so ordering cannot be doing the work.
        await asyncio.sleep(0.2 if "first" in question else 0.05)
        return f"answer to {question}", history

    async with Bus(ask) as bus:
        first, second = await asyncio.gather(
            bus.gateway.ask("the first one", timeout=10),
            bus.gateway.ask("the second one", timeout=10),
        )

    assert first.answer == "answer to the first one"
    assert second.answer == "answer to the second one"


async def test_streams_step_timings_before_the_answer():
    async def ask(question, history):
        # No queue, no writer plumbing — the tool finds its writer through
        # LangGraph's own run context, exactly as query_rankings does.
        async with progress.timed("sql", "SQL query", detail="SELECT 1"):
            await asyncio.sleep(0.01)
        return "Porto is mild.", history

    async with Bus(ask) as bus:
        events = [event async for event in bus.gateway.stream("porto?", timeout=10)]

    kinds = [kind for kind, _ in events]
    assert kinds[-1] == "final", "the answer must terminate the stream"
    assert kinds.count("final") == 1

    steps = [payload for kind, payload in events if kind == "step"]
    seen = {(s.step, s.status) for s in steps}
    assert {
        ("guard", "start"),
        ("answer", "start"),
        ("sql", "start"),
        ("caveats", "done"),
    } <= seen

    finished = [s for s in steps if s.status == "done"]
    assert finished and all(s.ms is not None and s.ms >= 0 for s in finished)
    assert any(s.detail == "SELECT 1" for s in steps)


async def test_step_events_do_not_interleave_between_concurrent_questions():
    """Two questions in flight must not have their progress logs interleaved."""

    async def ask(question, history):
        async with progress.timed("sql", f"query for {question}"):
            await asyncio.sleep(0.05 if question == "one" else 0.01)
        return f"answer to {question}", history

    async def collect(bus, q):
        return [p for k, p in await _drain(bus.gateway.stream(q, timeout=10))]

    async def _drain(agen):
        return [event async for event in agen]

    async with Bus(ask) as bus:
        first, second = await asyncio.gather(collect(bus, "one"), collect(bus, "two"))

    for question, payloads in (("one", first), ("two", second)):
        labels = [p.label for p in payloads if hasattr(p, "label")]
        assert f"query for {question}" in labels
        assert f"query for {'two' if question == 'one' else 'one'}" not in labels


async def test_a_failing_model_call_does_not_kill_the_graph():
    calls = []

    async def ask(question, history):
        calls.append(question)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return "recovered", history

    async with Bus(ask) as bus:
        broken = await bus.gateway.ask("first", timeout=10)
        ok = await bus.gateway.ask("second", timeout=10)

    assert "went wrong" in broken.answer
    assert ok.answer == "recovered"


async def test_a_busy_model_says_so_rather_than_blaming_the_question():
    """429/503 means the API was busy, not that anything here is wrong — and the
    client has already spent its retries by the time it reaches us."""

    async def ask(question, history):
        raise openai.RateLimitError(
            "Rate limited",
            response=httpx.Response(429, request=httpx.Request("POST", "/")),
            body=None,
        )

    async with Bus(ask) as bus:
        final = await bus.gateway.ask("where is best?", timeout=10)

    assert final.answer == climate.BUSY_TEXT
    assert "went wrong" not in final.answer


def _turn(question: str) -> list:
    return [HumanMessage(question), AIMessage(f"answer to {question}")]


def _texts(messages: list) -> list[str]:
    return [m.content for m in messages]


async def test_a_session_carries_history_into_the_next_question():
    """The whole point: the second question arrives with the first one attached."""
    seen = []

    async def ask(question, history):
        seen.append(list(history))
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("where is best?", "s1", timeout=10)
        await bus.gateway.ask("and in the shade?", "s1", timeout=10)

    assert seen[0] == [], "the first question starts from nothing"
    assert _texts(seen[1]) == ["where is best?", "answer to where is best?"]


async def test_sessions_do_not_see_each_other():
    seen = {}

    async def ask(question, history):
        seen[question] = list(history)
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("first in a", "a", timeout=10)
        await bus.gateway.ask("first in b", "b", timeout=10)
        await bus.gateway.ask("second in a", "a", timeout=10)

    assert seen["first in a"] == []
    assert seen["first in b"] == [], "a new session must not inherit another's"
    assert _texts(seen["second in a"]) == ["first in a", "answer to first in a"]


async def test_an_omitted_session_id_is_a_fresh_conversation():
    seen = []

    async def ask(question, history):
        seen.append(list(history))
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("one", timeout=10)
        await bus.gateway.ask("two", timeout=10)

    assert seen == [[], []], "no session id means no memory, as it did before"


async def test_a_failed_turn_does_not_poison_the_session():
    seen = []

    async def ask(question, history):
        seen.append(list(history))
        if question == "boom":
            raise RuntimeError("boom")
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("good", "s", timeout=10)
        broken = await bus.gateway.ask("boom", "s", timeout=10)
        await bus.gateway.ask("after", "s", timeout=10)

    assert "went wrong" in broken.answer
    assert _texts(seen[2]) == ["good", "answer to good"]


async def test_the_gateway_records_a_readable_transcript():
    async def ask(question, history):
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("where is best?", "s1", timeout=10)
        await bus.gateway.ask("and in the shade?", "s1", timeout=10)

        [convo] = await bus.gateway.conversations()

    assert convo.id == "s1"
    assert convo.title == "where is best?", "the opening question labels the convo"
    assert [(e.question, e.answer) for e in convo.exchanges] == [
        ("where is best?", "answer to where is best?"),
        ("and in the shade?", "answer to and in the shade?"),
    ]


async def test_the_transcript_keeps_the_caveats_the_model_never_sees():
    """The whole reason this record lives in the gateway rather than in the
    climate node — caveats are attached downstream and never reach the model."""

    async def ask(question, history):
        return "Lima is the best city on raw comfort hours.", history

    async with Bus(ask) as bus:
        await bus.gateway.ask("where is best?", "s1", timeout=10)
        [convo] = await bus.gateway.conversations()

    [exchange] = convo.exchanges
    assert exchange.caveats, "expected the caveats node's caveats to be recorded"
    assert any("Microclimate risk" in c for c in exchange.caveats)


async def test_conversations_are_listed_newest_first():
    async def ask(question, history):
        return f"answer to {question}", history

    async with Bus(ask) as bus:
        await bus.gateway.ask("older", "old", timeout=10)
        await bus.gateway.ask("newer", "new", timeout=10)

        listed = await bus.gateway.conversations()
        missing = await bus.gateway.conversation("never-asked")

    assert [c.id for c in listed] == ["new", "old"]
    assert missing is None


async def test_a_long_title_is_truncated():
    question = "Where in the world is it comfortable to be outdoors all year?"

    async def ask(q, history):
        return "somewhere", history

    async with Bus(ask) as bus:
        await bus.gateway.ask(question, "s1", timeout=10)
        [convo] = await bus.gateway.conversations()

    assert len(convo.title) <= store.TITLE_CHARS
    assert convo.title.endswith("…")


async def _eventually(get, timeout=5.0):
    """Poll until `get()` returns something truthy; accepts sync or async.

    Recording happens on the background task now, so it is not synchronous with
    the caller that abandoned the stream.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = get()
        if inspect.isawaitable(value):
            value = await value
        if value:
            return value
        await asyncio.sleep(0.02)
    return None


async def test_an_abandoned_stream_still_records_its_answer():
    """Switching conversations mid-answer closes the SSE stream, which closes
    the response generator. The turn must still land: the background task keeps
    driving the graph regardless, so a dropped transcript would leave the model
    remembering an exchange the user cannot see."""

    async def ask(question, history):
        await asyncio.sleep(0.05)
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        stream = bus.gateway.stream("where is best?", "abandoned")
        await stream.__anext__()  # one event, then walk away
        await stream.aclose()

        convo = await _eventually(lambda: bus.gateway.conversation("abandoned"))

    assert convo is not None, "the abandoned turn was never recorded"
    assert [e.question for e in convo.exchanges] == ["where is best?"]
    assert convo.exchanges[0].answer == "answer to where is best?"


async def test_pending_reports_a_question_while_it_is_in_flight():
    release = asyncio.Event()

    async def ask(question, history):
        await release.wait()
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        asking = asyncio.create_task(bus.gateway.ask("slow one", "s1", timeout=10))
        assert await _eventually(lambda: bus.gateway.pending("s1") == ["slow one"]), (
            "expected the in-flight question to be reported"
        )
        assert bus.gateway.pending("other-session") == []

        release.set()
        await asking

        assert bus.gateway.pending("s1") == [], "cleared once the answer lands"


async def test_an_unknown_subject_records_no_conversation():
    """A stale or foreign subject must not conjure a conversation."""

    async def ask(question, history):
        return "answer", history

    async with Bus(ask) as bus:
        await bus.gateway._record("never-asked", Final(answer="ghost", caveats=[]))

        assert await bus.gateway.conversation("never-asked") is None
        assert await bus.gateway.conversations() == []


async def test_a_session_is_listed_before_its_first_answer_arrives():
    """Nothing is stored until an answer lands, so a brand-new conversation is
    only visible through the in-flight view — otherwise the rail has no row to
    show, and no row to click your way back to."""
    release = asyncio.Event()

    async def ask(question, history):
        await release.wait()
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        asking = asyncio.create_task(bus.gateway.ask("first ever", "fresh", timeout=10))
        assert await _eventually(lambda: bus.gateway.pending_sessions().get("fresh"))

        questions, started_at = bus.gateway.pending_sessions()["fresh"]
        assert questions == ["first ever"]
        assert started_at > 0
        # Still nothing in the store — that is the whole problem being solved.
        assert await bus.gateway.conversation("fresh") is None

        release.set()
        await asking

        assert bus.gateway.pending_sessions() == {}
        convo = await bus.gateway.conversation("fresh")
        assert [e.question for e in convo.exchanges] == ["first ever"]


async def test_deleting_a_conversation_forgets_it_end_to_end():
    seen = []

    async def ask(question, history):
        seen.append(list(history))
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        await bus.gateway.ask("where is best?", "s1", timeout=10)
        await bus.gateway.ask("kept", "s2", timeout=10)

        await bus.gateway.delete_conversation("s1")

        assert await bus.gateway.conversation("s1") is None
        assert [c.id for c in await bus.gateway.conversations()] == ["s2"]

        # Reusing the id proves the model's memory went with the transcript.
        await bus.gateway.ask("again", "s1", timeout=10)

    assert seen[-1] == [], "a deleted session must not carry its history forward"


async def test_deleting_a_conversation_mid_answer_does_not_let_it_come_back():
    """The half-finished conversations this exists to clear out are exactly the
    ones with an answer still in flight — and `_record` rebuilds a conversation
    from that in-flight entry when it lands."""
    release = asyncio.Event()

    async def ask(question, history):
        await release.wait()
        return f"answer to {question}", [*history, *_turn(question)]

    async with Bus(ask) as bus:
        asking = asyncio.create_task(bus.gateway.ask("slow one", "doomed", timeout=10))
        assert await _eventually(lambda: bus.gateway.pending("doomed") == ["slow one"])

        await bus.gateway.delete_conversation("doomed")
        assert bus.gateway.pending("doomed") == []

        # The asker still gets its answer — only the record is gone.
        release.set()
        final = await asking
        assert final.answer == "answer to slow one"

        # Give the recording path a chance to (wrongly) resurrect it.
        await asyncio.sleep(0.1)
        assert await bus.gateway.conversation("doomed") is None
        assert await bus.gateway.conversations() == []


async def test_pending_sessions_groups_by_session_and_keeps_the_earliest_start():
    release = asyncio.Event()

    async def ask(question, history):
        await release.wait()
        return "answer", history

    async with Bus(ask) as bus:
        first = asyncio.create_task(bus.gateway.ask("one", "s1", timeout=10))
        second = asyncio.create_task(bus.gateway.ask("two", "s1", timeout=10))
        other = asyncio.create_task(bus.gateway.ask("elsewhere", "s2", timeout=10))
        assert await _eventually(
            lambda: len(bus.gateway.pending_sessions().get("s1", ([], 0))[0]) == 2
        )

        sessions = bus.gateway.pending_sessions()
        assert sorted(sessions["s1"][0]) == ["one", "two"]
        assert sessions["s2"][0] == ["elsewhere"]
        assert sessions["s1"][1] <= sessions["s2"][1], "earliest start wins"

        release.set()
        await asyncio.gather(first, second, other)
