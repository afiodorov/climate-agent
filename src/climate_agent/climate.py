"""The agent that actually answers questions, using DeepSeek and a SQL tool.

Wires two LangGraph nodes: `climate` (the tool-calling agent) and `caveats` (the
honesty sidecar, no LLM). `climate` publishes nothing to anyone — it just writes
`answer` into the graph state, and the graph's own edge is what hands it to
`caveats`. That is the LangGraph-native version of the old pub/sub lesson: the
climate node does not know the caveat node exists, it just happens to run next.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypedDict

import openai
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from . import progress, query
from .caveats import caveats_for

log = logging.getLogger(__name__)

MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# The client retries connection errors and 5xx with exponential backoff. That is
# thin for a busy server, which means "come back later" rather than anything
# wrong with the request. Retries are per HTTP request, so this applies to every
# round of the tool loop, not just the first.
MAX_RETRIES = 5

# Each tool round costs two graph steps (model call, tool call), so this bounds
# the loop at roughly 8 rounds — same ceiling the old `max_iterations=8` gave.
RECURSION_LIMIT = 20

# What the human sees when a turn dies. Split because the two say different
# things: one is worth retrying immediately, the other is not.
BUSY_TEXT = "The model is busy right now. Ask again in a moment."
FAILED_TEXT = "Something went wrong reaching the model. Try again."

History = list[BaseMessage]

# History in, (answer, new history) out. Keeping the store outside this callable
# means the seam stays a pure function, which is what makes it stubbable.
Ask = Callable[[str, History], Awaitable[tuple[str, History]]]

# A session is trimmed back to this many messages, oldest turns dropped first.
# Tool rounds make a single turn several messages, so this is a handful of turns,
# not a handful of questions. This bounds the cost of a request; eviction is a
# separate concern and belongs to the store's TTL.
MAX_SESSION_MESSAGES = 40

SYSTEM = f"""You answer questions about where in the world it is comfortable to be \
outdoors, using a precomputed ranking of the 1118 cities with population >= 500,000.

The ranking scores each city by how many daylight hours a year its UTCI (Universal \
Thermal Climate Index, computed hourly from ERA5 reanalysis, 2010-2024) falls in a \
comfortable band. `comfort_hours_yr` is the headline metric; `composite` additionally \
penalises seasonal unevenness and PM2.5, and is what `rank` sorts by.

Answer by querying the data with the `query_rankings` tool. Never state a number you \
have not read out of a query result, and never guess at a city's rank.

{query.SCHEMA}

