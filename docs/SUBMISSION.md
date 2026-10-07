# PersonaLab: TOKEN2049 Origins submission checklist

Sources:
- https://www.masumi.network/token2049/submission (fetched 2026-10-07)
- BuilderBase: https://builderbase.com/event/token2049-origins-hackathon#rules (deadline and official rules)

The fetched BuilderBase page listed no deadline or form fields, so check them there by hand.

How to read this file:
- `[x]` = done and verified.
- `[ ]` = open.
- `TODO:` = a value not known yet. Never fill a TODO with a guessed ID or hash.

## Key conditions (from the submission page)
- [ ] Built during the official 36-hour hacking period only. Existing libraries and frameworks are allowed.
- [ ] Submitted to the main track and to every partner track that applies. `TODO: list tracks`
- [ ] Slides are **locked at the deadline**. `TODO: deadline from BuilderBase`
- [ ] Payment collection verified on Cardano Preprod. If it is still pending, the submission says so.

## 1. Code repository
- [ ] Public repository, or judges given access. `TODO: repo URL`
- [x] Run instructions: `README.md` and `docs/SETUP-GUIDE.md`, including the error history
- [ ] No keys or secrets in the repo:
  - [x] `.env*` and `.local/` are git-ignored
  - [ ] Secret scan run before publishing. `TODO: run gitleaks/trufflehog on full history`
- [ ] Template leftovers renamed. The registration body in `payment-registration.mjs` and the input schema in `agent-api.mjs` still describe the template's "Team Name Finder".

## 2. Agent demo
- [ ] Demo shows the input, the agent running, and the real result (recorded, then embedded in the slides)
- [ ] Deployed agent URL. `TODO: hosted URL` (it currently runs locally on the operator host)
- [x] Coworker ID: `01a1156a-dbc8-7360-813b-043c0e148296` (PersonaLab, Vendor CardanoFish `01a1156a-7184-77bb-a15f-f712b72381be`)
- [x] Sample Task: rehearsal `01a115be-d0ca-77d5-bf90-b98aa4487fec`
- [ ] Availability statement. `TODO: e.g. "Available on Sokosumi Preprod from <date>; worker hosted at <host> until <date>"`
- [ ] Checked against the reference deployment checklist on the submission page

## 3. Completed Task evidence

| Item | Rehearsal (unpaid) | Paid Task |
|---|---|---|
| Sokosumi Task ID | `01a115be-d0ca-77d5-bf90-b98aa4487fec` | `TODO: paid Task ID` |
| Card | Engage: Reply to Comments & DMs | `TODO` |
| Status | `COMPLETED` | `TODO` |
| Completion event ID | `01a115bf-b375-7779-9ebf-e3cb43b24c7c` | `TODO` |
| Payment event IDs | n/a (unpaid) | `TODO: payment event IDs` |
| Result | `TODO: link or excerpt of the delivered Engage result` | `TODO` |

- [x] Coworker access to the event Workspace (TOKEN2049 `01a109d1-32a9-71a3-a0e3-658b2a7987cd`) is `GRANTED`, access ID `01a11580-fdb2-7259-86af-18c58e2ae61e`
- [x] Coworker access to the personal Workspace is `GRANTED`, access ID `01a1156a-e7c6-722c-bf42-143aa4a3b154`
- [x] Real model smoke test (Create): all 4 sections in 28 s

## 4. Seller payment proof (Cardano Preprod)

| Field | Value |
|---|---|
| MPS | Masumi Payment Service at revision `99d94cf31cad168a74281494e79d5cc56f34838d`, local `127.0.0.1:38127`, dedicated Postgres 16 |
| Agent identifier | `TODO: agentIdentifier (RegistrationConfirmed)` |
| Registration tx hash | `TODO` |
| Payment `blockchainIdentifier` | `TODO` |
| Purchaser nonce (`identifierFromPurchaser`) | `TODO` |
| Input hash / result hash | `TODO` / `TODO` |
| Signed deadlines | `payByTime` `TODO` · `submitResultTime` `TODO` · `unlockTime` `TODO` · `externalDisputeUnlockTime` `TODO` |
| Lock/escrow tx hash | `TODO` |
| Seller collection tx hash | `TODO: collection tx hash` |
| Explorer link | `https://preprod.cardanoscan.io/transaction/TODO` |
| Seller wallet address | `TODO: seller address` |
| Token unit (test USDM) | `16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d` (6 decimals) |
| Quoted amount | 1 tUSDM = `1000000` atomic units (enforced in `paid-task.mjs`) |
| Net received by seller | `TODO: netAtomicUnits from settlement.mjs` (Blockfrost UTxO inputs minus outputs at the seller address) |
| Core receipt | `TODO: sokosumi runtime receipt <paid Task ID>` → `settled: true`, `txHash` |

- [ ] At least one confirmed Preprod transaction hash, with an explorer link
- [ ] Collection confirmed (`Withdrawn`). If not, report it as pending.

## 5. Presentation slides
- [ ] Google Drive link to a **.ppt/.pptx or .keynote** file. `TODO: Drive link`
- [ ] Demo recording **embedded** in the file. External video links and live demos do not count.
- [ ] Sharing set so judges can view
- Outline: `docs/SLIDES-OUTLINE.md`

## 6. BuilderBase form
- [ ] Project name: PersonaLab
- [ ] One-line description: "A Sokosumi Coworker that launches and runs an original AI influencer: Create, Schedule, Engage, Analyze, paid through Masumi on Cardano."
- [ ] Repo link, Drive slides link, Coworker ID, Task IDs, tx hash (copy them from the sections above)
- [ ] Team members. `TODO`
- [ ] Submitted before the deadline. `TODO: confirmation`
