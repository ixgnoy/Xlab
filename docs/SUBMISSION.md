# PersonaLab: TOKEN2049 Origins submission checklist

Sources:
- https://www.masumi.network/token2049/submission (fetched 2026-10-07)
- BuilderBase: https://builderbase.com/event/token2049-origins-hackathon#rules (deadline and official rules)

The fetched BuilderBase page listed no deadline or form fields, so check them there by hand.

How to read this file:
- `[x]` = done and verified.
- `[ ]` = open.
- `TODO:` = a value not known yet. Never fill a TODO with a guessed ID or hash.

Machine-readable evidence: [`paid-proof.json`](paid-proof.json) (paid Task and settlement), [`masumi-api-smoke.json`](masumi-api-smoke.json) (MIP-003 agent API smoke test), [`registration-state.json`](registration-state.json) (Masumi registry), [`payment-state.json`](payment-state.json) (MPS payment source and wallets, no secrets).

## Key conditions (from the submission page)
- [ ] Built during the official 36-hour hacking period only. Existing libraries and frameworks are allowed.
- [ ] Submitted to the main track and to every partner track that applies. `TODO: list tracks`
- [ ] Slides are **locked at the deadline**. `TODO: deadline from BuilderBase`
- [x] Payment collection verified on Cardano Preprod: collection tx `ec5b8dad…3bc3` confirmed, on-chain state `Withdrawn`, seller net receipt 1 tUSDM (section 4).

## 1. Code repository
- [ ] Repository access for judges. Repo: `https://github.com/ixgnoy/personalab-coworker` (private; judges need access). `TODO: confirm judges were added`
- [x] Run instructions: `README.md` and `docs/SETUP-GUIDE.md`, including the error history
- [ ] No keys or secrets in the repo:
  - [x] `.env*` and `.local/` are git-ignored
  - [ ] Secret scan run before publishing. `TODO: run gitleaks/trufflehog on full history`
- [x] Template leftovers renamed. The registry entry is `PersonaLab` (Capability `personalab-langgraph` v1) and no "Team Name Finder" text remains in the `.mjs` files.

## 2. Agent demo
- [ ] Demo shows the input, the agent running, and the real result (recorded, then embedded in the slides). `TODO: demo video`
- [ ] Deployed agent URL. `TODO: hosted URL`. There is no hosted deployment: the LangGraph service, Node worker, agent API and MPS run locally on the operator machine (loopback only).
- [x] Coworker ID: `01a1156a-dbc8-7360-813b-043c0e148296` (PersonaLab, Vendor CardanoFish `01a1156a-7184-77bb-a15f-f712b72381be`)
- [x] Ready-to-run cards (final 4, from `coworker/offers.json`):
  1. **Onboarding: Build Your Virtual Avatar** (`[stage:onboarding]`): a real creator's interests, values, story, expertise and moat become a personal avatar profile plus a reusable Avatar JSON.
  2. **Create: AI Influencer Reel & Video Ad** (`[stage:create]`): trend swarm → persona → scene script citing the trend URL → persona-consistent keyframes (Gemini 3.1 Flash Lite Image) → AI image-to-video clips (xAI Grok Imagine Video 1.5 Lite) + voiceover → 9:16 MP4. Falls back to local ffmpeg assembly.
  3. **Script: Trend-based Reels & TikToks** (`[stage:scripts]`)
  4. **Trends: What's Hot on TikTok & Reels** (`[stage:trends]`): LangGraph `Send` fan-out swarm, cited evidence only, URL and number validation.
- Schedule, Engage and Analyze stay in the code (Instagram API in dry-run) but are not offered as cards, because Sokosumi cannot link Instagram or TikTok accounts.
- [x] Sample Tasks: see section 3.
- [ ] Availability statement. `TODO: e.g. "Available on Sokosumi Preprod from <date>; worker runs on the operator machine during judging"`
- [ ] Checked against the reference deployment checklist on the submission page

