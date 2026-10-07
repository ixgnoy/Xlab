# Xlab Workflow → PersonaLab Coworker Integration Plan

**Goal:** When the Xlab workflow is finished, plug it into the PersonaLab Coworker as its answer step, so a paid Sokosumi Task runs the workflow and returns its output. Builds on the base plan in the CardanoFishPrivate repo (`docs/superpowers/plans/2026-10-06-sokosumi-coworker.md`) (Phase 3 worker, Phase 4 tools). This plan replaces the Phase 3 placeholder answer.

**Status when written (2026-10-07):**
- Xlab repo (`github.com/ixgnoy/Xlab`) is cloned at `~/Downloads/Xlab` but holds only a README. The workflow does not exist yet, so everything below is written against an adapter contract, not against Xlab internals.
- Vendor `CardanoFish` (`01a1156a-7184-77bb-a15f-f712b72381be`, slug `cardanofish-johnny`). The CLI allows one vendor per account and has no rename, so the vendor name stays.
- Coworker **PersonaLab** (`01a1156a-dbc8-7360-813b-043c0e148296`), registered and connected to the personal workspace.
- TOKEN2049 workspace access requested, **pending** (Access ID `01a11580-fdb2-7259-86af-18c58e2ae61e`). Re-run the same `coworkers connect` after approval.
- Not done: runtime key import, MPS, worker, paid test Task.

## Gate: do not start until all are true

1. Xlab workflow runs end to end on its own, locally, from a single input to a single output.
2. Phase 3 of the base plan is green: a rehearsal Task and a paid Task both complete with the placeholder answer, and seller collection is verified on the Preprod explorer.
3. One sample chain (Offer 1 → 2 → 3 input and output) is saved in Xlab (`fixtures/`), so integration can be checked without the live marketplace.

Integrating before gate 2 means debugging payments and the workflow at the same time. Keep them separate, as the guide says: prove each stage separately.

## The three offers (confirmed with Johnny)

Each offer is its own paid Task with its own quote. Offer 2 needs Offer 1's output, and Offer 3 needs Offer 2's.

| # | Offer | Input | Output |
|---|---|---|---|
| 1 | **Trend + brand ideas** | Company name or URL, brand/company guidelines, topic or market | Trend analysis (cited) and content ideas that follow the brand guidelines |
| 2 | **Script + scene plan** | Offer 1 result (chosen idea) | Script and scene-by-scene plan |
| 3 | **Video generation** | Offer 2 result | Generated video (hosted link) |

### How chaining works

- The user starts Offer 2 by giving the **previous Task ID** in the brief (and which idea to use, if Offer 1 returned several). Same for Offer 3.
- The worker fetches that Task's saved result itself (`tasks get <id>` or its own journal, whichever is authoritative) instead of trusting pasted text. It checks:
  - the Task belongs to this Coworker and is `COMPLETED`;
  - it is the right offer type (a script request cannot consume a video Task);
  - it was requested by the same user or workspace.
- If any check fails, or no ID is given, return `needs-input` and ask for it. Never invent the missing upstream step.
- Store upstream Task ID and its `resultHash` in the downstream Task's journal row, so the demo can show the full lineage and a downstream result can be traced to exactly what it was built from.
- Pasted text is allowed as a fallback only if the user says so. Mark it as unverified in the result.
- No orchestration layer. The user (or an agent buying all three) sequences the Tasks. Each Task completes and settles independently.

### Per-offer constraints

1. **Offer 1:** needs real citations. Reuse the guide's "source verification" scenario. Brand guidelines may arrive as a file. CLI 1.0.4 only handles text, so accept a URL or pasted text for now.
2. **Offer 2:** pure text, fast and cheap. Output must be machine-readable enough for Offer 3. Return Markdown with a fenced JSON block of scenes (`id`, `duration`, `visual`, `voiceover`), and validate it before submitting.
3. **Offer 3 is the risk:**
   - Video generation is slow and costs real money per call. Quote is 1 tUSDM, so cap spend per Task and refuse scripts over a scene/length limit.
   - It likely exceeds a default `submitResultTime`. Measure runtime first. Open question 3 (max window) matters most here.
   - A video cannot go in the Task result. Upload it to hosted storage and return the link, a thumbnail and the scene list. Check the link works before `submit-result`.
   - Generation can fail partway. Save the provider job ID in the journal before polling, and resume polling after a crash instead of starting a second paid generation.
   - Content safety: refuse scripts that ask for real people's likeness or other disallowed content, with a clear reason, and let the payment refund.

### Adapter change

One adapter per offer, same contract, selected by the offer in the Task. Add `offer: "trend" | "script" | "video"` and `upstream?: { taskId: string; resultHash: string; text: string }` to `AnswerInput`. `answer()` stays one function with a switch, not three services.

## Adapter contract

The worker talks to the workflow through one function. Nothing else in the worker knows about Xlab.

```ts
// coworker/src/answer.ts
export type AnswerInput = {
  taskId: string;
  brief: string;            // Task description from Sokosumi
  attachments: string[];    // local paths, if any
  deadline: Date;           // submitResultTime minus safety margin
  signal: AbortSignal;      // aborted at deadline
};

export type AnswerResult =
  | { kind: "done"; text: string }                 // Markdown result
  | { kind: "needs-input"; question: string }      // asks the user, never guesses
  | { kind: "failed"; reason: string; retryable: boolean };

export function answer(input: AnswerInput): Promise<AnswerResult>;
```

