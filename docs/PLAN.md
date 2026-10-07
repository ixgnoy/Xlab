# Plan: "Crest" — an AI-influencer Coworker on Sokosumi

Level L4 (novel, multi-system, money + social-account side effects). Validate with the owner before Phase 2.

**Owner account:** owner account (TOKEN2049 Origins Hackathon 2026 workspace member).
**Goal:** one Sokosumi Coworker whose four ready-to-run tasks reproduce Postcrest's feature set, Create → Schedule → Engage → Analyze. Each task is backed by a LangGraph sub-agent that is also registered as a Masumi agent, so it can be hired on its own inside Sokosumi.

> "Clone" means **feature parity**, built with our own code, name, copy and visuals. We do not copy Postcrest's branding, text, UI assets or code.

---

## 1. Research summary (what the plan is built on)

Tags: **V** = verified in docs or source · **I** = inferred.

### 1.1 Postcrest feature inventory (V, postcrest.com, /pricing, /ai-characters, /instagram)

| Stage | Postcrest does | Crest MVP | Crest later |
|---|---|---|---|
| **Create** | Persona from presets or 5–10 photos, trained in about 5 minutes. Photos up to 4K; reels, carousels and stories; talking-head lip-sync in 30+ languages; TTS and voice clone; captions and hooks; 30-day ideas. | Persona from a text brief or reference images. Images (FLUX LoRA or Kontext), one 5–10s reel (image-to-video), voiceover, captions. | Long-form video, music, infographics |
| **Schedule** | Direct publishing to Instagram, YouTube and X; 30-day calendar; best-time suggestions; TikTok export only | Instagram Reels, images and carousels with our own scheduler; best-time suggestions | YouTube Shorts, X |
| **Engage** | Reads comments and DMs and drafts on-brand replies; a human approves each with one tap; flags conversations worth answering yourself | Drafts comment and DM replies, approved by a human (LangGraph interrupt), with an automation disclosure | Keyword-triggered private replies |
| **Analyze** | Reach, saves, shares, retention and watch time; top performers; hook analysis; "what to post next" | Reel and account insights, a top-post ranking, hook scoring, a next-week content plan that feeds back into Create | Cohort and A/B testing (trial reels) |

Pricing reference: Starter $19, Premium $49, Pro $99 per month, credit-based. Images cost 5–60 credits and video 40–400+.

### 1.2 Sokosumi and Masumi facts that shape the design

- **Ready-to-run task cards (V).** The cards in the screenshot ("Planning", PDF or Document output, owned by a Coworker like "Elena") are `Coworker.metadata.offers`. A Vendor admin sets them:
  - Command: `sokosumi --preprod coworkers update ID --metadata-file offers.json`
  - Each offer: `{title, prompt, category, description, deliverable, outputs:[{type: pdf|image|slides|doc|sheet|text|html, url?, content?}]}`
  - This gives us our four cards.
- **Coworker execution (V).** The flow is `tasks create` → worker `runtime start` → do the work → `runtime complete --result-file`. The result is UTF-8 text up to 1 MiB, so media is returned as URLs.
- **A Coworker can hire Masumi agents (V).** `POST /v1/tasks/{id}/jobs {agentId, inputData, inputSchema, maxCredits, name}` uses the Coworker key and is billed to the task owner. There is no CLI command for it, so we call the endpoint directly.
- **Masumi agent contract (V, MIP-003).**
  - Endpoints: `POST /start_job`, `GET /status`, `GET /availability`, `GET /input_schema`, `POST /provide_input`.
  - Hashing follows MIP-004.
  - Sokosumi quirks: it calls `?jobId=`, expects camelCase `inputHash`, and needs a **public HTTPS URL**.
- **Python SDK (V).** `pip install masumi` builds a FastAPI app with every MIP-003 endpoint, and a LangChain example exists. There is no real LangGraph template (the one labeled LangGraph is CrewAI), so we wrap `graph.ainvoke`.
- **Listing (V).**
  - Register on MPS (pricing in tUSDM, unit `16a55b…5553444d`, 6 decimals).
  - Submit the agent to Sokosumi.
  - `isShown` is controlled by an admin flag, so **listing needs Sokosumi approval**.
