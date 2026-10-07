# PersonaLab: AI influencer Coworker on Sokosumi

PersonaLab is a Sokosumi Coworker with four ready-to-run tasks: **Onboarding → Create → Script → Trends**.
It builds a real creator's virtual avatar, finds what is trending on TikTok and Reels (cited sources only), and turns one trend into scripts or a 9:16 AI video reel.
A Python LangGraph supervisor runs each task. A Node worker picks up Sokosumi Tasks and handles runtime and Masumi payment on Cardano Preprod.
The full plan is in [`docs/PLAN.md`](docs/PLAN.md). Current progress is in [`docs/setup-state.md`](docs/setup-state.md).

```
Sokosumi Task ──► worker.mjs (Node) ──HTTP──► crest-graph (Python LangGraph)
                    runtime start/complete       supervisor ─► onboarding_agent                                  (Onboarding)
                    payment (paid-task.mjs)                  ├► trend_swarm → persona → content → media → video   (Create)
                                                             ├► trend_swarm → script_writer                       (Script)
                                                             └► trend_swarm → trend_writer                        (Trends)
                                                 trend_swarm = LangGraph Send fan-out to parallel researchers
                                                 in code, not offered: scheduler / engage / analyst agents (Instagram API dry-run)
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

| Card | Tag | What it delivers |
|---|---|---|
| Onboarding: Build Your Virtual Avatar | `[stage:onboarding]` | A real creator's interests, values, story, expertise and moat → personal avatar profile, voice, visual identity, guardrails and a reusable Avatar JSON |
| Create: AI Influencer Reel & Video Ad | `[stage:create]` | Trend swarm → persona → scene script citing the trend URL → persona-consistent keyframes (Gemini 3.1 Flash Lite Image) → AI image-to-video clips (xAI Grok Imagine Video 1.5 Lite) + voiceover → 9:16 MP4 (ffmpeg fallback) |
| Script: Trend-based Reels & TikToks | `[stage:scripts]` | Cited trend analysis plus production-ready short-video scripts |
| Trends: What's Hot on TikTok & Reels | `[stage:trends]` | Parallel research swarm; only trends with a cited URL survive, and figures must appear in the cited source |

The supervisor routes on the tag; untagged input is classified by the model.
Schedule, Engage and Analyze stay in the code (Instagram API in dry-run) but are not offered as cards, because Sokosumi cannot link Instagram or TikTok accounts.
Core requires `metadata.channels` to be a record, `profile.llm` to be an array of strings, and `profile.hosting` to be a string.

## Create: trend-based AI reel
`[stage:create]` runs `trend_swarm → persona_agent → content_agent → media_agent → video_agent`.
The swarm (`TREND_CREATE_SWARM_SIZE`, default 2, `0` = off) is skipped when the brief already contains a pasted trend report or script.
The content agent picks one cited trend and writes one 15-20 s script with 4-6 timed scenes. The media agent renders a persona reference portrait and one 9:16 keyframe per scene.
The video agent writes `.local/media/<run>/reel.mp4` (9:16, H.264 + AAC, at most 60 s), served on loopback at `/media/<run>/reel.mp4`:
- AI clips: one image-to-video clip per scene through OpenRouter's video API (`VIDEO_MODEL_ID`, default `x-ai/grok-imagine-video-1.5-lite`, 720p). Capped by `VIDEO_MAX_CLIPS` (default 4) and the `MAX_USD_PER_TASK` budget left after trend research and images.
- Fallback: a Ken Burns move over the scene keyframe, assembled locally with ffmpeg (`FFMPEG_PATH`, then `PATH`, then the `imageio-ffmpeg` wheel). Assembly adds crossfades and burned-in captions inside the Reels safe area.
- Voiceover: OpenRouter TTS (`TTS_MODEL_ID`, `TTS_VOICE`), then Windows System.Speech, then a silent AAC track (`VOICE_ENGINE=auto|openrouter|windows|none`).
- Switches: `VIDEO_GENERATION=off` turns off the whole step and `VIDEO_AI=off` forces local assembly. `VIDEO_SIZE` is `720x1280` or `1080x1920`.
A video failure never fails the Task. The output then says `video not generated: <reason>`.

## Windows notes
- `sokosumi-cli.mjs` runs the CLI's JS entry point through `node`, because `execFileSync('sokosumi')` cannot start the `.cmd` shim.
- CLI 1.0.4 `auth login` opens the URL with `cmd /c start`, which cuts the URL at `&`. See the error history in `docs/setup-state.md`.

## Evidence
Verified on Sokosumi and Cardano Preprod on 2026-10-07:
- Paid Task `01a115db-7a10-7148-8526-d516924c360c` `COMPLETED`, 1 tUSDM escrowed and collected by the seller (net receipt 1 tUSDM): [`docs/paid-proof.json`](docs/paid-proof.json)
  - escrow [`ead8e54b…e019c`](https://preprod.cardanoscan.io/transaction/ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c), result [`02b70f55…41b7`](https://preprod.cardanoscan.io/transaction/02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7), collection [`ec5b8dad…3bc3`](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3)
- Masumi registration `RegistrationConfirmed`, tx [`ca5832b5…5dc1`](https://preprod.cardanoscan.io/transaction/ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1): [`docs/registration-state.json`](docs/registration-state.json)
- MIP-003 agent API smoke test: [`docs/masumi-api-smoke.json`](docs/masumi-api-smoke.json)
- Unpaid Tasks `COMPLETED`: Engage rehearsal `01a115be-d0ca-77d5-bf90-b98aa4487fec` (personal), Schedule `01a115c6-b98d-75bd-b5b0-7ab2f85d4ab4` and Trends `01a115f9-4653-7647-8b15-c5a3e10f5b30` (event Workspace; 8 trends, 7 cited URLs)
- Full checklist: [`docs/SUBMISSION.md`](docs/SUBMISSION.md). Services run locally on the operator machine; there is no hosted deployment.
