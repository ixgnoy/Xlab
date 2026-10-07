import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from crest_graph import ig_workflows, scheduler, server
from crest_graph.graph import build_graph
from crest_graph.instagram import AUTOMATION_DISCLOSURE, InstagramClient, InstagramError, MessagingWindowClosed
from crest_graph.store import Store

from test_graph import fake

TOKEN = "IGAAsecretTOKEN123"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class FakeGraph:
    """httpx MockTransport that mimics graph.instagram.com responses and records every request."""

    def __init__(self, statuses=("IN_PROGRESS", "FINISHED"), media=None, fail_publish=False):
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses)
        self.media = media or []
        self.fail_publish = fail_publish
        self.counter = 0

    def body(self, request):
        if request.headers.get("content-type", "").startswith("application/json"):
            return json.loads(request.content)
        return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        assert path.startswith("/v25.0/")
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(request.url)
        path = path[len("/v25.0"):]
        if method == "POST" and path == "/1784/media":
            self.counter += 1
            return httpx.Response(200, json={"id": f"c{self.counter}"})
        if method == "GET" and path.startswith("/c") and request.url.params.get("fields") == "status_code":
            return httpx.Response(200, json={"status_code": self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]})
        if method == "POST" and path == "/1784/media_publish":
            if self.fail_publish:
                return httpx.Response(500, json={"error": {"message": f"boom token={TOKEN}", "code": 2}})
            return httpx.Response(200, json={"id": "m-" + self.body(request)["creation_id"]})
        if method == "GET" and path == "/1784/content_publishing_limit":
            return httpx.Response(200, json={"data": [{"quota_usage": 3, "config": {"quota_total": 100, "quota_duration": 86400}}]})
        if method == "GET" and path == "/1784/media":
            return httpx.Response(200, json={"data": self.media})
        if method == "GET" and path.endswith("/insights"):
            names = request.url.params["metric"].split(",")
            return httpx.Response(200, json={"data": [{"name": n, "period": "lifetime", "values": [{"value": i + 1}]} for i, n in enumerate(names)]})
        if method == "GET" and path.endswith("/comments"):
            return httpx.Response(200, json={"data": [{"id": "cm1", "text": "where is this?", "username": "fan1", "timestamp": "2026-10-07T10:00:00+0000"}]})
        if method == "POST" and path.endswith("/replies"):
            return httpx.Response(200, json={"id": "reply1"})
        if method == "GET" and path == "/1784/conversations":
            assert request.url.params["platform"] == "instagram"
            return httpx.Response(200, json={"data": [{"id": "conv1", "updated_time": "2026-10-07T11:00:00+0000"}]})
        if method == "GET" and path == "/conv1":
            return httpx.Response(200, json={"id": "conv1", "messages": {"data": [
                {"id": "msg1", "created_time": "2026-10-07T11:00:00+0000", "from": {"id": "igsid9", "username": "fan2"}, "message": "collab?"},
                {"id": "msg0", "created_time": "2026-10-07T10:59:00+0000", "from": {"id": "1784", "username": "me"}, "message": "hi"},
            ]}})
        if method == "POST" and path == "/1784/messages":
            return httpx.Response(200, json={"recipient_id": "igsid9", "message_id": "mid1"})
        return httpx.Response(404, json={"error": {"message": f"unexpected {method} {path}"}})


def live(fake_graph: FakeGraph, **kwargs) -> InstagramClient:
    return InstagramClient(TOKEN, "1784", transport=httpx.MockTransport(fake_graph), sleep=lambda s: None,
                           poll_interval=1, max_wait=5, **kwargs)


# ---- client shapes ----------------------------------------------------------------------------------------
def test_reel_publish_flow_polls_then_publishes():
    g = FakeGraph()
    result = live(g).publish_container("REELS", "https://cdn.example/r.mp4", "hello")
    assert result == {"dry_run": False, "status": "published", "container_id": "c1", "media_id": "m-c1"}
    create = g.body(g.requests[0])
    assert create == {"media_type": "REELS", "video_url": "https://cdn.example/r.mp4", "share_to_feed": "true", "caption": "hello"}
    assert [r.url.params.get("fields") for r in g.requests[1:3]] == ["status_code", "status_code"]
    assert g.requests[-1].url.path.endswith("/media_publish")


