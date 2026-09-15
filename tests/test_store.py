"""The store contract, and the encoding the whole persistence story rests on.

Everything here runs offline against `MemoryStore`. The same contract tests also
run against a real `RedisStore` when one is reachable, and skip when it is not —
so `make test` needs no Docker, but `make redis && make test` proves more.
"""

import json
import os
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from climate_agent import store

# Deliberately not the app's database. Running the suite against a live Redis
# must not leave `test-*` rows in the conversation rail — db 15 keeps them apart.
REDIS_URL = os.environ.get(
    "REDIS_TEST_URL", "redis://:climate-agent-dev@localhost:6382/15"
)


@pytest.fixture(params=["memory", "redis"])
async def a_store(request):
    if request.param == "memory":
        yield store.MemoryStore()
        return
    redis_store = store.RedisStore(REDIS_URL)
    try:
        await redis_store.ping()
    except Exception:  # noqa: BLE001 — any failure to reach Redis means skip
        await redis_store.close()
        pytest.skip("no Redis reachable; run `make redis` to include these")
    yield redis_store
    await redis_store.close()


def a_session() -> str:
    """Unique per test, so a shared Redis needs no teardown between runs."""
    return f"test-{uuid.uuid4().hex}"


# ---------------------------------------------------------------- encoding


def test_history_round_trips_through_json_intact():
    """The claim persistence depends on: what the model hands back survives a
    trip through Redis (JSON) unchanged, tool calls included."""
    history = [
        HumanMessage("where is best?"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "query_rankings", "args": {"sql": "SELECT 1"}, "id": "t1"}
            ],
        ),
        ToolMessage(content="rows", tool_call_id="t1"),
        AIMessage("Lima."),
    ]

    roundtripped = store.decode_history(
        json.loads(json.dumps(store.encode_history(history)))
    )

    assert [type(m) for m in roundtripped] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert roundtripped[0].content == "where is best?"
    assert roundtripped[1].tool_calls[0]["args"] == {"sql": "SELECT 1"}
    assert roundtripped[1].tool_calls[0]["id"] == "t1"
    assert roundtripped[2].tool_call_id == "t1"
    assert roundtripped[2].content == "rows"
    assert roundtripped[3].content == "Lima."


# ------------------------------------------------------- schema evolution


def test_a_record_from_another_schema_version_is_ignored_not_raised():
    ours = json.dumps({"v": store.SCHEMA_VERSION, "id": "x"})
    theirs = json.dumps({"v": store.SCHEMA_VERSION + 1, "id": "x"})

    assert store._unpack(ours)["id"] == "x"
    assert store._unpack(theirs) is None, "a bumped version orphans old records"


@pytest.mark.parametrize("raw", [None, "{not json", '"a string"', "[]"])
def test_unreadable_records_are_treated_as_absent(raw):
    """Anything we cannot read costs a history, never a 500."""
    assert store._unpack(raw) is None


def test_a_malformed_conversation_is_dropped():
    assert store._to_conversation({"id": "x"}) is None


# ----------------------------------------------------------- the contract


async def test_history_survives_a_write_and_read(a_store):
    session = a_session()
    assert await a_store.history(session, "model-a") == []

    await a_store.save_history(session, [HumanMessage("hi")], "model-a")

    assert await a_store.history(session, "model-a") == [HumanMessage("hi")]


async def test_a_model_change_drops_the_history_but_keeps_the_transcript(a_store):
    """Thinking signatures are bound to the model that produced them, so bumping
    the model resets memory — without erasing anyone's chat log."""
    session = a_session()
    await a_store.save_history(session, [HumanMessage("hi")], "model-a")
    await a_store.save_conversation(
        store.Conversation(
            session, [store.Exchange("q", "a", ["careful"])], updated_at=store.now()
        )
    )

    assert await a_store.history(session, "model-b") == []

    conversation = await a_store.conversation(session)
    assert conversation is not None
    assert conversation.exchanges[0].caveats == ["careful"]


async def test_conversations_round_trip_and_list_newest_first(a_store):
    older, newer = a_session(), a_session()
    await a_store.save_conversation(
        store.Conversation(older, [store.Exchange("older q", "a")], updated_at=1000.0)
    )
    await a_store.save_conversation(
        store.Conversation(newer, [store.Exchange("newer q", "a")], updated_at=2000.0)
    )

    listed = [c.id for c in await a_store.conversations()]

    # A shared Redis may hold other runs' rows; only our two need to be ordered.
    assert [i for i in listed if i in {older, newer}] == [newer, older]
    assert await a_store.conversation("never-written") is None


async def test_appending_to_a_conversation_replaces_the_stored_copy(a_store):
    session = a_session()
    conversation = store.Conversation(session, [store.Exchange("q1", "a1")], 1.0)
    await a_store.save_conversation(conversation)

    conversation.exchanges.append(store.Exchange("q2", "a2"))
    conversation.updated_at = 2.0
    await a_store.save_conversation(conversation)

    stored = await a_store.conversation(session)
    assert [e.question for e in stored.exchanges] == ["q1", "q2"]


async def test_deleting_a_session_forgets_both_halves_and_de_indexes_it(a_store):
    """Delete has to take the history too. Leaving it behind would mean a
    conversation the user cleared out is still in Claude's context."""
    session, kept = a_session(), a_session()
    for s in (session, kept):
        await a_store.save_history(s, [HumanMessage("hi")], "model-a")
        await a_store.save_conversation(
            store.Conversation(s, [store.Exchange("q", "a")], updated_at=store.now())
        )

    await a_store.delete_session(session)

    assert await a_store.conversation(session) is None
    assert await a_store.history(session, "model-a") == []
    listed = [c.id for c in await a_store.conversations()]
    assert session not in listed, "the index still points at a deleted session"
    assert kept in listed, "delete took an unrelated session with it"


async def test_deleting_a_session_twice_is_not_an_error(a_store):
    """The rail is a snapshot, so a row may already be gone when it is clicked."""
    session = a_session()
    await a_store.save_conversation(store.Conversation(session, [], store.now()))

    await a_store.delete_session(session)
    await a_store.delete_session(session)
    await a_store.delete_session("never-written")


def test_the_title_comes_from_the_opening_question():
    long = "Where in the world is it comfortable to be outdoors all year round?"
    assert store.Conversation("x", [store.Exchange("short q", "a")]).title == "short q"
    assert store.Conversation("x").title == "New conversation"

    truncated = store.Conversation("x", [store.Exchange(long, "a")]).title
    assert len(truncated) <= store.TITLE_CHARS
    assert truncated.endswith("…")


def test_title_for_collapses_whitespace_and_truncates():
    assert store.title_for("  where   is\nbest? ") == "where is best?"

    long = "Where in the world is it comfortable to be outdoors all year round?"
    truncated = store.title_for(long)
    assert len(truncated) <= store.TITLE_CHARS
    assert truncated.endswith("…")
    # A stored conversation and an in-flight one must label identically.
    assert store.Conversation("x", [store.Exchange(long, "a")]).title == truncated
