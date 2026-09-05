# climate-agent

A LangGraph agent answering natural-language questions about outdoor-comfort
city rankings by writing DuckDB SQL over two vendored CSVs in `data/`. Three
nodes: `guard` (cheap DeepSeek scope classifier, fails open) → `climate`
(tool-calling loop over `query_rankings(sql)`) → `caveats` (deterministic, no
LLM). Same graph behind the FastAPI/SSE server and the CLI.

Other agents get the pieces directly: `/mcp` (Streamable HTTP MCP, tools
`describe_rankings`, `query_rankings`, `caveats_for`, `ask`), the same as JSON
under `/api/schema`, `/api/query`, `/api/caveats`, and `/llms.txt` as the map.
All in `src/climate_agent/api/agents.py`, all unauthenticated on purpose.

The model is **DeepSeek**, not Anthropic. `climate.ask_claude` is a historical
name — do not "fix" it into an Anthropic call.

## Three environments

| | Where | Deployed by | URL |
|---|---|---|---|
| dev | this box, `127.0.0.1:8000` | `make api` | localhost only |
| staging | this box, Docker | `make staging` | https://climate.staging.fiodorov.es |
| prod | Railway | **a push to `main`** | https://climate.fiodorov.es |

**Pushing `main` deploys production.** Railway builds from the GitHub repo on
every push. There is no CI and no approval step in between. So: work on a
branch, deploy that branch's working tree to staging, look at it, and merge to
`main` only when the intent is to ship.

`make staging` builds the image from **whatever is checked out right now** — no
commit, no push, no `git` at all. That is the point of it: staging redeploys
when you say so, prod redeploys when `main` moves.

## Running it

The Makefile is the source of truth; the README's "Running it" section explains
each target. Briefly:

```sh
make redis && make api        # dev, :8000 (serves the built UI if make build ran)
make ui                       # Vite on :5173, hot reload, proxies /api to :8000
make staging                  # build + deploy to climate.staging.fiodorov.es
make staging-logs             # follow the staging app
make staging-down
make test                     # 104 tests, no API key — the model is stubbed
make eval                     # 33-case guardrail eval; calls DeepSeek for real, costs money
make format lint              # ruff, line length 88
```

`make eval` is not free and not part of `make test`. Do not run it casually.

## The staging edge lives in another repo

Caddy and the GitHub login are **not** in this repo. They are in
`../staging-infra` (github.com/afiodorov/staging-infra, private), shared by
every staging app on this box: one Caddy terminating TLS, one oauth2-proxy
holding a cookie scoped to `.staging.fiodorov.es`, so one GitHub login covers
all of them. Access is `--github-user=afiodorov` and nobody else.

This repo contributes `docker-compose.staging.yml` — the app plus its own
Redis, joined to the external `staging` Docker network — and nothing else.

- Changing routing or auth → edit `../staging-infra/Caddyfile`, then
  `make check && make reload` there. `reload` is not `restart`: it swaps the
  config without dropping other apps' connections, including live SSE streams.
- The edge must be up (`cd ../staging-infra && make up`) before `make staging`
  is reachable. `make staging` guards on the network existing and says so.

### The invariant: staging services publish no host ports

Not a style rule — it is the security boundary. Docker publishes ports by DNAT
through the FORWARD chain, which **bypasses ufw's INPUT rules entirely**. A
`ports:` line in `docker-compose.staging.yml` would put that service on the
public internet no matter what `ufw status` says. Caddy is the single
deliberate exception.

`/etc/docker/daemon.json` sets `{"ip": "127.0.0.1"}` so a forgotten `ports:`
binds loopback instead of the world. Exposing something publicly therefore has
to be written out explicitly as `0.0.0.0:80:80`. Do not remove that file, and
do not add host port bindings to staging services.

Anything joining the `staging` network needs a globally unique service *and*
container name across all staging projects — Docker registers both as DNS
aliases there. Convention: service `<repo>`, container `<repo>-staging`.

## Secrets

| File | Holds | Tracked? |
|---|---|---|
| `.env` | `DEEPSEEK_API_KEY` for dev and the CLI | no |
| `.env.staging` | `DEEPSEEK_API_KEY` for the staging container | no |
| `../staging-infra/.env` | GitHub OAuth id/secret, oauth2-proxy cookie secret | no |
| Railway variables | prod's `DEEPSEEK_API_KEY`; `REDIS_URL` is injected | n/a |

Never commit any of these, and never paste a key into a commit message, a
README, or an issue.

## Things that will bite you

- **The app hard-fails at boot** without `DEEPSEEK_API_KEY`, a working DuckDB
  `SELECT 1`, or a reachable Redis. That is deliberate — fail at startup, not
  on the first question. A staging container that flaps for a few seconds after
  a reboot is Redis not being healthy yet; it settles.
- **Staging Redis is not the dev Redis.** Both use the `climate:v2:` key
  prefix, so pointing them at one database merges the two conversation rails.
  `REDIS_URL` is set by the compose file — overriding it in `.env.staging` is
  how you would break this by accident.
- **One replica only.** `Gateway._inflight` is an in-process dict, so pending
  turns are not shared. Do not add `deploy.replicas` or a second instance.
- **No CORS middleware**, by design: the Dockerfile serves the SPA and the API
  from one process, so `EventSource` is same-origin. Any deployment must keep
  them on the same host.
- **`GET /api/sessions` is unscoped** — every visitor sees everyone's
  conversations, and there is no rate limit. That is why staging is gated at
  all. Adding a second name to `--github-user` in `../staging-infra` gives that
  person every staging app and a shared conversation rail.
- **SSE needs an unbuffered path.** Caddy flushes `text/event-stream`
  immediately with no configuration, and `forward_auth` does not touch the
  response body. Do not add `encode gzip` to the staging_app snippet — its
  default matcher catches `text/event-stream`.
- **DNS for `*.staging.fiodorov.es` is a wildcard A record at GoDaddy.** New
  apps need no DNS change. GoDaddy's two nameservers can disagree for a few
  minutes after an edit, during which Let's Encrypt can burn one of its five
  failed validations per hostname per hour — hence the commented `acme_ca`
  staging line at the top of the Caddyfile, to uncomment while debugging.