def test_image_and_carousel_container_shapes():
    g = FakeGraph(statuses=("FINISHED",))
    client = live(g)
    client.publish_container("IMAGE", "https://cdn.example/a.jpg", "pic")
    assert g.body(g.requests[0]) == {"image_url": "https://cdn.example/a.jpg", "caption": "pic"}
    g.requests.clear()
    client.publish_container("CAROUSEL", ["https://cdn.example/a.jpg", "https://cdn.example/b.mp4"], "set")
    posts = [g.body(r) for r in g.requests if r.method == "POST" and r.url.path.endswith("/media")]
    assert posts[0] == {"image_url": "https://cdn.example/a.jpg", "is_carousel_item": "true"}
    assert posts[1] == {"media_type": "VIDEO", "video_url": "https://cdn.example/b.mp4", "is_carousel_item": "true"}
    assert posts[2]["media_type"] == "CAROUSEL" and posts[2]["children"] == "c2,c3" and posts[2]["caption"] == "set"
    with pytest.raises(ValueError):
        client.publish_container("CAROUSEL", ["https://cdn.example/a.jpg"], "one")


def test_container_error_status_raises():
    with pytest.raises(InstagramError, match="ERROR"):
        live(FakeGraph(statuses=("ERROR",))).publish_container("REELS", "https://x/r.mp4", "c")


def test_limit_insights_comments_and_errors_redact_token():
    g = FakeGraph()
    client = live(g)
    assert client.content_publishing_limit() == {"dry_run": False, "quota_usage": 3, "quota_total": 100, "quota_duration": 86400}
    insights = client.media_insights("m1", "REELS")
    assert set(insights) - {"dry_run"} == {"views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time"}
    assert "views" not in client.media_insights("m2", "FEED")
    assert client.list_comments("m1")[0]["id"] == "cm1"
    assert client.reply_comment("cm1", "thanks!")["sent"] is True
    assert g.body(g.requests[-1]) == {"message": "thanks!"}
    with pytest.raises(InstagramError) as info:
        live(FakeGraph(fail_publish=True)).media_publish("c1")
    assert TOKEN not in str(info.value) and "[redacted]" in str(info.value)
    assert TOKEN not in repr(client)


def test_send_dm_window_and_first_dm_disclosure():
    g = FakeGraph()
    client = live(g)
    with pytest.raises(MessagingWindowClosed):
        client.send_dm("igsid9", "hi", last_inbound_at=NOW - timedelta(hours=25), first_dm=True, now=NOW)
    with pytest.raises(MessagingWindowClosed):
        client.send_dm("igsid9", "hi", last_inbound_at=None, first_dm=True, now=NOW)
    assert not g.requests
    sent = client.send_dm("igsid9", "hi", last_inbound_at="2026-10-07T11:00:00+0000", first_dm=True, now=NOW)
    body = g.body(g.requests[-1])
    assert body == {"recipient": {"id": "igsid9"}, "message": {"text": AUTOMATION_DISCLOSURE + "hi"}}
    assert sent["sent"] is True
    client.send_dm("igsid9", "again", last_inbound_at=NOW - timedelta(hours=1), first_dm=False, now=NOW)
    assert g.body(g.requests[-1])["message"]["text"] == "again"


def test_dry_run_never_calls_or_claims_publish():
    client = InstagramClient(None, None)
    assert client.dry_run
    result = client.publish_container("REELS", "https://x/r.mp4", "c")
    assert result["status"] == "dry_run" and result["media_id"] is None and "DRY-RUN" in result["note"]
    assert client.reply_comment("1", "x")["sent"] is False
    dm = client.send_dm("u", "x", last_inbound_at=datetime.now(timezone.utc), first_dm=True)
    assert dm["sent"] is False and "DRY-RUN" in dm["note"]
    assert all(m["dry_run"] for m in client.list_media())
    assert client.media_insights("x")["label"] == "DRY-RUN"
    with pytest.raises(InstagramError):
        client.media_publish("c1")