Rules:
- `text` is exactly what gets hashed (`resultHash` = sha256 of it) and submitted. It is saved to the journal before `submit-result`, and never regenerated after that.
- Missing information returns `needs-input`. The worker moves the Task to `INPUT_REQUIRED`. This is one of the three scenarios the guide tests.
- Secrets (model keys and so on) come from env vars in the worker process. They are never in Task content, results or logs.

## Phase A: Wrap the workflow (≈1–2 h)

Pick the lowest rung that fits what Xlab turns out to be:

| Xlab form | Wrapper |
|---|---|
| TypeScript/Node library | Import in `answer.ts`, call directly |
| Python script or package | `execFile` with args and stdin, parse stdout JSON, hard timeout |
| Running HTTP service | `fetch` with timeout and the abort signal |

Do not add a queue, plugin system or config layer. One adapter, one function.

1. Add Xlab as a git submodule or pinned dependency (pin a commit, not `main`), so the demo does not change under us.
2. Write `answer.ts` for the chosen form.
3. Enforce `deadline`. If the workflow exceeds it, return `failed` with `retryable: false`. The worker never submits late (base plan review point 3).
4. Validate output before returning `done`: non-empty, under the Sokosumi result size limit (check the limit; unknown today), no secrets pattern matches.

**Check:** a script runs the three fixtures through `answer()` and diffs against the expected outputs.

## Phase B: Wire into the stage machine (≈1 h)

Replace the placeholder in the `working` stage of `paid.ts`:

- `working` → call `answer()`.
  - `done` → save `text` and `resultHash` to the journal, then `result-saved`.
  - `needs-input` → post the question as a Task comment, set `INPUT_REQUIRED`, and park the Task. Resume when the user replies. The payment stays in escrow.
  - `failed` → comment the reason, do not submit a result. Let the payment time out and refund. Never fabricate output to get paid.
- Add the per-offer `submitResultTime` once the workflow's real runtime is known (measure p95 on fixtures, add margin).

**Check:** unit tests for each of the three return kinds, plus crash/resume between `working` and `result-saved`.

## Phase C: Rehearse, then pay (≈1 h)

1. Rehearsal Task (no payment) in the personal workspace using one fixture brief. Confirm `COMPLETED` and that the result matches the fixture.
2. Paid Task with the same brief. Confirm the full chain through collection.
3. Run the full chain once as paid Tasks (Offer 1, then 2 with the Offer 1 Task ID, then 3 with the Offer 2 Task ID). Run the three guide scenarios on Offer 1 and 2 as rehearsal Tasks, and tool failure on Offer 3:
   - **Normal input:** result with sources the workflow actually used.
   - **Missing information:** a brief with a gap. Expect `INPUT_REQUIRED`, not a made-up answer.
   - **Tool failure:** make a workflow dependency fail (bad key or blocked URL). Expect a clear failure comment and no result submitted.

**Evidence to keep (IDs only, no keys):** Task IDs for each scenario, event IDs, payment and collection tx hashes, seller address, net tUSDM received.

## Phase D: Go live for the event

1. Confirm TOKEN2049 workspace access is `GRANTED`. Re-run the connect command if it still says pending.
2. Update the Coworker profile (`coworkers update --metadata-file`, validated against the schema) with a one-line description of the workflow's job and example prompts. Say what it needs as input.
3. Keep worker, MPS and Postgres online through judging (Railway non-serverless, or the Alibaba server). One active worker only.
4. Watch the first real Task end to end before leaving it unattended.

## Submission mapping

| BuilderBase item | Source |
|---|---|
| Code and start instructions | This repo plus Xlab commit hash, README with worker setup |
| Agent demo | Coworker ID, sample Task, the three scenario results |
| Completed Task evidence | Task IDs, Coworker ID, result output, payment event IDs |
| Payment proof | Tx hash, explorer link, seller receipt, collection tx, seller address, USDM unit, net amount |
| Slides | Google Drive .ppt/.keynote with the demo recording embedded |

## Risks

1. **Xlab is not ready in time.** Fallback: ship the Phase 3 placeholder with a thin real step (for example the CardanoFish research engine from base plan Phase 4), so the payment proof is still real.
2. **Workflow is slower than the Task window.** Measure early. Raise `submitResultTime` if Sokosumi allows it (open question 3 in the base plan), or cut scope per Task.
3. **Workflow needs files.** CLI 1.0.4 only submits a text result and may not upload files (open question 4 in the base plan). Return Markdown plus a hosted link.
4. **Output not reproducible.** Fixtures are only regression checks. Because the journal stores the exact result before submit, the hash on-chain always matches what the user received.

## Open questions

1. What runs each offer: one codebase in Xlab or three? What is the interface (library, script, HTTP)? This decides Phase A.
2. Which video provider does Offer 3 use, what is its cost per video and p95 runtime, and who holds the key?
3. Where is the video hosted for judges, and for how long?
4. Does Offer 1 return one idea or several? Offer 2 needs to know which was chosen.
5. Fixtures: with three chained offers we need one chain of three sample Tasks, not three independent ones.
