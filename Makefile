.PHONY: dev api ui build test format lint fmt imports clean redis redis-down

# Two processes in dev: uvicorn on :8000, Vite on :5173 proxying /api to it.
# Open http://localhost:5173 for hot reload; :8000 serves the built UI.
# `api` needs Redis for session storage and refuses to boot without it.
dev:
	@echo "run these in three shells:"
	@echo "  make redis"
	@echo "  make api"
	@echo "  make ui"

# Session storage. Conversations survive an API restart; `down` keeps the volume.
redis:
	docker compose up -d redis

redis-down:
	docker compose down

api:
	uv run python -m climate_agent.api

ui:
	cd frontend && npm run dev

# Build the UI into frontend/dist, which the API mounts at /.
build:
	cd frontend && npm install && npm run build

cli:
	uv run climate-agent

test:
	uv run pytest -q

format:
	uv run ruff check --select I --fix .
	uv run ruff format .

imports:
	uv run ruff check --select I --fix .

fmt:
	uv run ruff format .

lint:
	uv run ruff check .

clean:
	rm -rf frontend/dist frontend/node_modules .pytest_cache