# ---- store + scheduler ------------------------------------------------------------------------------------
def test_store_claim_is_atomic(tmp_path):
    store = Store(tmp_path / "s.db")
    sid = store.add_schedule(publish_at_utc="2026-10-07T10:00:00+00:00", media_type="REELS", caption="c", media_url="https://x/r.mp4")
    assert store.claim(sid) is True
    assert store.claim(sid) is False
    assert store.get_schedule(sid)["status"] == "publishing" and store.get_schedule(sid)["attempts"] == 1
    item = store.upsert_inbox(kind="comment", external_id="cm1", author="a", text="t")
    assert store.upsert_inbox(kind="comment", external_id="cm1", author="a", text="t") == item
    store.add_snapshot("m1", {"reach": 5})
    assert store.snapshots("m1")[0]["metrics"] == {"reach": 5}


def test_run_due_publishes_due_only_and_respects_limit(tmp_path):
    store = Store(tmp_path / "s.db")
    due = store.add_schedule(publish_at_utc="2026-10-07T11:00:00+00:00", media_type="REELS", caption="a", media_url="https://x/r.mp4")
    later = store.add_schedule(publish_at_utc="2026-10-08T11:00:00+00:00", media_type="REELS", caption="b", media_url="https://x/r.mp4")
    nomedia = store.add_schedule(publish_at_utc="2026-10-07T09:00:00+00:00", media_type="IMAGE", caption="c")
    summary = scheduler.run_due(NOW, store=store, client=live(FakeGraph()))
    assert summary["published"] == [{"id": due, "media_id": "m-c1"}]
    assert store.get_schedule(due)["status"] == "published"
    assert store.get_schedule(later)["status"] == "queued"
    assert store.get_schedule(nomedia)["status"] == "queued" and "media_url" in store.get_schedule(nomedia)["last_error"]

    class Full(FakeGraph):
        def __call__(self, request):
            if request.url.path.endswith("/content_publishing_limit"):
                return httpx.Response(200, json={"data": [{"quota_usage": 100, "config": {"quota_total": 100}}]})
            return super().__call__(request)

    store.set_media_url(nomedia, "https://x/a.jpg")
    summary = scheduler.run_due(NOW, store=store, client=live(Full()))
    assert summary["published"] == [] and "limit" in summary["skipped"][0]["reason"]


def test_run_due_dry_run_changes_nothing(tmp_path):
    store = Store(tmp_path / "s.db")
    sid = store.add_schedule(publish_at_utc="2026-10-07T11:00:00+00:00", media_type="REELS", caption="a", media_url="https://x/r.mp4")
    summary = scheduler.run_due(NOW, store=store, client=InstagramClient(None, None))
    assert summary["dry_run"] and summary["published"] == []
    assert "DRY-RUN" in summary["skipped"][0]["reason"]
    assert store.get_schedule(sid)["status"] == "queued" and store.get_schedule(sid)["attempts"] == 0


def test_unknown_publish_outcome_is_inspected_not_retried(tmp_path):
    store = Store(tmp_path / "s.db")
    sid = store.add_schedule(publish_at_utc="2026-10-07T11:00:00+00:00", media_type="REELS", caption="a", media_url="https://x/r.mp4")
    first = FakeGraph(fail_publish=True)
    scheduler.run_due(NOW, store=store, client=live(first))
    row = store.get_schedule(sid)
    assert row["status"] == "publishing" and row["ig_container_id"] == "c1"
    # Next run within the stale window: untouched, no new container.
    again = FakeGraph()
    scheduler.run_due(NOW + timedelta(minutes=1), store=store, client=live(again))
    assert not [r for r in again.requests if r.method == "POST"]
    # After the stale window, recovery sees the container already PUBLISHED and does not post again.
    recovered = FakeGraph(statuses=("PUBLISHED",), media=[{"id": "m9", "caption": "a", "timestamp": "2026-10-07T12:00:30+0000"}])
    summary = scheduler.run_due(NOW + timedelta(minutes=20), store=store, client=live(recovered))
    assert summary["recovered"][0]["outcome"].startswith("published")
    assert store.get_schedule(sid)["status"] == "published" and store.get_schedule(sid)["ig_media_id"] == "m9"
    assert not [r for r in recovered.requests if r.method == "POST"]