## 3. Completed Task evidence

| Task ID | Workspace | Card / stage | Paid | Status | Events / notes |
|---|---|---|---|---|---|
| `01a115be-d0ca-77d5-bf90-b98aa4487fec` | personal | Engage (rehearsal) | no | `COMPLETED` | completion event `01a115bf-b375-7779-9ebf-e3cb43b24c7c` |
| `01a115c6-b98d-75bd-b5b0-7ab2f85d4ab4` | event (TOKEN2049) | Schedule | no | `COMPLETED` | |
| `01a115f9-4653-7647-8b15-c5a3e10f5b30` | event (TOKEN2049) | Trends | no | `COMPLETED` | 8 trends, 7 cited URLs |
| `01a115db-7a10-7148-8526-d516924c360c` | `TODO: workspace` | `TODO: card` | **yes, 1 tUSDM** | `COMPLETED` | payment-request event `01a115e7-15dd-7728-a4be-d961a3c56f6a`, completion event `01a115f7-b0e0-7069-92ae-4223d6aeb607` |

- [x] Coworker access to the event Workspace (TOKEN2049 `01a109d1-32a9-71a3-a0e3-658b2a7987cd`) is `GRANTED`, access ID `01a11580-fdb2-7259-86af-18c58e2ae61e`
- [x] Coworker access to the personal Workspace is `GRANTED`, access ID `01a1156a-e7c6-722c-bf42-143aa4a3b154`
- [x] Real model smoke test (Create): all sections in 28 s
- [x] MIP-003 agent API smoke test (`masumi-api-smoke.json`): `/availability`, `/input_schema`, `/start_job`, `/status` all 200; MIP-004 input hash matches an independent recomputation; deadlines ordered; job `awaiting_payment`. Seller side only, no buyer funds.

## 4. Seller payment proof (Cardano Preprod)

