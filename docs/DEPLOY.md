# Deploying PersonaLab on Railway

The backend runs as three Railway services built from this repo. Masumi Payment Service (MPS) and its
Postgres are deployed separately; this guide only consumes their URL and a runtime token.

| Service | Image | Railway config file | Process | Public? |
|---|---|---|---|---|
| `graph` | `deploy/graph.Dockerfile` | `railway.graph.json` | `python -m crest_graph.server` (FastAPI + LangGraph) | Only if `MEDIA_PUBLIC=1` (media links) |
| `worker` | `deploy/node.Dockerfile` | `railway.worker.json` | `node worker.mjs` (Sokosumi Task executor + Masumi paid flow) | No |
| `agent-api` | `deploy/node.Dockerfile` | `railway.api.json` | `node agent-api.mjs` (MIP-003 Standard API) | Yes (registered `apiBaseUrl`) |

Set each service's *Config-as-code path* to its `railway.*.json`. All three use restart policy `ON_FAILURE`,
one replica, and no serverless sleep. The Node image picks its process from `SERVICE=worker|api`; the Railway
configs also set an explicit start command, so either works.

Attach a volume to each service at `/data` (the images set `DATA_DIR=/data`). It holds Task journals, the worker
lock, standard jobs, generated media and `personalab.db`. The images run as root because Railway volumes mount
root-owned.

## One-executor rule

Exactly one worker may execute Tasks for a Coworker. **Stop the local worker (`npm run worker`) before the hosted
worker starts**, and keep `worker` at one replica. The file lock in `DATA_DIR` only guards one machine; it cannot
see a worker on another machine, so two executors would start and complete the same Tasks twice. Local journals in
`.local/` are not migrated: a Task a local worker left mid-flight must be finished locally first.

## Environment variables

Names only. Secrets go in Railway service variables (or shared variables referenced per service), never in files
in the image. `.env*` and `.local` are excluded by `.dockerignore`.

### Shared deployment knobs

| Variable | Services | Notes |
|---|---|---|
| `HOSTED` | all | `1` in both images. Relaxes the loopback-only `CREST_GRAPH_URL` check and hides server file paths in results. Unset locally. |
| `DATA_DIR` | all | `/data` in both images; default `.local` locally. |
| `PORT` | graph, agent-api | Injected by Railway. Set `PORT=8080` on `graph` so the private URL is stable. `CREST_GRAPH_PORT` / `AGENT_API_PORT` win if set. |

### graph

| Variable | Secret | Notes |
|---|---|---|
| `CREST_GRAPH_TOKEN` | yes | Bearer token for `/run` and `/approve`; same value on worker and agent-api. |
| `MODEL_API_KEY`, `MODEL_ID` | key is secret | Chat model. Optional: `MODEL_BASE_URL`, `FALLBACK_MODEL_ID`, `MODEL_TIMEOUT_S`, `ZAI_MODEL`. |
| `OPENROUTER_API_KEY` | yes | Trends, images, video and TTS. Optional model ids: `TREND_MODEL_ID`, `IMAGE_MODEL_ID`, `VIDEO_MODEL_ID`, `TTS_MODEL_ID`, `TTS_VOICE`. |
| `CREST_GRAPH_HOST` | no | `::` in the image (dual-stack; Railway private networking can be IPv6). Default `127.0.0.1` locally. |
| `MEDIA_PUBLIC` | no | `1` lets anyone with a link fetch `/media/<run>/<file>`. Name validation and traversal protection still apply; only generated images and `reel.mp4` are served. Default off (loopback only). |
| `PUBLIC_MEDIA_BASE_URL` | no | e.g. `https://graph-xxx.up.railway.app`. Used in result Markdown links when `MEDIA_PUBLIC=1`; otherwise links stay `http://127.0.0.1:PORT`. Requires a public domain on `graph`. |
| `IG_ACCESS_TOKEN`, `IG_USER_ID` | token is secret | Optional live Instagram; DRY-RUN without them. |
| `MAX_USD_PER_TASK`, `IMAGE_GENERATION`, `VIDEO_GENERATION`, `VOICE_ENGINE`, `VIDEO_*`, `IMAGE_*` | no | Optional cost and media tuning. `FFMPEG_PATH` and `VIDEO_FONT_FILE` are preset in the image. |

### worker

