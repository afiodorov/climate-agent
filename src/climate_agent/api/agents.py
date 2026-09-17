"""The surface for other agents: MCP tools, plain JSON routes, and llms.txt.

An outside agent — Claude, ChatGPT, anything with an MCP client — does its own
reasoning, so what it needs from this service is the data, not the chat. The
tools here are the pieces the `climate` node is built from, handed out one by
one: the schema, the read-only SQL runner, and the caveat lookup. `ask` is kept
too, for a caller that would rather have the finished answer and pay for the
DeepSeek turn.

Three transports, one set of functions:

- `/mcp`: Streamable HTTP MCP, stateless, JSON responses. What Claude Code,
  claude.ai connectors, the Messages API and the OpenAI Responses API consume.
- `/api/schema`, `/api/query`, `/api/caveats`: the same tools as GET routes,
  for an agent that only has a web fetch. FastAPI's own `/openapi.json`
  describes them.
- `/llms.txt`: the map. What this is, what the columns mean, where the above
  live.

Nothing here has auth. The data is public and read-only, and `/api/ask` was
already open, so this widens no door; it only adds better-shaped ones.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .. import caveats, gateway, glossary, query

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"

# Set by the app's lifespan. Only `ask` needs it; the other tools are pure
# functions over the CSVs and work before it is set.
_gateway: gateway.Gateway | None = None


def attach(human: gateway.Gateway) -> None:
    global _gateway
    _gateway = human


def about() -> str:
    c = query.counts()
    return (
        f"A ranking of the {c['n_cities']} cities with population >= "
        f"{c['min_population']:,} by outdoor "
        "thermal comfort: how many daylight hours a year the UTCI (Universal Thermal "
        "Climate Index, computed hourly from ERA5 reanalysis, "
        f"{c['start_year']}-{c['end_year']}) falls inside a comfortable band. "
        "`comfort_hours_yr` is the headline metric; `composite` additionally penalises "
        "seasonal unevenness and PM2.5, and is what `rank` sorts by. Smaller cities "
        "appear as unranked reference rows. The same hourly record is also here "
        "re-aggregated — a UTCI histogram by month, daylight and dew point, and a "
        "month-by-hour profile — so SQL can rebuild the ranking under another comfort "
        "band, at night, or with a humidity filter."
    )


def honesty() -> str:
    """What every reader should know before quoting a number. The same facts
    the `caveats` node attaches to chat answers, stated once up front."""
    c = query.counts()
    tau = query.sensitivity_summary().get("metric_raw_hours", 0.56)
    return f"""\
- "Best" depends on the metric. Raw comfort hours and the composite agree only \
moderately (Kendall tau ~= {tau:.2f}); say which one you ranked by.
- `microclimate_risk` is True for {c["n_flagged"]} of {c["n_cities"]} cities: the ERA5 \
grid cell may not represent the city itself (coast, steep relief). Mention it when you \
name one.
- `sensitivity.rank_volatility` is how far a city's rank moves across \
{c["n_variants"]} scoring variants. A city whose spread exceeds its own rank is a \
scoring artefact, not a fact.
- `is_reference` rows are below the population floor and carry no rank.
- Anything rebuilt from `utci_histogram` or `hourly_profile` is recomputed under your \
own assumptions, not the published ranking; say so. Humidity is ERA5's cell-mean dew \
point, and UTCI already includes it.
- Never state a number you have not read out of a query result."""


def describe() -> dict[str, Any]:
    return {
        "about": about(),
        "schema": query.schema().strip(),
        "notes": honesty(),
        "max_rows": query.MAX_ROWS,
    }


def _query(sql: str) -> dict[str, Any]:
    result = query.run_query(sql)
    return {
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
    }


# --- MCP ---------------------------------------------------------------------

server = MCPServer(
    "climate",
    title="City outdoor comfort rankings",
    instructions=(
        "A ranking of the world's large cities by outdoor thermal comfort, plus the "
        "aggregated hourly UTCI record behind it. Call describe_rankings once for the "
        "schema, then query_rankings with DuckDB SQL. Pass your draft answer to "
        "caveats_for before presenting it. read_methodology explains how the index "
        "is built and what it leaves out."
    ),
)


@server.tool()
def describe_rankings() -> dict[str, Any]:
    """Every view and table, every column and what it means, the SQL macros, worked
    recipes, and the caveats that apply to any answer built on them. Read this
    once before writing SQL."""
    return describe()


@server.tool()
def read_methodology(section: str = "") -> str:
    """The pipeline's own write-up: method, sun exposure, the five metrics,
    sensitivity, known limitations, reproduction. Pass a `##` heading to get one
    section, or nothing for the whole document.

    Args:
        section: Part of a section heading, e.g. "limitations". Empty = all.
    """
    return query.methodology(section)


@server.tool()
async def query_rankings(sql: str) -> dict[str, Any]:
    """Run a read-only DuckDB SELECT over the views and tables `describe_rankings` lists.

    Returns columns and at most 60 rows; `truncated` is true when there were more,
    so add LIMIT or aggregate. Only SELECT and WITH statements are accepted.

    Args:
        sql: A DuckDB SELECT statement.
    """
    try:
        return await asyncio.to_thread(_query, sql)
    except query.QueryError as exc:
        # ToolError reaches the caller with its text; anything else is treated
        # as a crash and replaced with a generic message. A refused or broken
        # query is the caller's mistake, and they need to read why.
        raise ToolError(str(exc)) from exc


@server.tool()
async def caveats_for(answer: str) -> list[str]:
    """The honesty notes that apply to a draft answer: microclimate risk, unstable
    ranks, unranked reference cities, and metric ambiguity. Deterministic, no LLM.

    Args:
        answer: The prose you are about to present, city names included.
    """
    return await asyncio.to_thread(caveats.caveats_for, answer)


@server.tool()
async def ask(question: str, session_id: str = "") -> dict[str, Any]:
    """Ask the hosted agent in natural language and get its finished answer plus
    caveats. Slower and lossier than querying yourself; use it when you want a
    second opinion or do not want to write SQL.

    Args:
        question: A question about city outdoor comfort.
        session_id: Pass the same value again to make this a follow-up.
    """
    if _gateway is None:
        raise ToolError("The hosted agent is not running.")
    final = await _gateway.ask(question, session_id.strip() or None)
    return {"answer": final.answer, "caveats": final.caveats}


# A one-route Starlette app the FastAPI app registers at MCP_PATH; its session
# manager has to be run inside the outer app's lifespan, see `app.py`.
#
# Stateless: no session ids, every call stands alone, which is what a read-only
# server behind a load balancer wants. JSON responses rather than SSE for the
# same reason, and so `curl` shows something readable.
#
# Behind Caddy or Railway the Host header is the public name, so the SDK's
# localhost-only rebinding guard would reject every real request. There is no
# session or credential here for a rebinding attack to steal.
mcp_app = server.streamable_http_app(
    streamable_http_path=MCP_PATH,
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# --- Plain HTTP --------------------------------------------------------------

router = APIRouter()


@router.get("/api/schema")
def schema() -> dict[str, Any]:
    """The views, their columns, and the caveats. JSON twin of `describe_rankings`."""
    return describe()


@router.get("/api/query")
async def run(sql: str = "") -> dict[str, Any]:
    """A read-only SELECT as JSON: `columns`, `rows`, `truncated`."""
    if not sql.strip():
        raise HTTPException(status_code=400, detail="sql must not be empty")
    try:
        return await asyncio.to_thread(_query, sql)
    except query.QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/methodology", response_class=PlainTextResponse)
def methodology(section: str = "") -> str:
    """The pipeline's methodology document, whole or one `## section`."""
    return query.methodology(section)