- **Paid Coworker tasks (V).** `runtime complete` does not pay the seller. Payment goes through the worker's `masumiPayment` flow, which the template's `paid-task.mjs` already implements.

### 1.3 Instagram and media constraints

- **Publishing (V).** Publish through containers (`media_type=REELS|IMAGE|CAROUSEL|STORIES`). The media must be on a **public URL**.
  - Rate limit: 100 API posts per 24 hours.
  - **Instagram has no scheduling API**, so our scheduler fires the publish call.
- **Account and login (V).** The persona account must be a Business or Creator account. Use **Instagram Login** with these scopes:
  - `instagram_business_basic`
  - `instagram_business_content_publish`
  - `instagram_business_manage_comments`
  - `instagram_business_manage_messages`
  - `instagram_business_manage_insights`
  - For an account we own, Standard Access needs **no App Review**. Serving other users' accounts needs Advanced Access, which does need review.
- **Engagement rules (V).**
  - DM replies only within 24 hours of the user's last message.
  - Automated chats must **disclose automation**.
  - The 7-day Human Agent tag is for real humans only.
  - Webhooks are available for comments and messages.
- **Insights (V).** Reels metrics: `views, reach, likes, comments, shares, saved, total_interactions, ig_reels_avg_watch_time`. `impressions` is deprecated.
- **AI labelling (V/I).** Disclose photorealistic AI media. Keep C2PA metadata, and say "AI-generated persona" in the bio and captions.
- **Media costs (V).**

| Item | Provider / model | Cost |
|---|---|---|
| Persona LoRA training | fal FLUX | about $2 per run |
| LoRA image | fal FLUX | about $0.035–0.07 |
| Reference-image edit | FLUX Kontext pro | $0.04 per image |
| Reel clip, image-to-video | Kling 2.5 Turbo (fal) | $0.35 per 5s |
| Reel clip, video with audio | Veo 3.1 Lite | $0.05–0.08 per second |
| Voiceover | ElevenLabs | $0.04–0.08 per 1K characters |
| Talking head | HeyGen / Hedra | about $0.05–0.15 per second |

  - A 15-second reel costs about **$0.75–$6**.
- **LangGraph (V).**
  - `langgraph-supervisor` was **archived on Sep 20 2026**, so we build the supervisor as tool calls with handoffs.
  - Human-in-the-loop uses `interrupt()` and `Command(resume=…)`, which needs a durable **Postgres checkpointer**.
  - Python is ahead of JS, so we use **Python**.

---

## 2. Architecture

```
 Sokosumi (preprod)                         Our services (local first, then Railway)
 ─────────────────                          ─────────────────────────────────────────
 Coworker "Crest"  ── 4 offer cards ──┐
   Create / Schedule / Engage / Analyze │   ┌──────────────────────────────────────┐
                                        ▼   │ worker (Node, from template)         │
 Task READY ───────────── poll ───────────► │  runtime start / complete            │
                                            │  masumiPayment (paid-task.mjs)       │
                                            └───────────────┬──────────────────────┘
                                                            │ HTTP (local token)
                                            ┌───────────────▼──────────────────────┐
                                            │ crest-graph (Python, FastAPI)        │
                                            │  LangGraph supervisor ("Crest")      │
                                            │   ├─ persona_agent   (Create)        │
                                            │   ├─ content_agent   (Create)        │
                                            │   ├─ media_agent     (Create; async) │
                                            │   ├─ scheduler_agent (Schedule)      │
                                            │   ├─ engage_agent    (Engage, HITL)  │
                                            │   └─ analyst_agent   (Analyze)       │
                                            │  Postgres checkpointer               │
                                            └──┬──────────┬─────────┬──────────────┘
                                               │          │         │
     Masumi agents (MIP-003, same code) ◄──────┘          │         │
     /create /schedule /engage /analyze                   │         │
     registered on MPS, listed on Sokosumi            fal / Kling  Instagram Graph API
                                                      ElevenLabs   (publish, comments,
     Supabase project A: app data + checkpoints,      OpenRouter    DMs, insights,
       Storage bucket (public media URLs)             (DeepSeek)    webhooks)
     DB B (dedicated): MPS payment node
     scheduler: APScheduler job table in DB A
```

### Key decisions