def test_recovery_publishes_finished_container_once(tmp_path):
    store = Store(tmp_path / "s.db")
    sid = store.add_schedule(publish_at_utc="2026-10-07T11:00:00+00:00", media_type="REELS", caption="a", media_url="https://x/r.mp4")
    store.claim(sid, NOW - timedelta(hours=1))
    store.set_container(sid, "c7")
    g = FakeGraph(statuses=("FINISHED",))
    scheduler.run_due(NOW, store=store, client=live(g))
    assert store.get_schedule(sid)["ig_media_id"] == "m-c7"
    assert [r.url.path for r in g.requests if r.method == "POST"] == ["/v25.0/1784/media_publish"]


def test_scheduler_cli_once_dry_run(capsys):
    assert scheduler.main(["--once"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out


# ---- graph wiring -----------------------------------------------------------------------------------------
CALENDAR = """## Posting calendar
| Date | Local time | Timezone | Format | Pillar | Hook | Caption | Status |
|---|---|---|---|---|---|---|---|
| 2026-10-08 (Thu) | 7:30 PM | America/New_York | Reel | Tips | 3 swaps | Try these 3 swaps #ai | needs-media |
| Oct 9 | 08:00 | UTC+8 | Carousel | Story | Day 1 | Day one recap | queued |
| 2026-10-10 | 09:00 | UTC | Story | BTS | peek | quick peek | queued |
"""


def test_parse_calendar_converts_to_utc():
    rows = ig_workflows.parse_calendar(CALENDAR, NOW)
    assert rows[0]["publish_at"] == datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)  # EDT = UTC-4
    assert rows[0]["media_type"] == "REELS" and rows[0]["caption"] == "Try these 3 swaps #ai"
    assert rows[1]["publish_at"] == datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    assert rows[1]["media_type"] == "CAROUSEL"
    assert rows[2]["error"]


def test_scheduler_agent_appends_queue_dry_run():
    out = build_graph(fake(CALENDAR)).invoke({"input": "[stage:schedule] plan"}, {"configurable": {"thread_id": "t1"}})
    queue = out["output"].split("## Queue", 1)[1]
    assert "DRY-RUN" in queue and "dry_run" in queue and "skipped" in queue
    rows = ig_workflows._store().schedules()
    assert [r["status"] for r in rows] == ["dry_run", "dry_run"] and rows[0]["thread_id"] == "t1"


ENGAGE_REPLY = """## Inbox triage
| # | From | Message summary | Intent | Priority | Action |
|---|---|---|---|---|---|
| 1 | @ann | loves the reel | praise | low | reply |
| 2 | @bob | asks about refund | complaint | high | escalate-to-human |
| 3 | @cat | where to buy | lead | med | reply |

## Draft replies
- **#1:** Thank you so much!
- **#3:** Link is in bio - happy shopping!

## Approval needed
All drafts need approval.
"""


def test_engage_dry_run_saves_pending_and_approve_sends_nothing():
    out = build_graph(fake(ENGAGE_REPLY)).invoke({"input": "[stage:engage] comments: ..."}, {"configurable": {"thread_id": "t2"}})
    assert "## Approval" in out["output"] and "APPROVE" in out["output"] and "DRY-RUN" in out["output"]
    rows = ig_workflows._store().inbox("t2")
    assert [(r["draft"], r["status"]) for r in rows] == [
        ("Thank you so much!", "pending"), (None, "escalated"), ("Link is in bio - happy shopping!", "pending")]
    report = ig_workflows.approve(f"APPROVE {rows[0]['id']},{rows[1]['id']}", "t2")
    assert "post it manually" in report and "escalated" in report
    assert ig_workflows._store().get_inbox(rows[0]["id"])["status"] == "approved"


def test_engage_live_pulls_inbox_and_approve_sends(monkeypatch):
    g = FakeGraph(media=[{"id": "m1", "caption": "x"}])
    client = live(g)
    monkeypatch.setattr(ig_workflows, "_client", lambda: client)
    items = ig_workflows.fetch_inbox("t3")
    assert [(r["kind"], r["author"]) for r in items] == [("comment", "fan1"), ("dm", "fan2")]
    assert not [r for r in g.requests if r.method == "POST"]  # fetching never sends
    reply = f"## Inbox triage\n| # | From | Action |\n|---|---|---|\n| {items[0]['id']} | fan1 | reply |\n| {items[1]['id']} | fan2 | reply |\n\n" \
            f"## Draft replies\n#{items[0]['id']}: In Lisbon!\n#{items[1]['id']}: Send details by email please.\n"
    section = ig_workflows.record_drafts(reply, items, thread_id="t3")
    assert "DRY-RUN" not in section and "pending" in section
    assert not [r for r in g.requests if r.method == "POST"]
    results = ig_workflows.approve_ids([items[0]["id"], items[1]["id"]], "t3",
                                       now=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))
    assert [r["outcome"] for r in results] == ["sent", "sent"]
    posts = [(r.url.path, g.body(r)) for r in g.requests if r.method == "POST"]
    assert posts[0] == ("/v25.0/cm1/replies", {"message": "In Lisbon!"})
    assert posts[1][1]["message"]["text"].startswith(AUTOMATION_DISCLOSURE)
    assert ig_workflows.approve_ids([items[0]["id"]], "t3")[0]["outcome"] == "already sent"


