# Setup state (current)

Secrets never go in this file.

## Purpose
For creators and small companies, turn a brand profile and topic into a faceless AI-avatar video package (script, scenes, avatar/voice direction, captions, post copy), so they can publish branded videos without showing their face.
Demo input: "Brand: Calm Ledger, bookkeeping for freelancers. Topic: 3 tax mistakes freelancers make. 30s TikTok."
Quality check: all 8 sections present; script length fits target; no invented stats; avatar never resembles a real person.

## Verified checkpoints (2026-10-07)
- Node v24.15.0, pnpm 10.24.0, git 2.47.0, Docker 28.0.4 (daemon NOT running)
- Sokosumi CLI 1.0.4 installed globally
- Template: masumi-network/demo-agent-token2049 branch live-demo-name-finder @ ff35ea7
- eve 0.71.0 (locked); local tests 23/23 pass on Windows after path/permission fixes
- Model: OpenRouter `deepseek/deepseek-v4.1-flash` (not yet smoke-tested)

## Owner account (switched 2026-10-07)
- owner account, user 01a10f4d-c64d-7079-97e6-d85d058ad45c
- Org TOKEN2049 01a109d1-32a9-71a3-a0e3-658b2a7987cd (member)
- Vendor CardanoFish 01a1156a-7184-77bb-a15f-f712b72381be (admin) - reuse
- Coworker PersonaLab 01a1156a-dbc8-7360-813b-043c0e148296 (tasks) - reuse
- secondary account account: logged out, nothing created there

## Phase 0 checkpoint (verified 2026-10-07)
- Personal access GRANTED: access id 01a1156a-e7c6-722c-bf42-143aa4a3b154, personal workspace 01a10f4e-05f4-7671-abe3-9b702c901915
- Runtime key created and saved to .env.local and the CLI vault (vault import succeeded); value never printed
- COWORKER_ID set in .env

## Phase 1 progress (verified 2026-10-07)
- crest-graph (Python 3.12, langgraph 1.2.14, langchain-openai 1.6.7, fastapi 0.142.2) running on 127.0.0.1:21951 (`npm start`); bearer-token auth verified (401 without token)
- eve removed; client.mjs/comments.mjs call crest-graph; Node tests 22/22, Python tests 6/6 (fake model)
- 4 offer cards live on PersonaLab (coworkers update succeeded): Create / Schedule / Engage / Analyze
- BLOCKED: MODEL_API_KEY absent from .env.local and environment -> `npm run smoke` fails "Agent service has no model configured". No real model turn yet.
- NOT DONE: rehearsal Task (create -> runtime start -> result -> runtime complete). Waiting for a working model so the result is a real model answer.

## Pending (human)
- [x] OAuth login (via Windows URL-open workaround); whoami = intended account, platformRole user, user id 01a10f86-1b50-7089-b38b-c851b253f771
- [x] Personal Workspace exists; vendors: none; owned coworkers: none
- [ ] Create or join an organization in Sokosumi Web (required before Vendor creation); `workspaces list` currently empty
- [ ] Put `MODEL_API_KEY=` (OpenRouter key) in `.env.local`
- [ ] Payment DB: dedicated Supabase project (Supabase MCP not connected) or start Docker Desktop

## Not started
Model smoke test, execution Task, MPS, wallets, registration, paid Task, event join.

## Windows changes vs template
- `sokosumi-cli.mjs`: runs CLI JS entry via node (no .cmd shim)
- `sokosumi-runtime.mjs`: separator-neutral skills path check
- tests: path separators; POSIX mode assertion skipped on win32

## Error history
- 2026-10-07: first login as secondary account; owner is owner account. Logged out; relogin used a print-only URL opened in the owner account browser.
- 2026-10-07: `coworkers update` 422s: metadata.channels must be a record; profile.llm must be an array; profile.hosting must be a string. Fixed in coworker/offers.json.
- 2026-10-07: stopping `npm start` on Windows left python.exe on :21951; stopped by PID.
- 2026-10-07: `auth login` timed out twice ("OAuth login timed out waiting for the browser callback"). Cause: CLI 1.0.4 opens the URL with `cmd /c start "" URL`; cmd truncates at `&`. Fix: preload script redirecting to `rundll32 url.dll,FileProtocolHandler URL`.
