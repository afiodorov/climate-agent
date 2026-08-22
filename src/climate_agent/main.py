"""Build the graph and run the CLI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import climate, gateway, query, store


def _load_env() -> None:
    """Bare load_dotenv() searches upward from *this file*, which breaks once the
    package is installed outside the project. Check the cwd and the project root."""
    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


async def main() -> None:
    _load_env()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    # At DEBUG these bury our own logging in HTTP frames and request payloads.
    for noisy in ("httpx", "httpcore", "openai", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set. Put it in .env or export it.")
        raise SystemExit(1)
    try:
        query.run_sql("SELECT 1")
    except query.QueryError as exc:
        print(exc)
        raise SystemExit(1) from exc

    sessions = store.build()
    try:
        await sessions.ping()
    except Exception as exc:
        print(
            f"Redis unreachable at {getattr(sessions, 'url', '?')} — run `make redis`"
        )
        raise SystemExit(1) from exc

    # The repl shares the store with the API, so a conversation started here
    # shows up in the web UI too.
    human = gateway.Gateway(climate.build_graph(), store_=sessions)
    try:
        await gateway.repl(human)
    finally:
        await sessions.close()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    run()
