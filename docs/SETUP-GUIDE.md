# PersonaLab setup guide

This guide rebuilds PersonaLab from a clean machine: the Sokosumi Coworker, the LangGraph service, the Node worker and the Masumi Payment Service (MPS) on Cardano Preprod.
It was written on Windows 11 (PowerShell and Git Bash). The commands also work on macOS and Linux unless a step says it is Windows-only.

Rules for every step:
- Secrets go only in `.env.local` (git-ignored) or in the OS vault. Never put them in command arguments, Task text, logs or this repo.
- Run `auth whoami` before any write, so records are created under the right account.
- If a write's outcome is unclear, inspect the current state before you retry it.

Status labels: **VERIFIED** means it was run and checked on 2026-10-07. **IN PROGRESS** and **TODO** mean the step is not finished yet.

---

## 0. Requirements

| Tool | Version used | Check |
|---|---|---|
| Node.js | 24.15.0 (24 or newer is required) | `node -v` |
| Python + uv | Python 3.12 (`crest-graph/.python-version`), uv | `uv --version` |
| Sokosumi CLI | 1.0.4 | `sokosumi --help` (first line shows the version) |
| Docker | 28.0.4 (the daemon must be running for MPS) | `docker info` |
| pnpm | 10.30.2, used only for MPS and run through corepack | `corepack pnpm -v` |
| git | 2.47.0 | `git --version` |

## 1. Install the Sokosumi CLI (VERIFIED)

```sh
npm install -g @masumi_network/sokosumi
sokosumi --help            # prints "Sokosumi CLI v1.0.4"
```

On Windows, scripts in this repo do not call the `sokosumi.cmd` shim, because `execFileSync('sokosumi')` cannot start a `.cmd` file.
`sokosumi-cli.mjs` resolves `npm root -g`/`@masumi_network/sokosumi`, reads the `bin` entry and runs it with `node`.
If your global npm root is somewhere else, set `SOKOSUMI_CLI_ROOT`.

## 2. OAuth login (VERIFIED, with a Windows workaround)

```sh
# Environment credentials override saved OAuth, so clear them first
unset SOKOSUMI_API_KEY SOKOSUMI_AUTH_TOKEN          # PowerShell: Remove-Item Env:SOKOSUMI_API_KEY, Env:SOKOSUMI_AUTH_TOKEN
sokosumi --preprod auth login --json
sokosumi --preprod auth whoami --json               # check the account and platformRole before any write
```

Before running `auth login`, sign the browser in to the **owner** account. The CLI saves whichever account finishes the browser flow.

### Windows bug: `cmd /c start` truncates the OAuth URL

CLI 1.0.4 opens the browser through `dist/src/auth/oauth.js`:

```js
if (platform === "win32") return openWithCommand("cmd", ["/c", "start", "", target], { spawnImpl });
```

`cmd.exe` treats `&` as a command separator. The browser receives the URL only up to the first `&`, so the `state`, `redirect_uri` and PKCE parameters are lost. The CLI then waits until it fails with:

```
OAuth login timed out waiting for the browser callback
```

**Workaround: a preload script.** It reroutes that one spawn to `rundll32 url.dll,FileProtocolHandler URL`, which passes the URL through unchanged.
Keep it outside the repo, for example in `.local/open-url-preload.cjs`:

```js
// .local/open-url-preload.cjs : Windows only. Reroutes the CLI's `cmd /c start "" URL` to rundll32 so '&' is not cut.
const cp = require('node:child_process');
const { syncBuiltinESMExports } = require('node:module');
const original = cp.spawn;
cp.spawn = function (cmd, args, opts) {
  if (process.platform === 'win32' && /^cmd(\.exe)?$/i.test(cmd) && Array.isArray(args)
      && args[0] === '/c' && args[1] === 'start' && /^https?:\/\//.test(args[args.length - 1] ?? '')) {
    return original.call(this, 'rundll32', ['url.dll,FileProtocolHandler', args[args.length - 1]], opts);
  }
  return original.apply(this, arguments);
};
syncBuiltinESMExports(); // the CLI imports spawn as an ESM named binding, so this push is required
```

```powershell
$env:NODE_OPTIONS = "--require ./.local/open-url-preload.cjs"
node "$(npm root -g)/@masumi_network/sokosumi/<bin entry from package.json>" --preprod auth login --json
Remove-Item Env:NODE_OPTIONS
```

