"""Publishes due posts from the local queue.

    uv run --project crest-graph python -m crest_graph.scheduler --once
    uv run --project crest-graph python -m crest_graph.scheduler --loop --interval 60
    uv run --project crest-graph python -m crest_graph.scheduler --list
    uv run --project crest-graph python -m crest_graph.scheduler --set-media 3 https://cdn.example.com/reel.mp4

Without IG_ACCESS_TOKEN / IG_USER_ID it runs in DRY-RUN: it reports what would be published and changes nothing.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from .instagram import POSTS_PER_24H, InstagramClient, InstagramError, _parse_time
from .store import Store, get_store

log = logging.getLogger("crest_graph.scheduler")
MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=15)


def _client() -> InstagramClient:
    return InstagramClient.from_env()


def _find_published(client: InstagramClient, row: dict) -> str | None:
    """Look for a recently published media item matching this row (used when a crash lost the media id)."""
    caption = (row.get("caption") or "").strip()
    if not caption:
        return None
    claimed = _parse_time(row.get("claimed_at"))
    try:
        media = client.list_media(limit=25)
    except InstagramError:
        return None
    for item in media:
        if (item.get("caption") or "").strip() != caption:
            continue
        try:
            posted = _parse_time(item.get("timestamp"))
        except ValueError:
            posted = None
        if claimed is None or posted is None or posted >= claimed - timedelta(minutes=5):
            return str(item.get("id"))
    return None


def recover(store: Store, client: InstagramClient, now: datetime, stale_after: timedelta = STALE_AFTER) -> list[dict]:
    """Inspect rows stuck in 'publishing' instead of retrying them blindly (avoids double posts)."""
    results = []
    if client.dry_run:
        return results
    for row in store.stale_publishing(now - stale_after):
        sid, outcome = row["id"], "left publishing"
        try:
            if row["ig_media_id"]:
                store.mark_published(sid, row["ig_media_id"], now)
                outcome = "published (media id already recorded)"
            elif row["ig_container_id"]:
                status = client.container_status(row["ig_container_id"])
                if status == "PUBLISHED":
                    store.mark_published(sid, _find_published(client, row), now)
                    outcome = "published (container already PUBLISHED)"
                elif status == "FINISHED":
                    store.mark_published(sid, client.media_publish(row["ig_container_id"]), now)
                    outcome = "published (finished container)"
                elif status in ("ERROR", "EXPIRED"):
                    if row["attempts"] >= MAX_ATTEMPTS:
                        store.mark_failed(sid, f"container {status}")
                        outcome = "failed"
                    else:
                        store.requeue(sid, f"container {status}; requeued")
                        outcome = "requeued"
                else:
                    store.note(sid, f"container {status or 'unknown'}; will re-check")
            else:
                media_id = _find_published(client, row)
                if media_id:
                    store.mark_published(sid, media_id, now)
                    outcome = "published (found on account)"
                else:
                    store.requeue(sid, "recovered: no container was recorded")
                    outcome = "requeued"
        except InstagramError as error:
            store.note(sid, f"recovery check failed: {error}")
        results.append({"id": sid, "outcome": outcome})
    return results


def run_due(now: datetime | None = None, *, store: Store | None = None, client: InstagramClient | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    store = store or get_store()
    client = client or _client()
    summary: dict = {"dry_run": client.dry_run, "published": [], "failed": [], "skipped": [], "recovered": []}
    summary["recovered"] = recover(store, client, now)

    local_used = store.published_since(now - timedelta(hours=24))
    if client.dry_run:
        remaining = POSTS_PER_24H - local_used
    else:
        try:
            limit = client.content_publishing_limit()
            remaining = min(limit["quota_total"], POSTS_PER_24H) - max(limit["quota_usage"], local_used)
        except InstagramError as error:
            log.warning("publishing limit check failed: %s", error)
            remaining = POSTS_PER_24H - local_used

    for row in store.due(now):
        sid = row["id"]
        if not row["media_url"]:
            store.note(sid, "needs media_url (set with --set-media ID URL)")
            summary["skipped"].append({"id": sid, "reason": "needs media_url"})
            continue
        if remaining <= 0:
            summary["skipped"].append({"id": sid, "reason": "100 posts / 24h limit reached"})
            continue
        if client.dry_run:
            summary["skipped"].append({"id": sid, "reason": "DRY-RUN: would publish; nothing sent"})
            continue
        if not store.claim(sid, now):
            continue
        container_created = False

        def saved(container_id: str, sid: int = sid) -> None:
            nonlocal container_created
            store.set_container(sid, container_id)
            container_created = True

        try:
            result = client.publish_container(row["media_type"], _urls(row), row["caption"], on_container=saved)
            store.mark_published(sid, result["media_id"], now)
            remaining -= 1
            summary["published"].append({"id": sid, "media_id": result["media_id"]})
        except ValueError as error:
            store.mark_failed(sid, str(error))
            summary["failed"].append({"id": sid, "error": str(error)})
        except InstagramError as error:
            if container_created:
                # Outcome unknown (e.g. timeout during media_publish): keep 'publishing' so recovery inspects it.
                store.note(sid, f"{error}; will inspect container before retry")
                summary["skipped"].append({"id": sid, "reason": "publish outcome unknown; will inspect"})
            elif row["attempts"] + 1 >= MAX_ATTEMPTS:
                store.mark_failed(sid, str(error))
                summary["failed"].append({"id": sid, "error": str(error)})
            else:
                store.requeue(sid, str(error))
                summary["skipped"].append({"id": sid, "reason": f"requeued: {error}"})
    return summary


def _urls(row: dict) -> str | list[str]:
    url = row["media_url"] or ""
    return [u.strip() for u in url.split(",") if u.strip()] if row["media_type"] == "CAROUSEL" else url


def _print_summary(summary: dict) -> None:
    label = "DRY-RUN " if summary["dry_run"] else ""
    print(f"{label}published={len(summary['published'])} failed={len(summary['failed'])} "
          f"skipped={len(summary['skipped'])} recovered={len(summary['recovered'])}")
    for key in ("published", "failed", "skipped", "recovered"):
        for item in summary[key]:
            print(f"  {key}: {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m crest_graph.scheduler", description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="publish due posts once and exit")
    group.add_argument("--loop", action="store_true", help="keep publishing due posts")
    group.add_argument("--list", action="store_true", help="show the queue")
    group.add_argument("--set-media", nargs=2, metavar=("ID", "URL"), help="attach a public media URL to a queued post")
    parser.add_argument("--interval", type=int, default=60, help="seconds between --loop runs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.list:
        for row in get_store().schedules():
            print(f"{row['id']:>4} {row['publish_at_utc']} {row['media_type']:<8} {row['status']:<10} "
                  f"{'media' if row['media_url'] else 'NO MEDIA'} {row['last_error'] or ''}")
        return 0
    if args.set_media:
        get_store().set_media_url(int(args.set_media[0]), args.set_media[1])
        print(f"media_url set for {args.set_media[0]}")
        return 0
    while True:
        _print_summary(run_due())
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