| Field | Value |
|---|---|
| MPS | Masumi Payment Service at revision `99d94cf31cad168a74281494e79d5cc56f34838d`, local `127.0.0.1:38127`, dedicated Postgres 16 |
| Payment source | `Web3CardanoV2`, Preprod, contract `addr_test1wzs4e6wc95hkwezlccjw9mdvq0r0rsgx6zk34avptga3ftgn37w4g` |
| Agent identifier | `67ab0c92c4ac1610895a1c965ee50aba41a8f1513b15240723b3bd0b10648ac99be37c280788d2c1a9270b4960d342b1d4fb4a830b5beba022000000` (`RegistrationConfirmed`, registry ID `cmuxy6tgw0004z47kivbwxd9w`) |
| Registration tx hash | [`ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1`](https://preprod.cardanoscan.io/transaction/ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1) (block 5264016) |
| Payment `blockchainIdentifier` | prefix `318260ac026604601c02c10230139e4e…` (full value in MPS) |
| Purchaser nonce (`identifierFromPurchaser`) | `TODO` (not recorded in `paid-proof.json`) |
| Input hash / result hash | `fb9aa2fae5be1138b2b67fcfb32adea411a155bd3aed0caba11c84d64150f414` / `7ab2aed29451f9de720cd141be0e0262e74cc2a7fa17bc508ffbefea223a0954` |
| Signed deadlines | `payByTime` `2026-10-07T10:41:58.810Z` · `submitResultTime` `2026-10-07T11:06:58.810Z` · `unlockTime` `2026-10-07T11:22:58.810Z` · `externalDisputeUnlockTime` `2026-10-07T11:38:58.810Z` |
| Lock/escrow tx (`FundsLocked`) | [`ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c`](https://preprod.cardanoscan.io/transaction/ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c) |
| Result tx (`ResultSubmitted`) | [`02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7`](https://preprod.cardanoscan.io/transaction/02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7) |
| Seller collection tx (`Withdrawn`) | [`ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3`](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3) (block 5264251, 2026-10-07T11:33:31Z) |
| Seller wallet address | `addr_test1qqz6wglg8mvv7f0hrplymhw57z0d5u2jjxt9wt4u4hfvaxsfun3y53q6xrjtzwfwnzgl2urpxtx449wh3nw28crrrdrssejnde` |
| Seller wallet funding txs | [`a70a7918…181d3a`](https://preprod.cardanoscan.io/transaction/a70a791880b55cae34a0cdf6756f0c5f37ba8325dad5ce63acc184f5da181d3a), [`9ae55b9f…885cd0`](https://preprod.cardanoscan.io/transaction/9ae55b9f842a32c69c49a3774f0b61ae02c9d029ebe6f39ca2eb1cef0b885cd0) |
| Token unit (test USDM) | `16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d` (6 decimals) |
| Quoted amount | 1 tUSDM = `1000000` atomic units (enforced in `paid-task.mjs`) |
| Net received by seller | **1 tUSDM** (`1000000` atomic): Blockfrost tx UTxOs, seller tUSDM outputs minus seller tUSDM inputs |
| Core receipt | `sokosumi runtime receipt 01a115db-7a10-7148-8526-d516924c360c` → `settled: true`, `txHash` `ec5b8dad…3bc3` |

- [x] At least one confirmed Preprod transaction hash, with an explorer link (escrow, result and collection all `Confirmed`)
- [x] Collection confirmed (`Withdrawn`)
- Note: the first payment terms on this Task (payBy +5 min) expired with no escrow lock. Fresh terms with payBy +15 min on the same Task succeeded. See `docs/SETUP-GUIDE.md`, Problems and fixes.

## 5. Presentation slides
- [x] Deck built: `docs/deck/PersonaLab.pptx` (generated by `docs/deck/build_deck.py`)
- [ ] Google Drive link to the **.pptx** file. `TODO: Drive link`
- [ ] Demo recording **embedded** in the file. External video links and live demos do not count. `TODO: demo video`
- [ ] Sharing set so judges can view
- Outline: `docs/SLIDES-OUTLINE.md`

## 6. BuilderBase form
- [ ] Project name: PersonaLab
- [ ] One-line description: "A Sokosumi Coworker that builds a creator's virtual avatar and turns live, cited TikTok/Reels trends into scripts and 9:16 AI video reels, paid per task through Masumi on Cardano."
- [ ] Repo link, Drive slides link, Coworker ID, Task IDs, tx hash (copy them from the sections above)
- [ ] Team members. `TODO: team names`
- [ ] Submitted before the deadline. `TODO: confirmation`

## Live card runs on Sokosumi (final 4 cards, TOKEN2049 workspace, verified 2026-10-07)

| Card | Task ID | Status | Result highlights |
|---|---|---|---|
| Onboarding: Build Your Virtual Avatar | `01a11630-ecb4-771d-ac62-552db90ef0c1` | COMPLETED | All 7 sections + machine-readable Avatar JSON |
| Create: AI Influencer Reel & Video Ad | `01a1162d-13b0-77c8-80ff-ad5d7bc36ec9` | COMPLETED | 20.1 s 9:16 AI video ad (4 image-to-video clips + voiceover), based on a cited trend; cost ~$0.72; copy in `docs/demo/create-reel-home-coffee.mp4` (sha256 `31fed431…f3a5`) |
| Script: Trend-based Reels & TikToks | `01a11630-f714-7588-87d2-79c1f009f5ac` | COMPLETED | 3 scripts tied to cited trends + evidence log |
| Trends: What's Hot on TikTok & Reels | `01a115f9-4653-7647-8b15-c5a3e10f5b30` | COMPLETED | 8 ranked trends, 7 cited URLs |
| Paid Task (Masumi payment) | `01a115db-7a10-7148-8526-d516924c360c` | COMPLETED + collected | See `docs/paid-proof.json` |
