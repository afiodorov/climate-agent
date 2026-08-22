import logging
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "anthropic", "asyncio", "faststream"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print(f"🌤  Climate Agent API on http://127.0.0.1:{port}")
    uvicorn.run("climate_agent.api.app:app", host="0.0.0.0", port=port)
