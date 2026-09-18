"""The agent-facing surface: /mcp, the JSON routes and llms.txt.

Drives the FastAPI app in-process with the real lifespan bypassed — it wants
DeepSeek and Redis — by attaching a stubbed gateway directly and running only
the MCP session manager. What is under test is the wiring: every route answers,
the MCP tools are listed and callable, and errors come back readable.
"""

import asyncio

import httpx
import pytest
import pytest_asyncio
from conftest import flagged_city, has_data

from climate_agent import climate, gateway, query, store
from climate_agent.api import agents
from climate_agent.api.app import app

FLAGGED = flagged_city() if has_data else "Lima"

pytestmark = [
    pytest.mark.skipif(
        not (query.out_dir() / "rankings.csv").exists(),
        reason="climate out/ not built",
    ),
    # The MCP session manager can be started exactly once per process, the
    # same as in the app's lifespan, so one event loop and one fixture serve
    # the whole module.
    pytest.mark.asyncio(loop_scope="module"),
]

# Stateless JSON-mode MCP over plain HTTP: every POST is a complete JSON-RPC
# exchange, no session id to carry. That is what makes it testable with httpx.
MCP_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


async def _allow(question, history):
    return True


async def _ask(question, history):
    return f"{FLAGGED} is the best city. (asked: {question})", history


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    agents.attach(
        gateway.Gateway(
            climate.build_graph(ask=_ask, guard=_allow), store_=store.MemoryStore()
        )
    )
    # The manager's anyio task group must be entered and left by the same
    # task, and pytest-asyncio tears a fixture down in a different task than it
    # set it up in. So it runs in a task of its own, held open by an event.
    started, stop = asyncio.Event(), asyncio.Event()

    async def hold():
        async with agents.server.session_manager.run():
            started.set()
            await stop.wait()

    manager = asyncio.create_task(hold())
    await started.wait()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://climate.example"
    ) as c:
        yield c
    stop.set()
    await manager


async def _call(client, name, **arguments):
    r = await client.post(
        agents.MCP_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=MCP_HEADERS,
    )
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def test_llms_txt_names_its_own_host(client):
    r = await client.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "https://climate.example/mcp" in r.text
    assert "comfort_hours_yr" in r.text  # the schema is in there


async def test_llms_txt_is_https_behind_a_proxy():
    # Uvicorn will not trust X-Forwarded-Proto from a non-loopback proxy, so
    # the request arrives as http; the file must still advertise https.
    text = agents.llms_txt("http://climate.fiodorov.es/")
    assert "http://climate.fiodorov.es/mcp" in text  # the helper is literal
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://climate.fiodorov.es"
    ) as c:
        r = await c.get("/llms.txt")
    assert "https://climate.fiodorov.es/mcp" in r.text


async def test_schema_route(client):
    r = await client.get("/api/schema")
    body = r.json()
    assert r.status_code == 200
    assert "rankings" in body["schema"]
    assert body["max_rows"] == query.MAX_ROWS


async def test_query_route_returns_rows(client):
    r = await client.get(
        "/api/query", params={"sql": "SELECT name, rank FROM rankings LIMIT 2"}
    )
    body = r.json()
    assert r.status_code == 200
    assert body["columns"] == ["name", "rank"]
    assert len(body["rows"]) == 2
    assert body["truncated"] is False


async def test_query_route_refuses_writes(client):
    r = await client.get("/api/query", params={"sql": "DROP VIEW rankings"})
    assert r.status_code == 400
    assert "read-only" in r.json()["detail"]


async def test_query_route_caps_rows(client):
    r = await client.get(
        "/api/query", params={"sql": "SELECT name FROM rankings CROSS JOIN range(100)"}
    )
    body = r.json()
    assert len(body["rows"]) == query.MAX_ROWS
    assert body["truncated"] is True


async def test_glossary_route(client):
    r = await client.get("/api/glossary")
    assert r.status_code == 200
    terms = {t["term"]: t for t in r.json()["terms"]}
    b = query.counts()["band"]
    assert (
        f"{b['cold_full']:g} to {b['warm_full']:g}"
        in terms["comfort hours"]["definition"]
    )
    assert "composite" in terms["composite"]["aliases"]
    pt = terms["composite"]["translations"]["pt"]
    assert pt["term"] and pt["aliases"] and pt["definition"]
    # Compressed for clients that take it, plain for the rest.
    assert r.headers["content-encoding"] == "gzip"
    plain = await client.get("/api/glossary", headers={"accept-encoding": "identity"})
    assert "content-encoding" not in plain.headers
    assert plain.json() == r.json()


async def test_caveats_route(client):
    r = await client.get("/api/caveats", params={"answer": f"{FLAGGED} is the best."})
    assert r.status_code == 200
    assert any("Microclimate risk" in c for c in r.json()["caveats"])


async def test_mcp_does_not_shadow_the_static_mount(client):
    # A path that merely starts with /mcp must fall through to the SPA mount
    # (or 404 when no frontend is built), never into the MCP transport.
    r = await client.get("/mcpx")
    assert r.status_code in (200, 404)
    assert "jsonrpc" not in r.text


async def test_mcp_lists_the_tools(client):
    r = await client.post(
        agents.MCP_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=MCP_HEADERS,
    )
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {
        "describe_rankings",
        "query_rankings",
        "caveats_for",
        "read_methodology",
        "ask",
    }


async def test_methodology_route_and_tool(client):
    r = await client.get("/api/methodology", params={"section": "sensitivity"})
    assert r.status_code == 200
    assert r.text.startswith("## ")
    result = await _call(client, "read_methodology", section="sensitivity")
    assert result["isError"] is False
    assert result["content"][0]["text"].startswith("## ")


async def test_mcp_query_returns_structured_rows(client):
    result = await _call(
        client, "query_rankings", sql="SELECT name FROM rankings ORDER BY rank LIMIT 1"
    )
    assert result["isError"] is False
    assert result["structuredContent"]["columns"] == ["name"]
    assert len(result["structuredContent"]["rows"]) == 1


async def test_mcp_query_error_is_readable(client):
    result = await _call(client, "query_rankings", sql="SELECT nope FROM rankings")
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "nope" in text  # DuckDB's own message, not a generic "tool failed"


async def test_mcp_caveats_tool(client):
    result = await _call(client, "caveats_for", answer=f"{FLAGGED} is the best.")
    assert result["isError"] is False
    assert any("Microclimate risk" in c["text"] for c in result["content"])


async def test_mcp_ask_runs_the_graph(client):
    result = await _call(client, "ask", question="where is best?")
    assert result["isError"] is False
    body = result["structuredContent"]
    assert "asked: where is best?" in body["answer"]
    assert body["caveats"], "the caveats node should have annotated the answer"