1. **The Node worker stays.** The template's worker, payment and settlement code already passes its tests and matches the guide. Its `answer()` call to eve is swapped for an HTTP call to `crest-graph`. This replaces eve with LangGraph, as requested.
2. **One graph, two front doors.**
   - The Sokosumi Coworker uses the full supervisor graph. Each offer card sets a `stage` field in the Task prompt.
   - The same four stage subgraphs are exposed as MIP-003 Masumi agents using `pip masumi`, one FastAPI router per stage. Each stage gets its own MPS registration.
   - The Coworker can call its own subgraphs in-process (cheap) or hire any Masumi agent through `POST /v1/tasks/{id}/jobs`. That second path shows Masumi agents being used inside Sokosumi.
3. **The model** is OpenRouter `deepseek/deepseek-v4.1-flash` for planning and text work. Media goes to fal, Kling and ElevenLabs, called as tools.
4. **Human approval** (LangGraph interrupt) comes before anything public: the first publish of a persona, every comment or DM reply, and any spend over budget.
   - The Sokosumi Task moves to `INPUT_REQUIRED`, the human answers with `tasks comment`, and the graph resumes.
   - This mirrors Postcrest's one-tap approval.
5. **Storage.** Results are Markdown or JSON (≤1 MiB) with links to media in a Supabase Storage public bucket. Instagram can fetch those same URLs.
6. **Databases.**
   - Supabase project A holds app tables, the LangGraph checkpointer and the schedule.
   - A **separate** database B holds MPS (the guide requires a dedicated MPS database). This can be a second Supabase project or Docker Postgres.

### Agent roster (LangGraph nodes)

| Agent | Tools | Output |
|---|---|---|
| supervisor | handoff tools to each agent, `budget_check` | routes by `stage`, merges the result |
| persona_agent | `fal.train_lora`, `fal.kontext_ref`, `store.save_persona` | persona card (name, niche, voice, style, LoRA id, reference images) |
| content_agent | LLM only, plus `persona.get` | content pillars, a 7- or 30-day idea list, hooks, scripts, captions, hashtags |
| media_agent | `fal.flux_lora_image`, `fal.kling_i2v`, `elevenlabs.tts`, `ffmpeg.mux_captions`, `storage.upload` | public image and reel URLs (async jobs, polled) |
| scheduler_agent | `ig.best_times`, `schedule.add/list/cancel`, `ig.publish_container` | calendar entries, publish receipts |
| engage_agent | `ig.list_comments`, `ig.list_dms`, `ig.reply_comment`, `ig.send_dm` (gated by interrupt) | draft replies, then sent replies after approval; escalation list |
| analyst_agent | `ig.media_insights`, `ig.account_insights`, `store.history` | KPI report, top posts, hook scores, next-week plan |

---

## 3. The four ready-to-run tasks (`offers.json`)

| # | title | category | deliverable | output | input the prompt asks for |
|---|---|---|---|---|---|
| 1 | **Create: Launch an AI Influencer** | Create | Persona card, 3 on-brand photos, one 8-second reel and a 7-day post plan | doc + image | niche, audience, persona look/vibe (or reference image URLs), voice, platform |
| 2 | **Script: Trend-based Reels & TikToks** | Script | Trend swarm (3 agents) then 3 production-ready scripts tied to cited trends: hook, timestamped beats, on-screen text, VO, shot list, sound reference, caption, hashtags, CTA, TikTok vs Reels variants | doc | niche, audience, platform, number of scripts, length, tone |
| 3 | **Trends: What's Hot on TikTok & Reels** | Trends | Parallel research swarm (LangGraph `Send` fan-out, default 5 lenses) ranks current trends; every claim links to a URL returned by web search | doc | niche, region, time window |
| 4 | **Analyze: Performance & Next Content** | Analyze | KPI report, top-3 and bottom-3 posts with reasons, hook scores, next week's plan | pdf | persona id, period, goal metric |

Sokosumi cannot link to Instagram/TikTok accounts, so the Schedule (`[stage:schedule]`) and Engage (`[stage:engage]`) stages stay in the graph but have no card.

Each `prompt` field is a template the user completes when starting the card. The worker parses the stage tag (`[stage:create]`, and so on) to route the work.

---

## 4. Implementation phases and checkpoints

