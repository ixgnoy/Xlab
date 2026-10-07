"""Instagram Platform API client (Instagram API with Instagram Login, host graph.instagram.com).

Verified against developers.facebook.com/docs/instagram-platform (v25.0 examples):
- POST /{ig-id}/media                 create container (image_url | video_url+media_type=REELS | CAROUSEL+children)
- GET  /{container-id}?fields=status_code   EXPIRED | ERROR | FINISHED | IN_PROGRESS | PUBLISHED
- POST /{ig-id}/media_publish         creation_id -> {"id": media id}
- GET  /{ig-id}/content_publishing_limit?fields=quota_usage,config   (100 API posts / rolling 24h)
- GET  /{ig-id}/media, GET /{media-id}/insights?metric=...
- GET  /{media-id}/comments, POST /{comment-id}/replies {"message"}
- GET  /{ig-id}/conversations?platform=instagram, GET /{conversation-id}?fields=messages{...}
- POST /{ig-id}/messages {"recipient": {"id"}, "message": {"text"}}  (24h window after the user's last message)

DRY-RUN: when IG_ACCESS_TOKEN or IG_USER_ID is missing, every method returns realistic sample data marked
"dry_run": True / "DRY-RUN" and never performs, or claims, a publish or send.
The access token is sent in the Authorization header (IG_TOKEN_IN_QUERY=1 switches to an access_token parameter)
and is redacted from every error message and repr.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import httpx

from . import config

log = logging.getLogger("crest_graph.instagram")

GRAPH_HOST = "https://graph.instagram.com"
DEFAULT_VERSION = "v25.0"
POSTS_PER_24H = 100
DM_WINDOW = timedelta(hours=24)
AUTOMATION_DISCLOSURE = "[Automated reply - you're chatting with an AI assistant for this account.] "
MEDIA_TYPES = ("REELS", "IMAGE", "CAROUSEL")
REELS_METRICS = ("views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time")
# The FEED metric list in Meta's docs omits views/total_interactions; requesting an unsupported metric fails the whole call.
FEED_METRICS = ("reach", "likes", "comments", "shares", "saved")
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
DRY = "DRY-RUN"


class InstagramError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class MessagingWindowClosed(InstagramError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":  # Graph style +0000
        text = text[:-2] + ":" + text[-2:]
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def with_disclosure(text: str) -> str:
    return text if text.startswith(AUTOMATION_DISCLOSURE.strip()[:12]) else AUTOMATION_DISCLOSURE + text


def check_window(last_inbound_at: Any, now: datetime | None = None) -> None:
    """Raise MessagingWindowClosed unless the user messaged us within the last 24 hours."""
    last = _parse_time(last_inbound_at)
    now = now or _now()
    if last is None:
        raise MessagingWindowClosed("Instagram only allows replies after the user messages first")
    if now - last > DM_WINDOW:
        raise MessagingWindowClosed("The 24-hour messaging window has closed; a human must reply in the Instagram app")


class InstagramClient:
    def __init__(
        self,
        access_token: str | None = None,
        user_id: str | None = None,
        *,
        version: str = DEFAULT_VERSION,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 5.0,
        max_wait: float = 300.0,
        token_in_query: bool = False,
    ):
        self._token = access_token or None
        self.user_id = user_id or None
        self.version = version
        self._sleep = sleep
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        # Fallback for hosts that reject the Bearer header: send access_token as a parameter instead.
        # httpx logs request URLs at INFO, so its logger is raised to WARNING to keep the token out of logs.
        self.token_in_query = token_in_query
        if token_in_query:
            logging.getLogger("httpx").setLevel(logging.WARNING)
        self._http = httpx.Client(base_url=f"{GRAPH_HOST}/{version}", timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, **kwargs) -> "InstagramClient":
        return cls(
            config.get("IG_ACCESS_TOKEN"),
            config.get("IG_USER_ID"),
            version=config.get("IG_API_VERSION", DEFAULT_VERSION),
            timeout=float(config.get("IG_TIMEOUT_S", "20")),
            token_in_query=config.get("IG_TOKEN_IN_QUERY", "0") == "1",
            **kwargs,
        )

    @property
    def dry_run(self) -> bool:
        return not (self._token and self.user_id)

    def __repr__(self) -> str:  # never expose the token
        return f"InstagramClient(user_id={self.user_id!r}, dry_run={self.dry_run})"

    # ---- HTTP -------------------------------------------------------------------------------------------
    def _redact(self, text: str) -> str:
        return text.replace(self._token, "[redacted]") if self._token else text

    def _request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
                 data: dict | None = None) -> dict:
        if self.dry_run:
            raise InstagramError("DRY-RUN: no Instagram credentials; refusing to call the API")
        headers = {}
        if self.token_in_query:
            params = {**(params or {}), "access_token": self._token}
        else:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._http.request(method, path, params=params, json=json, data=data, headers=headers)
        except httpx.HTTPError as error:
            raise InstagramError(self._redact(f"Instagram request failed: {type(error).__name__}")) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            message = self._redact(str(err.get("message") or f"HTTP {response.status_code}"))
            log.warning("Instagram API error status=%s code=%s", response.status_code, err.get("code"))
            raise InstagramError(f"Instagram API error: {message}", response.status_code, err.get("code"))
        return body if isinstance(body, dict) else {"data": body}

    # ---- Publishing -------------------------------------------------------------------------------------
    def create_container(self, media_type: str, url: str | None = None, caption: str | None = None, *,
                         children: Iterable[str] | None = None, is_carousel_item: bool = False,
                         share_to_feed: bool = True, cover_url: str | None = None) -> str:
        media_type = media_type.upper()
        payload: dict[str, Any] = {}
        if media_type == "IMAGE":
            payload["image_url"] = url
        elif media_type in ("REELS", "VIDEO"):
            payload.update(media_type=media_type, video_url=url)
            if media_type == "REELS":
                payload["share_to_feed"] = "true" if share_to_feed else "false"
            if cover_url:
                payload["cover_url"] = cover_url
        elif media_type == "CAROUSEL":
            payload.update(media_type="CAROUSEL", children=",".join(children or []))
        else:
            raise ValueError(f"Unsupported media_type {media_type}")
        if is_carousel_item:
            payload["is_carousel_item"] = "true"
        elif caption:
            payload["caption"] = caption
        if self.dry_run:
            return f"{DRY}-container-{abs(hash((media_type, url, caption))) % 10**10}"
        return str(self._request("POST", f"/{self.user_id}/media", data=payload)["id"])

    def container_status(self, container_id: str) -> str:
        if self.dry_run:
            return "FINISHED"
        return str(self._request("GET", f"/{container_id}", params={"fields": "status_code"}).get("status_code", ""))

    def wait_for_container(self, container_id: str) -> str:
        waited = 0.0
        while True:
            status = self.container_status(container_id)
            if status in ("FINISHED", "PUBLISHED"):
                return status
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Container {container_id} status {status}")
            if waited >= self.max_wait:
                raise InstagramError(f"Container {container_id} still {status or 'unknown'} after {int(waited)}s")
            self._sleep(self.poll_interval)
            waited += self.poll_interval

    def media_publish(self, creation_id: str) -> str:
        if self.dry_run:
            raise InstagramError("DRY-RUN: media_publish is never called without credentials")
        return str(self._request("POST", f"/{self.user_id}/media_publish", data={"creation_id": creation_id})["id"])

    def publish_container(self, media_type: str, url: str | list[str] | None, caption: str | None = None, *,
                          on_container: Callable[[str], None] | None = None) -> dict:
        """Create container(s) -> poll status_code until FINISHED -> media_publish.

        `on_container` is called with the container id before publishing so callers can persist it
        (needed for idempotent recovery after a crash).
        """
        media_type = media_type.upper()
        if media_type not in MEDIA_TYPES:
            raise ValueError(f"media_type must be one of {', '.join(MEDIA_TYPES)}")
        urls = [u for u in (url if isinstance(url, list) else [url]) if u]
        if not urls:
            raise ValueError("A public media URL is required")
        if media_type == "CAROUSEL":
            if not 2 <= len(urls) <= 10:
                raise ValueError("A carousel needs 2-10 media URLs")
            kids = [
                self.create_container("VIDEO" if u.lower().split("?")[0].endswith(VIDEO_SUFFIXES) else "IMAGE", u,
                                      is_carousel_item=True)
                for u in urls
            ]
            for kid in kids:
                self.wait_for_container(kid)
            container = self.create_container("CAROUSEL", caption=caption, children=kids)
        else:
            container = self.create_container(media_type, urls[0], caption)
        if on_container:
            on_container(container)
        if self.dry_run:
            return {"dry_run": True, "status": "dry_run", "container_id": container, "media_id": None,
                    "note": f"{DRY}: container simulated; nothing was published"}
        status = self.wait_for_container(container)
        media_id = self.media_publish(container) if status == "FINISHED" else None
        return {"dry_run": False, "status": "published", "container_id": container, "media_id": media_id}

    def content_publishing_limit(self) -> dict:
        if self.dry_run:
            return {"dry_run": True, "quota_usage": 0, "quota_total": POSTS_PER_24H, "quota_duration": 86400}
        body = self._request("GET", f"/{self.user_id}/content_publishing_limit", params={"fields": "quota_usage,config"})
        row = (body.get("data") or [{}])[0]
        cfg = row.get("config") or {}
        return {"dry_run": False, "quota_usage": int(row.get("quota_usage", 0)),
                "quota_total": int(cfg.get("quota_total", POSTS_PER_24H)), "quota_duration": int(cfg.get("quota_duration", 86400))}

    # ---- Reading media and insights ---------------------------------------------------------------------
    def list_media(self, limit: int = 10) -> list[dict]:
        if self.dry_run:
            base = _now()
            return [
                {"id": f"{DRY}-media-{i}", "caption": f"{DRY} sample post {i}", "media_type": "VIDEO",
                 "media_product_type": "REELS", "permalink": None,
                 "timestamp": (base - timedelta(days=i)).isoformat(), "dry_run": True}
                for i in range(1, min(limit, 3) + 1)
            ]
        fields = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
        return list(self._request("GET", f"/{self.user_id}/media", params={"fields": fields, "limit": limit}).get("data", []))

    def media_insights(self, media_id: str, product_type: str = "REELS") -> dict:
        metrics = REELS_METRICS if product_type.upper() == "REELS" else FEED_METRICS
        if self.dry_run:
            sample = {"views": 1200, "reach": 900, "likes": 80, "comments": 6, "shares": 9, "saved": 14,
                      "total_interactions": 109, "ig_reels_avg_watch_time": 4200}
            return {"dry_run": True, "label": DRY, **{m: sample[m] for m in metrics}}
        body = self._request("GET", f"/{media_id}/insights", params={"metric": ",".join(metrics)})
        out: dict[str, Any] = {"dry_run": False}
        for row in body.get("data", []):
            values = row.get("values") or [{}]
            out[row.get("name")] = values[0].get("value", row.get("total_value", {}).get("value"))
        return out

    # ---- Comments ---------------------------------------------------------------------------------------
    def list_comments(self, media_id: str) -> list[dict]:
        if self.dry_run:
            return [{"id": f"{DRY}-comment-1", "text": f"{DRY} sample comment", "username": "sample_user",
                     "timestamp": _now().isoformat(), "dry_run": True}]
        params = {"fields": "id,text,timestamp,username,from"}
        return list(self._request("GET", f"/{media_id}/comments", params=params).get("data", []))

    def reply_comment(self, comment_id: str, message: str) -> dict:
        if self.dry_run:
            return {"dry_run": True, "sent": False, "id": None, "note": f"{DRY}: reply not sent"}
        body = self._request("POST", f"/{comment_id}/replies", json={"message": message})
        return {"dry_run": False, "sent": True, "id": body.get("id")}

    # ---- Messaging --------------------------------------------------------------------------------------
    def list_conversations(self) -> list[dict]:
        if self.dry_run:
            return [{"id": f"{DRY}-conversation-1", "updated_time": _now().isoformat(), "dry_run": True}]
        return list(self._request("GET", f"/{self.user_id}/conversations", params={"platform": "instagram"}).get("data", []))

    def list_messages(self, conversation_id: str) -> list[dict]:
        if self.dry_run:
            return [{"id": f"{DRY}-message-1", "created_time": _now().isoformat(),
                     "from": {"id": f"{DRY}-igsid", "username": "sample_user"}, "message": f"{DRY} sample DM",
                     "dry_run": True}]
        params = {"fields": "messages{id,created_time,from,to,message}"}
        return list((self._request("GET", f"/{conversation_id}", params=params).get("messages") or {}).get("data", []))

    def send_dm(self, recipient_id: str, text: str, *, last_inbound_at: Any, first_dm: bool,
                now: datetime | None = None) -> dict:
        """Send a DM only inside the 24h window; the first automated DM in a thread carries a disclosure."""
        check_window(last_inbound_at, now)
        body_text = with_disclosure(text) if first_dm else text
        if self.dry_run:
            return {"dry_run": True, "sent": False, "message_id": None, "text": body_text, "note": f"{DRY}: DM not sent"}
        body = self._request("POST", f"/{self.user_id}/messages",
                             json={"recipient": {"id": recipient_id}, "message": {"text": body_text}})
        return {"dry_run": False, "sent": True, "message_id": body.get("message_id"), "text": body_text}
