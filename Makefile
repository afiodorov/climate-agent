.PHONY: dev api ui build test eval eval-view format lint fmt imports clean redis redis-down

NODE_MODULES := frontend/node_modules

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

ui: $(NODE_MODULES)
	cd frontend && npm run dev

# Build the UI into frontend/dist, which the API mounts at /.
build: $(NODE_MODULES)
	cd frontend && npm run build

# A real file target, not a step inside `ui` and `build`: npm ci wipes and
# reinstalls node_modules from the lockfile, which is the right thing when the
# manifest changed and pure waste on every other run. Make skips it when
# node_modules is newer than both manifests — hence the touch, since npm leaves
# the directory mtime at whenever its last file happened to land.
$(NODE_MODULES): frontend/package.json frontend/package-lock.json
	cd frontend && npm ci
	@touch $@

cli:
	uv run climate-agent

test:
	uv run pytest -q

# The guardrail eval. Unlike `test`, this calls DeepSeek for real — one cheap
# classifier call per case — so it needs a key and costs a fraction of a cent.
# PROMPTFOO_PYTHON is not optional: promptfoo shells out to `python`, which on
# most boxes is either missing or the wrong interpreter.
eval:
	cd evals && PROMPTFOO_PYTHON=$(CURDIR)/.venv/bin/python npx -y promptfoo@latest eval --no-cache

# The last run's results as a browsable table.
eval-view:
	cd evals && npx -y promptfoo@latest view --yes

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
