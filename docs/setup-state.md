# Setup state (current)

Secrets never go in this file.

## Purpose
PersonaLab: a Sokosumi Coworker that builds a real creator's virtual avatar, researches cited TikTok/Reels trends, and turns one trend into scripts or a 9:16 AI video reel, paid per task through Masumi on Cardano Preprod.
Quality check: fixed output sections; trends kept only with a search-returned URL; figures only if they appear in the cited source; personas original, AI disclosure recommended.
(Earlier draft purpose, kept for history: faceless AI-avatar video package for creators, demo brand "Calm Ledger".)

## Current state (verified 2026-10-07)
- 4 final offer cards live on PersonaLab: Onboarding: Build Your Virtual Avatar, Create: AI Influencer Reel & Video Ad, Script: Trend-based Reels & TikToks, Trends: What's Hot on TikTok & Reels
- Schedule / Engage / Analyze remain in code (Instagram API dry-run), not offered: Sokosumi cannot link Instagram/TikTok
- Create pipeline: trend swarm -> persona -> scene script citing trend URL -> keyframes (Gemini 3.1 Flash Lite Image) -> image-to-video clips (xAI Grok Imagine Video 1.5 Lite) + voiceover -> 9:16 MP4; ffmpeg fallback
- Real model smoke test passed (28 s)
- Event workspace access GRANTED: 01a11580-fdb2-7259-86af-18c58e2ae61e
- Tasks COMPLETED: Engage rehearsal 01a115be-d0ca-77d5-bf90-b98aa4487fec (personal, event 01a115bf-b375-7779-9ebf-e3cb43b24c7c); Schedule 01a115c6-b98d-75bd-b5b0-7ab2f85d4ab4 (event workspace); Trends 01a115f9-4653-7647-8b15-c5a3e10f5b30 (event workspace, 8 trends, 7 cited URLs)
- MPS (rev 99d94cf3) on 127.0.0.1:38127 with dedicated Postgres; payment source Web3CardanoV2 Preprod (docs/payment-state.json)
- Masumi registration RegistrationConfirmed, tx ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1 (docs/registration-state.json)
- MIP-003 agent API smoke passed (docs/masumi-api-smoke.json)
- Seller wallet funded: txs a70a791880b55cae34a0cdf6756f0c5f37ba8325dad5ce63acc184f5da181d3a, 9ae55b9f842a32c69c49a3774f0b61ae02c9d029ebe6f39ca2eb1cef0b885cd0
- PAID Task 01a115db-7a10-7148-8526-d516924c360c COMPLETED: escrow ead8e54b... (FundsLocked), result 02b70f55... (ResultSubmitted), collection ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3 (Withdrawn); Core receipt settled; seller net 1 tUSDM (docs/paid-proof.json)
- Services run locally on the operator machine; no hosted deployment

## Earlier checkpoints (history)
- Node v24.15.0, pnpm 10.24.0, git 2.47.0, Docker 28.0.4 (daemon later started for MPS)
- Sokosumi CLI 1.0.4 installed globally
- Template: masumi-network/demo-agent-token2049 branch live-demo-name-finder @ ff35ea7
- eve 0.71.0 (locked, later removed); local tests 23/23 pass on Windows after path/permission fixes
- Model: DeepSeek V4.1 Flash (OpenRouter fallback); smoke-tested

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
- eve removed; client.mjs/comments.mjs call crest-graph
- Offer cards updated several times; final set is the 4 cards above
- Resolved: MODEL_API_KEY was missing (smoke failed "Agent service has no model configured"); key added, smoke passed
- Resolved: rehearsal Task done with a real model answer (01a115be-d0ca-77d5-bf90-b98aa4487fec)

## Pending (human)
- [x] OAuth login (via Windows URL-open workaround)
- [x] Organization joined (TOKEN2049); Vendor and Coworker reused
- [x] MODEL_API_KEY in `.env.local`
- [x] Payment DB: Docker Postgres for MPS
- [ ] Demo video, Google Drive slides link, team names, BuilderBase submission (see docs/SUBMISSION.md)

## Windows changes vs template
- `sokosumi-cli.mjs`: runs CLI JS entry via node (no .cmd shim)
- `sokosumi-runtime.mjs`: separator-neutral skills path check
- tests: path separators; POSIX mode assertion skipped on win32

## Error history
- 2026-10-07: first login as secondary account; owner is owner account. Logged out; relogin used a print-only URL opened in the owner account browser.
- 2026-10-07: `coworkers update` 422s: metadata.channels must be a record; profile.llm must be an array; profile.hosting must be a string. Fixed in coworker/offers.json.
- 2026-10-07: stopping `npm start` on Windows left python.exe on :21951; stopped by PID.
- 2026-10-07: `auth login` timed out twice ("OAuth login timed out waiting for the browser callback"). Cause: CLI 1.0.4 opens the URL with `cmd /c start "" URL`; cmd truncates at `&`. Fix: preload script redirecting to `rundll32 url.dll,FileProtocolHandler URL`.
- 2026-10-07: MPS `POST /registry` returned 400: description >250 chars. No record created; pending cleared; shortened and re-registered -> RegistrationConfirmed.
- 2026-10-07: agent-api `/start_job` lacked `sellerVKey`. Fixed with `sellerVkeyOf()` (payment SmartContractWallet vkey, then registry); smoke `missingFields: []`.
- 2026-10-07: worker exited with code 127; restarted, journal resumed without repeating steps.
- 2026-10-07: image model safety filter rejected keyframe prompts with negated wording ("not a real person"); prompts now state requirements positively.
- 2026-10-07: first paid-Task terms (payBy +5 min) expired with no escrow lock. Fresh terms on the same Task with payBy +15 min -> FundsLocked, ResultSubmitted, Withdrawn.