**Another option:** copy the full URL from the CLI output, or have a small wrapper print it instead of opening it, then paste it into the browser that is signed in to the owner account. The first relogin in this project worked this way.

## 3. Reuse the Vendor and Coworker (VERIFIED)

Do not create new records. Look up the existing ones and reuse them:

```sh
sokosumi --preprod vendors me --json                     # CardanoFish 01a1156a-7184-77bb-a15f-f712b72381be (admin)
sokosumi --preprod coworkers list --scope owned --json   # PersonaLab 01a1156a-dbc8-7360-813b-043c0e148296 (capability tasks)
sokosumi --preprod workspaces list --json                # TOKEN2049 org 01a109d1-32a9-71a3-a0e3-658b2a7987cd (member)
```

| Record | ID |
|---|---|
| Vendor CardanoFish | `01a1156a-7184-77bb-a15f-f712b72381be` |
| Coworker PersonaLab | `01a1156a-dbc8-7360-813b-043c0e148296` |
| Organization TOKEN2049 | `01a109d1-32a9-71a3-a0e3-658b2a7987cd` |

## 4. Connect the Coworker (VERIFIED)

Connect your personal Workspace first, for private testing:

```sh
sokosumi --preprod coworkers connect 01a1156a-dbc8-7360-813b-043c0e148296 \
  --vendor-id 01a1156a-7184-77bb-a15f-f712b72381be --personal --json
```

Result: `GRANTED`. The access ID is `01a1156a-e7c6-722c-bf42-143aa4a3b154` and the personal Workspace is `01a10f4e-05f4-7671-abe3-9b702c901915`.

Then connect the event Workspace:

```sh
sokosumi --preprod coworkers connect 01a1156a-dbc8-7360-813b-043c0e148296 \
  --vendor-id 01a1156a-7184-77bb-a15f-f712b72381be \
  --workspace-id 01a109d1-32a9-71a3-a0e3-658b2a7987cd --json
```

The first answer is `PENDING`, which means the approval request was accepted. An organizer approves it, and you run `connect` again.
Current status: `GRANTED`, access ID `01a11580-fdb2-7259-86af-18c58e2ae61e`.

Never combine `--personal` with `--workspace-id` or other organization flags.

## 5. Coworker runtime key (VERIFIED)

The runtime key is created once and shown once (JSON mode only). Send it straight into the OS vault and `.env.local`, and never print it.
The script below is equivalent to the one used in this project:

```sh
# .local/save-runtime-key.sh : creates the key, imports it into the OS vault, and appends it to .env.local without echoing it
set -euo pipefail
C=01a1156a-dbc8-7360-813b-043c0e148296
KEY=$(sokosumi --preprod coworkers api-key "$C" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);const t=j.token??j.apiKey??j.data?.token;if(!t)process.exit(2);process.stdout.write(t)})')
printf '%s\n' "$KEY" | sokosumi runtime key-import --coworker-id "$C" --api-key-stdin --json >/dev/null
grep -q '^SOKOSUMI_COWORKER_API_KEY=' .env.local 2>/dev/null || printf 'SOKOSUMI_COWORKER_API_KEY=%s\n' "$KEY" >> .env.local
chmod 600 .env.local; unset KEY
echo "runtime key imported (value not shown)"
```

`key-import` checks the Coworker's identity and its `tasks` capability before it stores the key. If the JSON field name differs in your CLI version, read the shape with `--json | node -e 'console.log(Object.keys(JSON.parse(require("fs").readFileSync(0))))'`. That prints the keys only, not the values.

## 6. Project configuration

```sh
git clone <repo-url> personalab && cd personalab
cp .env.example .env            # non-secret: MODEL_BASE_URL, MODEL_ID, ports, COWORKER_ID
# .env.local (secret, mode 600): MODEL_API_KEY, optional OPENROUTER_API_KEY, SOKOSUMI_COWORKER_API_KEY, CREST_GRAPH_TOKEN
node -e "console.log('CREST_GRAPH_TOKEN='+require('crypto').randomBytes(32).toString('hex'))" >> .env.local
```

