"""promptfoo's view of the scope filter: a question in, ALLOW or REFUSE out.

promptfoo is a Node tool, so this file is the whole bridge to the Python under
test. It deliberately calls `guard.build_guard()` — the real thing the graph
wires in — rather than reimplementing the prompt, so an eval run exercises the
same classifier a deployed question meets. Nothing here is importable by the
app; the dependency points one way.

promptfoo spawns a Python process per call, so the `lru_cache` below is not a
cross-case optimisation — it just stops a retried call inside one process from
rebuilding the client.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage

from climate_agent import guard
from climate_agent.main import _load_env

_load_env()  # the classifier needs DEEPSEEK_API_KEY; promptfoo does not load .env


@lru_cache(maxsize=1)
def _guard() -> guard.Guard:
    return guard.build_guard()


def _history(turns: list[dict] | None) -> list:
    """Rebuild a conversation from the `history` var.

    Cases carry history as `{q, a}` pairs because that is what reads well in
    YAML; the guard wants LangChain messages. Only the questions actually reach
    the classifier (see `guard._context`), but the answers are kept here so a
    case reads like the conversation it describes.
    """
    messages = []
    for turn in turns or []:
        messages.append(HumanMessage(turn["q"]))
        messages.append(AIMessage(turn.get("a", "")))
    return messages


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """promptfoo's provider contract. `prompt` is the rendered `{{question}}`."""
    variables = (context or {}).get("vars", {})
    question = variables.get("question", prompt)
    try:
        allowed = asyncio.run(_guard()(question, _history(variables.get("history"))))
    except Exception as exc:  # noqa: BLE001 — the only channel back to Node
        # Reported as an eval *error* rather than a verdict. The guard already
        # fails open on a bad model call, so anything reaching here is a broken
        # bridge — a missing key, an unimportable package — and must not be
        # scored as a passing ALLOW.
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"output": "ALLOW" if allowed else "REFUSE"}