Guidance:
- Prefer several small queries over one large one. Always LIMIT ranked lists.
- "Best" is ambiguous: raw comfort hours, comfort fraction, the composite, worst-month \
hours and evenness rank cities differently. If a question turns on that choice, say \
which metric you used and why.
- Month columns answer "what is February like in X". The sun/shade pair answers \
"is it bearable in the shade".
- Be direct and concise. A sentence or two of prose plus the numbers that support it. \
Do not append a caveats section — that is added downstream.
"""


@tool
async def query_rankings(sql: str) -> str:
    """Run a read-only SQL query against the city comfort ranking.

    Use this for every factual claim. Only SELECT and WITH statements are permitted.
    The views `rankings` and `sensitivity` are described in the system prompt.

    Args:
        sql: A DuckDB SELECT statement.
    """
    async with progress.timed("sql", "SQL query", detail=" ".join(sql.split())):
        try:
            return await asyncio.to_thread(query.run_sql, sql)
        except query.QueryError as exc:
            return f"Query failed: {exc}"


def _is_question(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage)


def _committable(messages: History) -> History:
    """Trim a transcript back to something replayable next turn.

    Hitting the recursion limit can cut the loop off mid-tool-round, leaving an
    `AIMessage` with a pending `tool_calls` that nothing ever answered; replaying
    that is a 400. Drop from the end until the transcript closes on a plain
    assistant reply — worst case that discards the whole broken turn and leaves
    the session as it was.
    """
    end = len(messages)
    while end:
        message = messages[end - 1]
        if isinstance(message, AIMessage) and not message.tool_calls:
            return list(messages[:end])
        end -= 1
    return []


def _trim_session(messages: History) -> History:
    """Drop whole turns off the front until the session is back under budget."""
    trimmed = list(messages)
    while len(trimmed) > MAX_SESSION_MESSAGES:
        boundary = next(
            (i for i in range(1, len(trimmed)) if _is_question(trimmed[i])), None
        )
        if boundary is None:  # one turn is over budget on its own; leave it be
            break
        trimmed = trimmed[boundary:]
    return trimmed


def _busy(exc: openai.APIStatusError) -> bool:
    return isinstance(exc, openai.RateLimitError) or exc.status_code == 503


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in content
    ).strip()


def ask_claude(model: ChatOpenAI | None = None) -> Ask:
    """Build the 'answer one question' function. Swappable in tests.

    Named for symmetry with the old Anthropic-backed version; the model itself
    is DeepSeek now.
    """
    model = model or ChatOpenAI(
        model=MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        max_retries=MAX_RETRIES,
    )
    agent = create_agent(model, tools=[query_rankings], system_prompt=SYSTEM)

    async def ask(question: str, history: History) -> tuple[str, History]:
        try:
            return await _attempt(question, history)
        except openai.BadRequestError:
            if not history:
                raise
            # Stored history the API will no longer accept — a changed block
            # shape, a signature it rejects. Without this the conversation is
            # permanently wedged; with it the user just loses the memory.
            log.warning("replaying history failed; retrying without it", exc_info=True)
            return await _attempt(question, [])

    async def _attempt(question: str, history: History) -> tuple[str, History]:
        messages: History = [*history, HumanMessage(question)]
        write = progress.writer()
        final_state: dict | None = None
        try:
            async for mode, chunk in agent.astream(
                {"messages": messages},
                stream_mode=["custom", "values"],
                config={"recursion_limit": RECURSION_LIMIT},
            ):
                if mode == "custom":
                    # The SQL tool's own `progress.timed` runs inside this nested
                    # agent's graph, so its writes need forwarding to reach the
                    # outer stream a browser is actually reading.
                    write(chunk)
                else:
                    final_state = chunk
        except GraphRecursionError:
            pass  # `final_state` still holds whatever the loop produced so far

        if final_state is None:
            return "No response from the model.", history
        updated: History = final_state["messages"]
        last = updated[-1] if updated else None
        if not isinstance(last, AIMessage) or last.tool_calls:
            return "The model returned no text.", history
        text = _text_of(last)
        if not text:
            return "The model returned no text.", history
        return text, _committable(updated)

    return ask


class GraphState(TypedDict):
    question: str
    messages: History
    answer: str
    caveats: list[str]


def build_graph(ask: Ask | None = None) -> CompiledStateGraph:
    """Two nodes, one edge: `climate` answers, `caveats` annotates.

    `ask` exists for tests: a stand-in so the suite runs without an API key.
    """
    answer = ask if ask is not None else ask_claude()

    async def climate_node(state: GraphState) -> dict:
        try:
            async with progress.timed("answer", "DeepSeek + SQL tool"):
                text, updated = await answer(state["question"], state["messages"])
        except openai.APIStatusError as exc:
            if _busy(exc):
                log.warning("model busy; gave up after %d retries", MAX_RETRIES)
                text = BUSY_TEXT
            else:
                log.exception("answering failed")
                text = FAILED_TEXT
            return {"messages": state["messages"], "answer": text}
        except Exception:  # a bad turn must not take the graph down
            log.exception("answering failed")
            return {"messages": state["messages"], "answer": FAILED_TEXT}
        return {"messages": _trim_session(updated), "answer": text}

    async def caveats_node(state: GraphState) -> dict:
        try:
            async with progress.timed("caveats", "Caveat lookup"):
                notes = caveats_for(state["answer"])
        except Exception:  # never swallow the answer over a failed lookup
            log.exception("caveat lookup failed")
            notes = []
        return {"caveats": notes}

    graph = StateGraph(GraphState)
    graph.add_node("climate", climate_node)
    graph.add_node("caveats", caveats_node)
    graph.add_edge(START, "climate")
    graph.add_edge("climate", "caveats")
    graph.add_edge("caveats", END)
    return graph.compile()
