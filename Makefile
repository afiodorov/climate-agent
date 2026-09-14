.PHONY: dev api ui build test eval eval-view format lint fmt imports clean redis redis-down \
        staging staging-down staging-logs staging-prune data

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

# Vendor a fresh pipeline run from the sibling checkout. Everything in data/
# must come from ONE run of ../climate (score, sweep, report, export-agent):
# the histogram is checked against rankings.csv, and a mismatch is a bug. The
# manifest is written last by the pipeline, so it being older than
# rankings.csv means the export was not re-run.
CLIMATE_OUT := ../climate/out
data:
	@test -f $(CLIMATE_OUT)/agent/manifest.json || \
		{ echo "no $(CLIMATE_OUT)/agent/manifest.json — run 'uv run cli.py export-agent' in ../climate"; exit 1; }
	@test ! $(CLIMATE_OUT)/rankings.csv -nt $(CLIMATE_OUT)/agent/manifest.json || \
		{ echo "rankings.csv is newer than the agent export — re-run export-agent in ../climate"; exit 1; }
	mkdir -p data/agent
	cp $(CLIMATE_OUT)/rankings.csv $(CLIMATE_OUT)/sensitivity.csv $(CLIMATE_OUT)/sensitivity_summary.csv data/
	cp $(CLIMATE_OUT)/README.md data/methodology.md
	cp $(CLIMATE_OUT)/agent/*.parquet $(CLIMATE_OUT)/agent/manifest.json data/agent/
	@du -sh data

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

STAGING := docker compose -f docker-compose.staging.yml

# Staging on this box: https://climate.staging.fiodorov.es, behind a GitHub
# login. Builds the image from the working tree — no commit, no push, no
# Railway — so what you are looking at is what is checked out right now. Prod
# still deploys from a push to GitHub and is untouched by any of this.
#
# The shared Caddy + oauth2-proxy edge lives in ../staging-infra and has to be
# up first; this only brings up the app and its own Redis, neither of which
# publishes a port.
staging:
	@docker network inspect staging >/dev/null 2>&1 || \
		{ echo "no 'staging' network — run 'make up' in ../staging-infra first"; exit 1; }
	$(STAGING) up -d --build

staging-down:
	$(STAGING) down

staging-logs:
	$(STAGING) logs -f climate-agent

# Every `make staging` orphans the previous image and grows the build cache.
# Neither is urgent on a 955 GB disk, but a month of them adds up. Deliberately
# not folded into `staging` — that would throw away the cache that makes the
# rebuild fast. Safe: nothing in use is removed.
staging-prune:
	docker image prune -f
	docker builder prune -f