@router.get("/api/caveats")
async def notes(answer: str = "") -> dict[str, list[str]]:
    """The caveats that apply to a draft answer. JSON twin of `caveats_for`."""
    return {"caveats": await asyncio.to_thread(caveats.caveats_for, answer)}


@router.get("/api/glossary")
async def terms() -> dict[str, list[glossary.Entry]]:
    """Plain-language definitions of the ranking's terms, numbers from the data.

    The UI marks these in every answer; other clients can do the same."""
    return {"terms": await asyncio.to_thread(glossary.glossary)}


def llms_txt(base: str) -> str:
    base = base.rstrip("/")
    return f"""\
# Climate: city outdoor comfort rankings

> {about()}

Free, read-only, no auth. Query it directly rather than scraping the chat UI.

## MCP (preferred)

Streamable HTTP endpoint: {base}{MCP_PATH}
Tools: describe_rankings, query_rankings(sql), caveats_for(answer), read_methodology(section), ask(question).

- Claude Code: `claude mcp add --transport http climate {base}{MCP_PATH}`
- Claude API: mcp_servers=[{{"type": "url", "url": "{base}{MCP_PATH}", "name": "climate"}}]
- OpenAI Responses API: tools=[{{"type": "mcp", "server_label": "climate", "server_url": "{base}{MCP_PATH}", "require_approval": "never"}}]

## Plain HTTP

- {base}/api/schema — views, columns, caveats (JSON)
- {base}/api/query?sql=SELECT+name,+rank+FROM+rankings+ORDER+BY+rank+LIMIT+10 — read-only DuckDB, max {query.MAX_ROWS} rows (JSON)
- {base}/api/caveats?answer=... — honesty notes for a draft answer (JSON)
- {base}/api/glossary — plain-language definitions of the terms, with aliases (JSON)
- {base}/api/methodology?section=limitations — how the index is built and what it misses (text)
- {base}/api/ask?q=... — the hosted agent, as server-sent events
- {base}/openapi.json — the OpenAPI description of all of the above

## Before you quote a number

{honesty()}

## Schema

{query.schema().strip()}
"""


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms(request: Request) -> str:
    # Built from the request so staging and prod each name themselves. Uvicorn
    # only trusts X-Forwarded-Proto from loopback, and neither Caddy nor
    # Railway's edge is that, so the scheme is fixed up here: anything that is
    # not a dev loopback is behind TLS.
    base = request.base_url
    if base.hostname not in ("localhost", "127.0.0.1", "::1"):
        base = base.replace(scheme="https")
    return llms_txt(str(base))
