# Instagram setup (Schedule / Engage / Analyze)

PersonaLab uses the official **Instagram API with Instagram Login** (host `graph.instagram.com`, API `v25.0`).
Until `IG_ACCESS_TOKEN` and `IG_USER_ID` are set, everything runs in **DRY-RUN**: calendars are saved as
`dry_run` rows, drafts are saved but never sent, and analytics use the metrics pasted into the request.
Nothing is ever reported as published or sent in DRY-RUN.

## 1. Meta app

1. Convert the Instagram account to a **Professional** account (Business or Creator).
2. At developers.facebook.com create an app (type **Business**) and add the **Instagram** product, then pick
   **API setup with Instagram login**.
3. Under *Business login settings* add your OAuth redirect URI.
4. Request these permissions: `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_comments`, `instagram_business_manage_messages`, `instagram_business_manage_insights`.
5. For your **own** account, **Standard Access** is enough: add the account as an Instagram tester /
   app role and accept the invite in the Instagram app. App Review (Advanced Access) is only needed to serve
   accounts you do not own.

## 2. Tokens

1. Open the authorize URL in a browser while logged in to the Instagram account:
   `https://www.instagram.com/oauth/authorize?client_id=APP_ID&redirect_uri=REDIRECT&response_type=code&scope=instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments,instagram_business_manage_messages,instagram_business_manage_insights`
2. Exchange the `code` (valid 1 hour, single use) for a short-lived token, server side:
   `POST https://api.instagram.com/oauth/access_token` with `client_id`, `client_secret`,
   `grant_type=authorization_code`, `redirect_uri`, `code`. The response includes `user_id`.
3. Exchange it for a **long-lived token (60 days)**:
   `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=APP_SECRET&access_token=SHORT_TOKEN`
4. Refresh before it expires (token at least 24h old):
   `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=LONG_TOKEN`

Run these from a terminal; never paste tokens into a Task, a prompt, or a commit.

## 3. Environment (`.env.local`)

| Variable | Required | Meaning |
|---|---|---|
| `IG_ACCESS_TOKEN` | for live mode | Long-lived Instagram User token |
| `IG_USER_ID` | for live mode | Instagram professional account id (`user_id` from the token exchange, or `GET /me?fields=user_id`) |
| `IG_APP_SECRET` | optional | App secret, only for running the token exchange/refresh yourself |
| `IG_API_VERSION` | optional | Default `v25.0` |
| `IG_TIMEOUT_S` | optional | HTTP timeout, default 20 |
| `IG_TOKEN_IN_QUERY` | optional | `1` sends the token as `access_token` instead of a Bearer header |
| `PERSONALAB_DB` | optional | SQLite path, default `.local/personalab.db` |

## 4. How each stage behaves

- **Schedule** - the calendar table is parsed into the `schedules` table (`queued`, or `dry_run`) and a
  `## Queue` section lists the IDs. Attach a public media URL to each post, then run the scheduler:
  `uv run --project crest-graph python -m crest_graph.scheduler --set-media 3 https://cdn.example.com/reel.mp4`
  `uv run --project crest-graph python -m crest_graph.scheduler --loop` (or `--once`, `--list`).
  Flow: create container -> poll `status_code` until `FINISHED` -> `media_publish`. Rows are claimed as
  `publishing` before any call and stuck rows are inspected (container status, recent media) before any retry,
  so a crash does not double-post. The 100 API posts per rolling 24h limit is checked via
  `content_publishing_limit`. Reels: 9:16 H.264 MP4 at a public URL. Stories are not queued.
- **Engage** - with a token, recent comments and inbound DMs are pulled into the `inbox` table. The model drafts
  replies; they are saved as `pending` and **nothing is sent automatically**. Reply to the Task with
  `APPROVE 1,3` (or `POST /approve {"thread_id": "...", "ids": [1, 3]}` with the bearer token) to send.
  DMs are only sent inside the 24-hour window after the user's last message, and the first automated DM to a
  person starts with an automation disclosure. Escalated items always need a human.
- **Analyze** - with a token, insights for the 10 most recent media are fetched (reels: views, reach, likes,
  comments, shares, saved, total_interactions, ig_reels_avg_watch_time; feed posts: reach, likes, comments,
  shares, saved), saved to `insights_snapshots`, and given to the model as data. Without a token, the
  model only uses metrics pasted in the request and never invents numbers.

## 5. AI disclosure

- The persona is an original AI character. Say so in the bio (for example "AI-generated creator") and apply
  Instagram's **AI info** label to photorealistic AI images and video when posting.
- Keep a short disclosure in captions of photorealistic posts (for example `#AIgenerated`).
- Automated DMs disclose that the reply is automated at the start of a conversation (built in); disclose again
  after a long gap or when switching from a human to automation.
- Never imitate a real person's face, voice or name, and never post medical, financial-guarantee or income claims.
