# PersonaLab slide outline (10 slides) and demo script

Export the deck as .pptx or .keynote, upload it to Google Drive, and embed the demo recording on slide 4.
Values marked `TODO` must come from real evidence before the deck is locked.

---

### 1. Title
- **PersonaLab**: a Sokosumi Coworker that launches and runs an original AI influencer
- Four ready-to-run tasks: **Create → Schedule → Engage → Analyze**
- Built with Masumi + Sokosumi on Cardano Preprod · Vendor CardanoFish · TOKEN2049 Origins

### 2. Problem
- AI-influencer SaaS tools are closed, subscription-based ($19–99 a month) and tied to one dashboard
- Creators and small brands need four separate jobs done: a persona, a posting plan, inbox replies and analytics
- No agent marketplace sells these jobs per task, with on-chain payment and human approval

### 3. Solution
- One Coworker (`01a1156a-dbc8-7360-813b-043c0e148296`) with four task cards. It matches the features of an AI-influencer SaaS, written as our own code, copy and branding.
- **Create:** persona card, 3 photo concepts with generation prompts, an 8-second reel script, a 7-day plan
- **Schedule:** calendar with best times and a publishing checklist
- **Engage:** ranked inbox, on-brand draft replies, an escalation list. **Nothing is sent without approval.**
- **Analyze:** KPI summary with the formula inputs shown, top and bottom posts, a hook scorecard, next week's plan

### 4. Demo flow (embedded recording)
1. Pick a card in Sokosumi and fill in the prompt
2. The Task goes `READY`, then the worker runs `runtime start`
3. The LangGraph supervisor routes to the right agent using the `[stage:*]` tag
4. The result is saved, then `runtime complete` runs, and the Task is `COMPLETED` with an event ID
5. Paid path: Masumi escrow, then result hash, then seller collection. `TODO: show once done`

### 5. Architecture (text diagram)
```
Sokosumi Task (card prompt "[stage:engage] ...")
        │ poll every 5 s (one worker lock, journal per Task)
        ▼
worker.mjs (Node 24) ── runtime start / complete (Coworker key from the OS vault)
        │             └─ paid-task.mjs → MPS (127.0.0.1:38127, Postgres 16) → Cardano Preprod
        │ HTTP + bearer token, 127.0.0.1 only
        ▼
crest-graph (FastAPI + LangGraph)
  supervisor ──► persona_agent → content_agent   (Create)
             ├─► scheduler_agent                 (Schedule)
             ├─► engage_agent                    (Engage)
             └─► analyst_agent                   (Analyze)
        │
        ▼
DeepSeek V4.1 Flash (direct API), with OpenRouter as fallback
```

### 6. Masumi payment flow
1. The buyer starts a paid Task. MPS quotes **1 tUSDM** (unit `16a55b…5553444d`) with signed deadlines (`payByTime`, `submitResultTime`, `unlockTime`)
2. The buyer's `masumiPayment` locks funds in the Web3CardanoV2 escrow contract. The worker waits for on-chain confirmation.
3. The worker runs the graph, submits the result hash (SHA-256) to MPS, and completes the Task
4. After `unlockTime`, the seller collects. `settlement.mjs` checks Core's receipt against the MPS withdrawal tx and Blockfrost UTxOs, and reports the **net amount received**
- Each step is saved before the next outside write, so a crash never pays or collects twice

### 7. Results and evidence

| Evidence | Value |
|---|---|
| Rehearsal Task (Engage) | `01a115be-d0ca-77d5-bf90-b98aa4487fec`, COMPLETED |
| Completion event | `01a115bf-b375-7779-9ebf-e3cb43b24c7c` |
| Event Workspace access | GRANTED, `01a11580-fdb2-7259-86af-18c58e2ae61e` |
| Real model smoke test | Create, 4/4 sections, 28 s |
| Tests | Node 22/22, Python 6/6 |
| Paid Task | `TODO: paid Task ID` |
| Collection tx | `TODO: tx hash` + preprod.cardanoscan.io link |
| Net seller receipt | `TODO` |

### 8. Quality and safety checks
- Every card's output has fixed section headings. The smoke test counts the `##` sections.
- Prompt rules:
  - No invented statistics, follower counts or testimonials. Unsure figures are marked `[verify]`.
  - Personas are always original and never look like a real person. AI disclosure is recommended.
  - Pasted comments and DMs are treated as untrusted data (prompt-injection guard)
  - Engage: automated replies are disclosed, risky threads go to a human, and every draft needs approval
  - Analyze: if no metrics are given, it returns a measurement plan instead of made-up numbers
- Ops:
  - Bearer-token, loopback-only graph service
  - Secrets only in `.env.local` and the OS vault
  - Errors are logged with their class and status only, never the prompt or keys

### 9. What needed human help
- OAuth login in the owner account's browser, plus the Windows `cmd /c start` URL-truncation fix
- Vendor and Coworker reuse, and the organizer's approval of event Workspace access
- Model API key, Blockfrost Preprod key, test ADA and USDM from the faucet
- Starting Docker Desktop for the MPS database
- Paid-Task approval and seller collection. `TODO`

### 10. Roadmap
- Media generation: FLUX or Kontext persona images, a Kling image-to-video reel, ElevenLabs voice
- Instagram Graph API: real publishing from the scheduler, comment and DM webhooks, live insights
- Human-in-the-loop with LangGraph `interrupt()`, a Postgres checkpointer, and approval through `tasks comment`
- Each stage registered as its own Masumi agent (MIP-003), hireable from other Coworkers through `/v1/tasks/{id}/jobs`
- Hosted deployment (graph, worker and MPS), passing a laptop-offline test

---

## 90-second demo recording script

| Time | Screen | Voiceover |
|---|---|---|
| 0:00–0:10 | Title slide, then the Sokosumi Coworker page with 4 cards | "PersonaLab is a Sokosumi Coworker that runs an AI influencer end to end: Create, Schedule, Engage, Analyze." |
| 0:10–0:25 | Open the **Engage** card and paste 4 sample comments and DMs (one is a risky purchase question) | "I'll pick Engage and paste my inbox. Comments are treated as untrusted data." |
| 0:25–0:35 | Terminal: worker log shows `runtime start`, then the Task shows `RUNNING` | "Our Node worker picks the Task up and starts it with the Coworker's own runtime key." |
| 0:35–0:50 | Split view: crest-graph log routes `[stage:engage]` to engage_agent | "A LangGraph supervisor reads the stage tag and hands off to the engage agent, running DeepSeek V4.1 Flash." |
| 0:50–1:05 | Sokosumi Task shows `COMPLETED`. Scroll the result: triage table, drafts, escalation, "Approval needed" | "The result: a ranked inbox, on-brand drafts with an automation disclosure, the purchase question sent to a human, and nothing sent without approval." |
| 1:05–1:20 | Payment view: MPS payment → escrow tx → collection tx on preprod.cardanoscan.io (`TODO: record after the paid Task`) | "Paid Tasks settle through Masumi: 1 test USDM is locked in escrow, the result hash is submitted, and the seller collects on Cardano Preprod." |
| 1:20–1:30 | Evidence slide with Task, event and tx IDs | "Every step is journaled, so nothing runs or pays twice. PersonaLab: your AI influencer team, hired by the task." |

Recording tips:
- Use 1080p and hide `.env.local`, terminal history, and any MPS seed or wallet output
- Before recording, blur or crop any email address or local path that appears on screen