Times assume the hackathon's 36-hour window. Every phase ends with a verified checkpoint written to `docs/setup-state.md`.

### Phase 0: Accounts and records (≈1h, mostly human steps)
1. ✅ CLI login as **owner account** (user id `01a10f4d-c64d-7079-97e6-d85d058ad45c`, platformRole `user`).
2. ✅ Organization: TOKEN2049 `01a109d1-32a9-71a3-a0e3-658b2a7987cd` (role `member`), which meets the Vendor prerequisite.
3. ✅ **Reuse** Vendor **CardanoFish** `01a1156a-7184-77bb-a15f-f712b72381be` (slug `cardanofish-johnny`, role `admin`). No new Vendor is needed.
4. **Reuse** Coworker **PersonaLab** `01a1156a-dbc8-7360-813b-043c0e148296` (slug `cardanofish-market-researcher`, capability `tasks`, not shown, not whitelisted). It plays the role called "Crest" in this plan. Next: `coworkers connect … --personal` to check or request personal access, then save the runtime key with the guide's script.
5. Checkpoint: Vendor ID, Coworker ID, `GRANTED` personal access, key imported.

### Phase 1: Execution path with no payment (≈3h)
1. Write `crest-graph/` in Python 3.12 with langgraph, langchain-openai (pointed at OpenRouter), fastapi and psycopg. Start with the supervisor plus content_agent only.
2. Add a `POST /run {stage, input, task_id}` endpoint, protected by a local bearer token.
3. Change `client.mjs` `answer()` to call `crest-graph`. Keep the journal and deadline logic.
4. Model smoke test: one real DeepSeek call through OpenRouter.
5. Upload `offers.json` with `coworkers update --metadata-file`, then check that the four cards appear in Sokosumi Web.
6. Rehearsal Task (Create card, text-only output) → `runtime start` → result → `runtime complete`.
7. Checkpoint: Task ID, `COMPLETED`, event ID. **This proves execution only.**

### Phase 2: Create stage media (≈5h)
1. Set up Supabase project A: tables `personas, posts, media, schedules, inbox_items, insights, runs`; a public Storage bucket; the LangGraph checkpointer (`.setup()`).
2. Add persona_agent. It uses FLUX Kontext with reference images (fast path); a LoRA training run (about $2) is optional.
3. Add media_agent: 3 images, one Kling image-to-video clip, ElevenLabs voiceover, ffmpeg captions, then upload. Run media as async jobs with saved progress so a worker restart doesn't pay for the same generation twice.
4. Add a budget guard: refuse any task estimated above `MAX_USD_PER_TASK` (default $3).
5. Checkpoint: the Create card returns working public media URLs, and the cost is logged.

### Phase 3: Instagram connection (≈4h, human steps: Meta app and account)
1. Human steps:
   - Create the Meta developer app.
   - Turn the persona's Instagram account into a Business or Creator account.
   - Run Instagram Login with the five scopes.
   - Store the long-lived token in Supabase Vault or `.env.local`, never in Task output.
2. Write the `ig.*` tools: the container publish flow (create → poll `status_code` → `media_publish`), a `content_publishing_limit` check, comments, DMs and insights.
3. Add the scheduler: an APScheduler job store in database A. Each job publishes at its due time, and the publish is saved before it is sent, so a container is never published twice.
4. Add a webhook endpoint for comments and messages (on Railway, with the URL verified). Until it's deployed, poll instead.
5. Checkpoint: one real Reel published to the test account, with its media ID recorded.

### Phase 4: Engage and Analyze (≈4h)
1. engage_agent:
   - Rank the inbox, draft replies, then `interrupt()`. The Task goes to `INPUT_REQUIRED`, and the human approves through a comment. Approved replies are sent.
   - Add the disclosure line at the start of each DM thread.
   - Respect the 24-hour window.
2. analyst_agent:
   - Pull insights, rank posts, score hooks against retention and watch time, and write next week's plan.
   - Store the plan so Create can use it. This closes the Create → Analyze loop.
3. Checkpoint: one Engage Task and one Analyze Task completed against real account data.