def test_analyst_injects_live_insights(monkeypatch):
    g = FakeGraph(media=[{"id": "m1", "caption": "reel one", "media_product_type": "REELS", "timestamp": "2026-10-06T10:00:00+0000"}])
    monkeypatch.setattr(ig_workflows, "_client", lambda: live(g))
    model = fake("## KPI summary")
    out = build_graph(model).invoke({"input": "[stage:analyze] last week"})
    prompt = model.calls[0][1].content
    assert "## Instagram insights (live" in prompt and "| m1 |" in prompt
    assert "live Instagram insights for 1" in out["output"]
    assert ig_workflows._store().snapshots("m1")


def test_analyst_dry_run_uses_pasted_metrics():
    model = fake("## KPI summary")
    out = build_graph(model).invoke({"input": "[stage:analyze] reach 100 likes 5"})
    assert model.calls[0][1].content == "reach 100 likes 5"
    assert "pasted" in out["output"]


def test_approve_endpoint_requires_token(monkeypatch):
    real_get = server.config.get
    monkeypatch.setattr(server.config, "get", lambda name, default=None: "t0ken" if name == "CREST_GRAPH_TOKEN" else real_get(name, default))
    store = ig_workflows._store()
    item = store.upsert_inbox(kind="comment", external_id="cmX", author="a", text="t", thread_id="t9", draft="hi")
    client = TestClient(server.app)
    assert client.post("/approve", json={"thread_id": "t9", "ids": [item]}).status_code == 401
    ok = client.post("/approve", json={"thread_id": "t9", "ids": [item]}, headers={"Authorization": "Bearer t0ken"})
    assert ok.status_code == 200 and ok.json()["results"][0]["outcome"] == "DRY-RUN: approved, not sent"


def test_token_in_query_fallback_keeps_token_out_of_errors():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(400, json={"error": {"message": f"bad token {TOKEN}", "code": 190}})

    client = InstagramClient(TOKEN, "1784", transport=httpx.MockTransport(handler), token_in_query=True)
    with pytest.raises(InstagramError) as info:
        client.list_media()
    assert seen[0].url.params["access_token"] == TOKEN and "authorization" not in seen[0].headers
    assert TOKEN not in str(info.value) and info.value.code == 190