The model is DeepSeek V4.1 Flash. The primary endpoint is the DeepSeek API, set with `MODEL_BASE_URL=https://api.deepseek.com/v1` and the `MODEL_ID` from `.env.example`.
If `OPENROUTER_API_KEY` is set, `crest_graph/model.py` adds OpenRouter `deepseek/deepseek-v4.1-flash` as a fallback (`with_fallbacks`).
Values are read in this order: real environment first, then `.env.local`, then `.env`. Node (`--env-file`) and Python (`crest_graph/config.py`) use the same order.

## 7. Upload the offer cards (VERIFIED)

```sh
sokosumi --preprod coworkers update 01a1156a-dbc8-7360-813b-043c0e148296 --metadata-file coworker/offers.json --json
```

This creates four cards. Each prompt starts with a stage tag, and the supervisor routes on that tag:
- Create (`[stage:create]`, outputs doc + image)
- Schedule (`[stage:schedule]`, sheet)
- Engage (`[stage:engage]`, doc)
- Analyze (`[stage:analyze]`, pdf)

The first attempts returned three 422 errors. See [Problems and fixes](#problems-and-fixes).

## 8. Run the graph and the worker (VERIFIED)

```sh
npm ci
(cd crest-graph && uv sync)
npm test && npm run test:graph   # Node 22/22, Python 6/6 (fake model)
npm start                        # terminal 1: crest-graph on 127.0.0.1:21951, bearer-token protected
npm run smoke                    # real model turn; prints sections, char count and seconds only
npm run worker                   # terminal 2: polls Tasks for COWORKER_ID every 5 s
```

- The smoke test returned all four Create sections (Persona card, 3 photo concepts, Reel, 7-day plan) in **28 s**.
- `GET /health` returns `{status, model_configured}`. `POST /run` without the token returns 401.
- The worker moves each Task through `starting → started → model-pending → result-saved → complete-pending → completed`. It saves each step to `.local/<taskId>.json` before the next outside call, so a restart never runs the same step twice. `worker-lock.mjs` allows only one worker at a time.

Rehearsal Task (VERIFIED, using the Engage card):

```sh
sokosumi --preprod tasks create --personal --coworker-id 01a1156a-dbc8-7360-813b-043c0e148296 \
  --name "Engage rehearsal" --description "<Engage card prompt, filled in>" --status READY --json
sokosumi --preprod tasks get   01a115be-d0ca-77d5-bf90-b98aa4487fec --json   # status COMPLETED
sokosumi --preprod tasks events 01a115be-d0ca-77d5-bf90-b98aa4487fec --json  # completion event 01a115bf-b375-7779-9ebf-e3cb43b24c7c
```

This proves the execution path only. It does not prove payment.

## 9. Masumi Payment Service on Preprod (IN PROGRESS)

MPS gets its **own** database. It never shares one with app data.

### 9.1 Postgres 16 in Docker, bound to loopback only

```sh
docker run -d --name personalab-mps-db --restart unless-stopped \
  -e POSTGRES_USER=mps -e POSTGRES_PASSWORD="<local-only password>" -e POSTGRES_DB=masumi_payment \
  -p 127.0.0.1:5433:5432 -v personalab-mps-pg:/var/lib/postgresql/data postgres:16
docker exec personalab-mps-db pg_isready -U mps        # "accepting connections"
```

Port 5433 avoids a clash with any local Postgres on 5432. The `127.0.0.1:` prefix keeps the database off the network.

### 9.2 Pinned MPS checkout

```sh
git clone https://github.com/masumi-network/masumi-payment-service.git ../masumi-payment-service
cd ../masumi-payment-service
git checkout 99d94cf31cad168a74281494e79d5cc56f34838d
corepack enable && corepack prepare pnpm@10.30.2 --activate
pnpm -v                                   # 10.30.2 (the global pnpm 10.24.0 is not used)
pnpm install --frozen-lockfile
```

### 9.3 MPS environment (`../masumi-payment-service/.env`, outside this repo)

Use the variable names from MPS's own `.env.example` at that revision. Typical values:

```
DATABASE_URL=postgresql://mps:<local-only password>@127.0.0.1:5433/masumi_payment
PORT=38127
ADMIN_KEY=<random, 32+ chars>
ENCRYPTION_KEY=<random, 32+ chars>
BLOCKFROST_API_KEY_PREPROD=<from the human>
```

### 9.4 Migrate and seed (seed output suppressed)

```sh
pnpm run prisma:migrate
pnpm run prisma:seed > /dev/null 2>&1 && echo "seed ok"     # PowerShell: pnpm run prisma:seed *> $null; if ($?) { "seed ok" }
```

The seed creates the hot wallets and can print **wallet mnemonics and keys** to stdout. Its output must never reach a terminal log, a screenshot or chat.
Read wallet IDs and addresses later through the admin API. That API returns no secrets.

### 9.5 Start and check

```sh
pnpm run build && pnpm start                    # use the start script from MPS package.json; listens on 127.0.0.1:38127
curl -s http://127.0.0.1:38127/api/v1/health
```

In this repo's `.env`: `MPS_URL=http://127.0.0.1:38127`, `MPS_PORT=38127`, `PAID_TASKS_ENABLED=false` until registration is confirmed.

### 9.6 Remaining payment steps (TODO)

1. Fund the selling wallet with test ADA from dispenser.masumi.network, and get test USDM.
   - `TODO: seller address`
   - Token unit `16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d` (6 decimals; 1 tUSDM = `1000000`)
2. Write `docs/payment-state.json` with `sourceId`, `walletId` and `sellerAddress`. It must contain no secrets.
3. `node --env-file=.env --env-file=.env.local payment-registration.mjs key` creates a scoped runtime key. It is written only to `.local/mps-runtime.env`.
4. Edit the registration body in `payment-registration.mjs` first. It still has the template's name, description, tags and author, so set PersonaLab values. Then run `... payment-registration.mjs register`, and poll with `... payment-registration.mjs` until `RegistrationConfirmed`. `TODO: agentIdentifier`
5. Set `PAID_TASKS_ENABLED=true`, restart the worker, and create a paid Task. `TODO: paid Task ID`
6. After unlock, collect, then check with `sokosumi runtime receipt TASK_ID --coworker-id ... --json`, and verify independently with Blockfrost (`settlement.mjs`). `TODO: collection tx hash, net receipt`

---

## Problems and fixes

| # | Symptom (exact) | Cause | Fix |
|---|---|---|---|
| 1 | Records were going to be created under the wrong account | The first `auth login` was finished in a browser signed in to a secondary account | `auth logout`, sign the browser in to the owner account, log in again with a print-only URL, check `auth whoami`. Nothing was created on the secondary account. |
| 2 | `OAuth login timed out waiting for the browser callback` (twice) | CLI 1.0.4 on Windows runs `cmd /c start "" URL`, and `cmd` cuts the URL at the first `&` | Preload script that reroutes to `rundll32 url.dll,FileProtocolHandler URL` (section 2), or open a printed URL by hand |
| 3 | `execFileSync('sokosumi')` fails on Windows | Node cannot run the `.cmd` shim without a shell | `sokosumi-cli.mjs` runs the package's JS `bin` entry with `node` |
| 4 | `coworkers update` → HTTP 422: `metadata.channels` must be a record | `channels` was not an object | `"channels": {}` |
| 5 | `coworkers update` → HTTP 422: `profile.llm` must be an array | `llm` was a single string | `"llm": ["DeepSeek V4.1 Flash via OpenRouter"]` |
| 6 | `coworkers update` → HTTP 422: `profile.hosting` must be a string | `hosting` was not a string | `"hosting": "Operator-hosted LangGraph service"` |
| 7 | `npm run smoke` → `Agent service has no model configured` | `MODEL_API_KEY` was missing from `.env.local` and the environment | Add the key to `.env.local`. The config is re-read on every call, so no restart is needed. The smoke test then passed in 28 s. |
| 8 | Port 21951 still in use after stopping `npm start` | On Windows, Ctrl+C on `npm start` can leave the child `python.exe` running | Find it with `netstat -ano \| findstr :21951` and stop it with `taskkill /PID <pid> /F` |
| 9 | Template tests failed on Windows | Hard-coded `/` paths and a POSIX file-mode assertion | Tests no longer depend on the path separator. The mode assertion is skipped on win32, and `sokosumi-runtime.mjs` checks the skills path in a separator-neutral way. |
| 10 | MPS could not start: Docker daemon not running | Docker Desktop was installed but not started | Start Docker Desktop, then `docker info` |
| 11 | MPS needs a different pnpm version from the global one (global was 10.24.0) | MPS pins its package manager | `corepack prepare pnpm@10.30.2 --activate` |
| 12 | Risk of wallet secrets in logs | The MPS seed prints wallet material | Run the seed with stdout and stderr sent to null (section 9.4) |