| Variable | Secret | Notes |
|---|---|---|
| `COWORKER_ID` | no | The PersonaLab Coworker. |
| `SOKOSUMI_COWORKER_API_KEY` | yes | The `coworker_*` runtime key. When set, the worker lists Tasks with this key alone (personal + organization workspaces, no user OAuth) and pipes it to `sokosumi runtime start/complete --api-key-stdin`. Comments and the paid flow use it too. Unset locally, where the OAuth CLI and OS vault are used. |
| `WORKER_TARGETS` | no | Default `personal,org:<id>:<slug>` (TOKEN2049 org). Tasks in workspaces not listed are skipped. |
| `CREST_GRAPH_URL` | no | Private URL, e.g. `http://graph.railway.internal:8080`. |
| `CREST_GRAPH_TOKEN` | yes | Same as graph. Optional `CREST_GRAPH_TIMEOUT_MS`. |
| `PAID_TASKS_ENABLED` | no | `true` enables the Masumi paid flow for personal Tasks. Optional windows: `PAID_PAY_BY_MIN`, `PAID_SUBMIT_MIN`, `PAID_UNLOCK_MIN`, `PAID_DISPUTE_MIN`. |
| `PAID_ORG_TASKS` | no | `true` also charges organization Tasks whose title contains `[paid]`; other organization Tasks stay free. Needed for a hosted paid run, because the Coworker key lists organization Tasks only. |
| `MPS_URL` | no | Base URL of the separately deployed MPS (no `/api/v1`). |
| `MPS_RUNTIME_TOKEN` | yes | MPS runtime key. Overrides `DATA_DIR/mps-runtime.env`. |
| `BLOCKFROST_API_KEY_PREPROD` | yes | Settlement verification for paid Tasks. |

### agent-api

| Variable | Secret | Notes |
|---|---|---|
| `AGENT_API_HOST` | no | `::` in the image; default `127.0.0.1` locally. |
| `MPS_URL`, `MPS_RUNTIME_TOKEN` | token is secret | As for worker. |
| `CREST_GRAPH_URL`, `CREST_GRAPH_TOKEN` | token is secret | As for worker. |
| `AGENT_API_PUBLIC_URL` | no | The public Railway domain; used when (re)registering `apiBaseUrl`, not at runtime. |

`docs/registration-state.json` (public agent identifier and payment source index, no secrets) is baked into the
Node image; worker and agent-api read it to price jobs.

## Order of operations

1. Deploy `graph` with a volume, `PORT=8080`, and its secrets. Check `GET /health` reports `model_configured: true`.
2. Stop the local worker. Deploy `worker` with a volume and `CREST_GRAPH_URL=http://graph.railway.internal:8080`.
3. Deploy `agent-api` with a volume and a public domain. Re-register the agent's `apiBaseUrl` only if it changes.
4. Optional: give `graph` a public domain, then set `MEDIA_PUBLIC=1` and `PUBLIC_MEDIA_BASE_URL`.

## Local build check

```sh
docker build -f deploy/graph.Dockerfile -t personalab-graph .
docker build -f deploy/node.Dockerfile -t personalab-node .
```

Local behaviour is unchanged when none of these variables are set: loopback binds, `.local/` data, strict
`http://127.0.0.1` graph URL, loopback-only media, and the OAuth CLI + OS vault for Sokosumi.

## Live deployment (verified 2026-10-07)

Sokosumi stays the only user interface (PersonaLab's 4 ready-to-run cards). The backend runs on Railway project `personalab`:

| Service | Address | Notes |
|---|---|---|
| graph | https://graph-production-e6ee.up.railway.app (`/health`) · private `graph.railway.internal:8080` | Binds `0.0.0.0`: uvicorn on `::` disables dual-stack, so the IPv4 public edge returned 502 |
| worker | no public port | `auth coworker-key`, polls personal + TOKEN2049 workspaces; the only executor (local worker stopped) |
| agent-api | https://agent-api-production-78a3.up.railway.app (`/availability`) | Masumi MIP-003 Standard API |
| mps | private `mps.railway.internal:3001` | Database migrated from the local node with the same encryption key; same wallets and registration; local node stopped |
| Postgres | private | Restored with `pg_restore` through a temporary TCP proxy, deleted afterwards |

Hosted proof: Task `01a11661-884f-7083-af8a-225f26881edc` (Trends) READY → RUNNING → COMPLETED with all laptop services stopped.
Showcase page (optional, for judges): https://personalab-site.vercel.app
