# PersonaLab: AI influencer Coworker on Sokosumi

PersonaLab is a Sokosumi Coworker with four ready-to-run tasks, **Create → Schedule → Engage → Analyze**.
A Python LangGraph supervisor runs each task. A Node worker picks up Sokosumi Tasks and handles runtime and payment.
The full plan is in [`docs/PLAN.md`](docs/PLAN.md). Current progress is in [`docs/setup-state.md`](docs/setup-state.md).

```
Sokosumi Task ──► worker.mjs (Node) ──HTTP──► crest-graph (Python LangGraph)
                    runtime start/complete       supervisor ─► persona → content   (Create)
                    payment (paid-task.mjs)                  ├► scheduler_agent    (Schedule)
                                                             ├► engage_agent       (Engage)
                                                             └► analyst_agent      (Analyze)
```

## Requirements
Node.js 24 or newer, Python 3.12 with `uv`, and Sokosumi CLI 1.0.4 or newer, signed in as the Vendor admin.

## Configuration
| File | Contents | Git |
|---|---|---|
| `.env` | Non-secret settings (model ID, ports, `COWORKER_ID`) | ignored |
| `.env.local` | Secrets: `MODEL_API_KEY`, `SOKOSUMI_COWORKER_API_KEY`, `CREST_GRAPH_TOKEN` (file mode 600) | ignored |
| `.env.example` | Variable names and file precedence, without secret values | committed |

Precedence: real process environment, then `.env.local`, then `.env`. The Node scripts (`--env-file`) and the Python loader (`crest_graph/config.py`) follow the same order.

## Run
```sh
npm ci && (cd crest-graph && uv sync)
npm start          # LangGraph service on 127.0.0.1:21951
npm run smoke      # one real model turn through the graph
npm run worker     # second terminal: polls Tasks assigned to COWORKER_ID
npm test && npm run test:graph
```
On Windows, stopping `npm start` can leave `python.exe` running on port 21951. Stop it by PID if that happens.

## Ready-to-run tasks
The cards are defined in `coworker/offers.json` and applied with:
```sh
sokosumi --preprod coworkers update COWORKER_ID --metadata-file coworker/offers.json --json
```
Each card's prompt starts with `[stage:create|schedule|engage|analyze]`, and the supervisor routes on that tag.
Untagged input is classified by the model.
Core requires `metadata.channels` to be a record, `profile.llm` to be an array of strings, and `profile.hosting` to be a string.

## Windows notes
- `sokosumi-cli.mjs` runs the CLI's JS entry point through `node`, because `execFileSync('sokosumi')` cannot start the `.cmd` shim.
- CLI 1.0.4 `auth login` opens the URL with `cmd /c start`, which cuts the URL at `&`. See the error history in `docs/setup-state.md`.