### Phase 5: Masumi agents and payment (≈6h, human steps: Blockfrost key, wallet funding)
1. Mount 4 `masumi` FastAPI routers (`/create`, `/schedule`, `/engage`, `/analyze`) on `crest-graph`. Each gets an `input_schema` (MIP-003 format) that matches its offer.
2. MPS setup (guide step 4):
   - Use dedicated database B: migrate, then seed with output silenced.
   - Get the Blockfrost Preprod key from the human.
   - Fund the selling wallet with test ADA.
3. Register 4 agents on MPS (Dynamic pricing in the Coworker flow; 1 tUSDM default quote), then submit to Sokosumi listing. **Listing needs admin approval.**
4. Run the paid Coworker Task:
   - Signed terms, then `masumiPayment`, then confirmed escrow.
   - Run the work, then submit the result hash, then complete the Task.
   - After unlock, collect.
   - Verify the seller's net receipt with an independent Blockfrost lookup.
5. Show agent use inside Sokosumi: in a Create Task, the Coworker calls `POST /v1/tasks/{id}/jobs` to hire the listed **Analyze** Masumi agent (or another listed agent) and records the job ID.
6. Checkpoint: paid Task ID, payment IDs, deadlines, result hash, collection tx hash, measured receipt.

### Phase 6: Deploy, event approval, submission (≈5h)
1. Deploy to Railway: `crest-graph` (public HTTPS, required for MIP-003), the worker (always on, not serverless), and MPS. Use Supabase for databases A and B, with secrets in Railway variables. **Ask before creating any paid resource.**
2. Stop the local worker before starting the hosted one, so only one runs at a time.
3. Test with the laptop offline: run a new Task from another device, a paid run, and a restart.
4. Connect to the event: `coworkers connect … --workspace-id 01a109d1-32a9-71a3-a0e3-658b2a7987cd`, which returns `PENDING`. Send the access ID to the organizers.
5. Submission: public repository with no secrets, setup guide with an error log, a slide deck with an embedded demo, and payment proof (BuilderBase + masumi.network/token2049/submission).

---

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Wrong account owns the records (already happened once) | Check `whoami` before every create command; the CLI login opens the URL only in the owner account browser |
| Instagram approval or account limits block publishing | Use our own account with Standard Access (no review). If blocked, Schedule exports a ready-to-post bundle; we report it as not published |
| Media cost overruns | Per-task budget guard, cheap default models, cost logged per run |
| Video generation latency (1–5 min) passes Task deadlines | Async jobs, deadline checked before each paid step, fall back to an image carousel |
| Duplicate publish or duplicate payment after a crash | Save state before every outside write, check container or payment state before retrying, one worker lock |
| Masumi listing not approved in time | Coworker cards work without listing; hire an already-listed agent to show the `/tasks/{id}/jobs` path |
| Policy: deceptive AI personas or impersonation | Original personas only, no real person's likeness without consent, AI disclosure in bio, captions and DMs, human approval before engagement |
| Windows-only issues (CLI `.cmd` shim, OAuth `&`) | Fixed with `sokosumi-cli.mjs` and the login preload; reported upstream |
| Secrets leak into Task output, logs or repo | Server-side env only, a redaction check on results, a secret scan before publishing |

## 6. Human actions needed (in order)
1. Finish the CLI login as owner account (link already open).
2. Put `MODEL_API_KEY` (OpenRouter) in `.env.local`.
3. Create Supabase project A and database B (or start Docker for B). Put their connection strings in private env files.
4. fal.ai and ElevenLabs API keys, in `.env.local`.
5. Meta developer app plus Instagram Business account and Login (Phase 3).
6. Blockfrost Preprod key in MPS `.env`; fund the selling wallet with test ADA from dispenser.masumi.network (Phase 5).
7. Add Personal Workspace credits with Stripe test card `4242…` (before the paid Task).
8. Approve Railway resources (Phase 6).

## 7. Definition of done
- [ ] 4 offer cards visible on Coworker "Crest"; each one completes a real Task
- [ ] One real Reel published by the Schedule stage
- [ ] Engage replies sent only after human approval, with disclosure
- [ ] Analyze plan feeds the next Create run
- [ ] 4 Masumi agents registered (`RegistrationConfirmed`); at least one hired from a Coworker Task
- [ ] Paid Task with confirmed seller collection tx and measured net receipt
- [ ] Hosted deployment passes the laptop-offline test; event access requested
