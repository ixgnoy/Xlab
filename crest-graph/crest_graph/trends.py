"""Trend Analyzer: a LangGraph swarm of parallel web-research agents.

plan_swarm fans out with the Send API to one `researcher` task per lens; LangGraph runs the tasks of a
superstep concurrently and merges their findings through an `operator.add` reducer. `aggregate` then
validates, dedupes, scores and renders the report.

Trust rules (enforced in code, not only in prompts):
- An evidence item survives only if its URL is http(s) AND was returned by the search tool's
  url_citation annotations (or is a page we fetched ourselves). Model-written URLs are never trusted.
- A figure (views, likes, %, counts) survives only if the same number appears in the cited source excerpt.
- A trend with no surviving evidence is dropped.
- A failing researcher never fails the run; it is reported in "Method & limits".
"""
from __future__ import annotations

import json
import operator
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Annotated, Any, Callable, TypedDict
from urllib.parse import urlsplit, urlunsplit

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import config, prompts

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CREATIVE_CENTER_URL = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"
MAX_SWARM = 8


@dataclass(frozen=True)
class Lens:
    id: str
    name: str
    focus: str


LENSES: tuple[Lens, ...] = (
    Lens(
        "tiktok_creative_center",
        "TikTok Creative Center",
        "TikTok's own public trend data: TikTok Creative Center (ads.tiktok.com/business/creativecenter) trending "
        "hashtags, songs/sounds and creators, plus TikTok Newsroom / TikTok for Business posts and reputable "
        "write-ups that quote Creative Center figures. Platform: TikTok.",
    ),
    Lens(
        "instagram_reels",
        "Instagram Reels",
        "Instagram Reels trends: official Instagram/Meta creator sources (about.instagram.com, creators.instagram.com, "
        "the @creators account, Instagram's trend reports and 'trending audio' guidance) and reputable coverage of "
        "Reels formats, audio and features. Platform: Instagram.",
    ),
    Lens(
        "press",
        "News & marketing press",
        "News and marketing-trade coverage of short-form video trends published this week or month "
        "(e.g. Social Media Today, The Verge, TechCrunch, Business Insider, Later, Hootsuite, Sprout Social, Buffer "
        "trend roundups). Platforms: TikTok and Instagram Reels.",
    ),
    Lens(
        "search_interest",
        "Search-interest signals",
        "Search-interest signals: Google Trends explore/trending pages and articles that cite Google Trends or "
        "TikTok search data for rising short-video topics, sounds and challenges.",
    ),
    Lens(
        "niche",
        "Niche lens",
        "Trends specific to the user's niche from the brief (formats, sounds, hashtags and creator styles that are "
        "currently working in that niche on TikTok and Instagram Reels).",
    ),
)
SCRIPT_LENS_ORDER = ("tiktok_creative_center", "instagram_reels", "niche", "press", "search_interest")


# ---------------------------------------------------------------- search tool


@dataclass
class SearchResult:
    text: str
    citations: list[dict] = field(default_factory=list)  # {url, title, content}
    tokens: int = 0
    cost: float = 0.0


Searcher = Callable[..., SearchResult]
PageFetcher = Callable[[str, float], str]


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(config.get(name, str(default)) or default)
    except ValueError:
        value = default
    return max(low, min(high, value))


def openrouter_search(system: str, user: str, *, max_tokens: int, timeout: float) -> SearchResult:
    """One OpenRouter chat completion with the web plugin; citations come from url_citation annotations."""
    api_key = config.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    body = {
        "model": config.get("TREND_MODEL_ID", "deepseek/deepseek-v4.1-flash"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "plugins": [{"id": "web", "max_results": _int("TREND_SEARCH_RESULTS", 6, 1, 10)}],
        "max_tokens": max_tokens,
        "reasoning": {"effort": "low"},
        "usage": {"include": True},
    }
    response = httpx.post(
        OPENROUTER_URL,
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "X-Title": "PersonaLab Trend Analyzer"},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter web search returned HTTP {response.status_code}")
    data = response.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    citations = []
    for annotation in message.get("annotations") or []:
        if annotation.get("type") != "url_citation":
            continue
        cite = annotation.get("url_citation") or {}
        if cite.get("url"):
            citations.append({"url": cite["url"], "title": cite.get("title") or "", "content": cite.get("content") or ""})
    usage = data.get("usage") or {}
    return SearchResult(
        text=str(message.get("content") or ""),
        citations=citations,
        tokens=int(usage.get("total_tokens") or 0),
        cost=float(usage.get("cost") or 0.0),
    )


def fetch_page(url: str, timeout: float) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 PersonaLab trend probe"})
    response.raise_for_status()
    return response.text


def probe_creative_center(fetcher: PageFetcher, timeout: float) -> tuple[list[dict], str]:
    """Try the public Creative Center page directly. It is JS-rendered, so usually nothing is extractable."""
    try:
        html = fetcher(CREATIVE_CENTER_URL, timeout)
    except Exception as error:  # network/HTTP problems are notes, not failures
        return [], f"direct fetch of TikTok Creative Center failed ({type(error).__name__}); relied on web search"
    names = list(dict.fromkeys(re.findall(r'"hashtag_?[nN]ame"\s*:\s*"([^"]{1,60})"', html)))[:10]
    if not names:
        return [], "TikTok Creative Center page fetched but it is JavaScript-rendered; no trend data was extractable without a browser, so web search was used"
    page = {"url": CREATIVE_CENTER_URL, "title": "TikTok Creative Center - popular hashtags", "content": ", ".join(names)}
    return [page], f"TikTok Creative Center page fetched directly; {len(names)} hashtag names extracted from the page"


# ---------------------------------------------------------------- validation


def normalize_url(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    url = url.strip().rstrip(").,;]")
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or " " in url:
        return None
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, parts.query, ""))


def domain(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return host


NUMBER = re.compile(r"\d[\d,.]*\s?(?:%|[kKmMbB]\b)?")


def _numbers(text: str) -> list[str]:
    out = []
    for raw in NUMBER.findall(text or ""):
        value = raw.replace(",", "").replace(" ", "").rstrip(".").lower()
        if value and any(ch.isdigit() for ch in value):
            out.append(value)
    return out


def _supported(claim: str, source_text: str) -> bool:
    """Every number in the claim must appear in the cited source excerpt."""
    numbers = _numbers(claim)
    if not numbers:
        return True
    haystack = (source_text or "").replace(",", "").lower()
    haystack = re.sub(r"(\d)\s+(%|[kmb]\b)", r"\1\2", haystack)
    return all(n in haystack or n.rstrip("%kmb") in haystack for n in numbers)


def parse_json(text: str) -> Any:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
            try:  # tolerate trailing prose after the object
                return decoder.raw_decode(text[start:])[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("researcher did not return JSON")


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d{4})-(\d{2})(?:-(\d{2}))?", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1))
    except ValueError:
        return None


def validate_trends(raw: Any, citations: list[dict], lens: str) -> tuple[list[dict], dict]:
    """Keep only trends with evidence whose URL the search tool actually returned."""
    cited = {}
    for item in citations:
        key = normalize_url(item.get("url", ""))
        if key:
            cited[key] = item
    trends = raw.get("trends", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    stats = {"evidence_dropped": 0, "trends_dropped": 0, "figures_dropped": 0}
    kept = []
    for trend in trends:
        if not isinstance(trend, dict) or not str(trend.get("trend", "")).strip():
            continue
        evidence = []
        for item in trend.get("evidence") or []:
            if not isinstance(item, dict):
                stats["evidence_dropped"] += 1
                continue
            key = normalize_url(item.get("url", ""))
            source = cited.get(key) if key else None
            if source is None:
                stats["evidence_dropped"] += 1
                continue
            quote = str(item.get("quote_or_metric") or "").strip()
            if quote and not _supported(quote, source.get("content", "")):
                stats["figures_dropped"] += 1
                quote = ""
            evidence.append(
                {
                    "url": source["url"],
                    "title": str(item.get("title") or source.get("title") or domain(source["url"]))[:200],
                    "quote_or_metric": quote[:300],
                    "published_date": str(item.get("published_date") or "")[:40],
                }
            )
        if not evidence:
            stats["trends_dropped"] += 1
            continue
        source_text = " ".join(cited[normalize_url(e["url"])].get("content", "") for e in evidence)
        signals = []
        raw_signals = trend.get("engagement_signals") or []
        if isinstance(raw_signals, (str, dict)):
            raw_signals = [raw_signals]
        for signal in raw_signals:
            text = json.dumps(signal) if isinstance(signal, dict) else str(signal)
            if not _numbers(text):
                continue
            if _supported(text, source_text):
                signals.append(text[:200])
            else:
                stats["figures_dropped"] += 1
        confidence = str(trend.get("confidence") or "low").lower()
        kept.append(
            {
                "trend": str(trend["trend"]).strip()[:120],
                "platform": str(trend.get("platform") or "unspecified").strip()[:40],
                "format": str(trend.get("format") or trend.get("format/sound/hashtag") or "").strip()[:160],
                "why_hot": str(trend.get("why_hot") or "").strip()[:300],
                "evidence": evidence,
                "engagement_signals": signals,
                "confidence": confidence if confidence in ("high", "medium", "low") else "low",
                "lenses": [lens],
            }
        )
    return kept, stats


# ---------------------------------------------------------------- aggregation


def _key(name: str) -> set[str]:
    stop = {"the", "a", "an", "trend", "trends", "on", "of", "and", "tiktok", "reels", "instagram", "challenge", "video", "videos"}
    words = re.findall(r"[a-z0-9]+", name.lower().replace("#", " "))
    return {w for w in words if w not in stop} or set(words)


def merge(trends: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for trend in trends:
        key = _key(trend["trend"])
        target = None
        for existing in merged:
            other = _key(existing["trend"])
            if key and other and len(key & other) / len(key | other) >= 0.6:
                target = existing
                break
        if target is None:
            merged.append({**trend, "evidence": list(trend["evidence"]), "lenses": list(trend["lenses"]), "platforms": {trend["platform"].lower()}})
            continue
        seen = {normalize_url(e["url"]) for e in target["evidence"]}
        target["evidence"] += [e for e in trend["evidence"] if normalize_url(e["url"]) not in seen]
        target["engagement_signals"] = list(dict.fromkeys(target["engagement_signals"] + trend["engagement_signals"]))
        target["lenses"] = list(dict.fromkeys(target["lenses"] + trend["lenses"]))
        target["platforms"].add(trend["platform"].lower())
        target["why_hot"] = target["why_hot"] or trend["why_hot"]
        target["format"] = target["format"] or trend["format"]
        order = ("low", "medium", "high")
        target["confidence"] = max(target["confidence"], trend["confidence"], key=order.index)
    return merged


def score(trend: dict, today: date) -> float:
    sources = len({domain(e["url"]) for e in trend["evidence"]})
    dates = [d for d in (_date(e.get("published_date")) for e in trend["evidence"]) if d]
    newest = max(dates) if dates else None
    age = (today - newest).days if newest else None
    recency = 2.0 if age is not None and age <= 14 else 1.0 if age is not None and age <= 45 else 0.0
    platforms = {p for p in trend.get("platforms", {trend["platform"].lower()}) if p != "unspecified"}
    joined = " ".join(platforms)
    cross = 1.5 if ("tiktok" in joined and "instagram" in joined) or "both" in joined or "cross" in joined else 0.0
    engagement = min(len(trend["engagement_signals"]), 3) * 0.75
    confidence = {"high": 1.5, "medium": 0.75, "low": 0.0}[trend["confidence"]]
    return round(sources * 2.0 + recency + cross + engagement + confidence + 0.5 * (len(trend["lenses"]) - 1), 2)


def _cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def render(trends: list[dict], findings: list[dict], *, today: date, brief: str, top_n: int = 8) -> str:
    total_sources = len({normalize_url(e["url"]) for t in trends for e in t["evidence"]})
    lines = ["## Hot trends right now", ""]
    if not trends:
        lines.append("No trend survived evidence validation (every candidate lacked a URL returned by the search tool). See Method & limits.")
    else:
        lines += ["| Rank | Trend | Platform | Why it's hot | Evidence | Confidence | Score |", "|---|---|---|---|---|---|---|"]
        for rank, trend in enumerate(trends[:top_n], 1):
            links = ", ".join(f"[{i}]({e['url']})" for i, e in enumerate(trend["evidence"][:4], 1))
            platform = "/".join(sorted(trend["platforms"])) if trend.get("platforms") else trend["platform"]
            what = trend["trend"] + (f" ({trend['format']})" if trend["format"] else "")
            lines.append(f"| {rank} | {_cell(what)} | {_cell(platform)} | {_cell(trend['why_hot'] or '-')} | {links} | {trend['confidence']} | {trend['score']} |")
    lines += ["", "## Evidence log", ""]
    for rank, trend in enumerate(trends[:top_n], 1):
        lines.append(f"**{rank}. {trend['trend']}**")
        for e in trend["evidence"]:
            detail = f" - \"{_cell(e['quote_or_metric']).strip(chr(34))}\"" if e["quote_or_metric"] else ""
            when = f" ({e['published_date']})" if e["published_date"] else ""
            lines.append(f"- [{_cell(e['title'])}]({e['url']}){when}{detail}")
        for signal in trend["engagement_signals"]:
            lines.append(f"- Engagement signal stated by source: {_cell(signal)}")
        lines.append("")
    lines += ["## How to use this trend", ""]
    for rank, trend in enumerate(trends[:3], 1):
        lines.append(f"### {rank}. {trend['trend']}")
        lines.append(f"- Hook: open on the trend's signature moment ({trend['format'] or 'its format'}) in the first 3 seconds, framed for your niche.")
        lines.append("- Fit: keep the persona's voice; adapt the format rather than copying another creator's content.")
        lines.append(f"- Reference: {trend['evidence'][0]['url']}")
        lines.append("- Sounds: pick audio from the in-app trending/commercial library; licensing differs for business accounts.")
        lines.append("")
    failed = [f for f in findings if f.get("error")]
    tokens = sum(f.get("tokens", 0) for f in findings)
    cost = sum(f.get("cost", 0.0) for f in findings)
    dropped = sum(f.get("stats", {}).get("evidence_dropped", 0) for f in findings)
    figures = sum(f.get("stats", {}).get("figures_dropped", 0) for f in findings)
    lines += [
        "## Method & limits",
        "",
        f"- Date of research: {today.isoformat()}. Brief: {_cell(brief)[:200] or '(none)'}",
        f"- Swarm: {len(findings)} parallel research agents ({', '.join(f['lens_name'] for f in findings)}), each using live web search; "
        f"{len(failed)} failed. {total_sources} distinct cited sources.",
        "- No logged-in feed scrolling, no account access and no private analytics were used. Only public web pages returned by the search tool.",
        "- Figures (views, likes, shares, post counts, % growth) appear only where the cited source states them; numbers not found in the source excerpt were removed.",
        f"- Validation removed {dropped} evidence item(s) without a search-returned http(s) URL and {figures} unverified figure(s); trends left with no evidence were dropped.",
        "- Score = 2 x independent source domains + recency (<=14 days: 2, <=45 days: 1) + 1.5 if on both TikTok and Instagram + 0.75 per stated engagement figure (max 3) + confidence + 0.5 per extra agreeing lens.",
        f"- Usage: {tokens} tokens, about ${cost:.4f} reported by OpenRouter.",
    ]
    for finding in findings:
        if finding.get("note"):
            lines.append(f"- {finding['lens_name']}: {finding['note']}")
        if finding.get("error"):
            lines.append(f"- {finding['lens_name']} researcher failed: {finding['error']}; continued with the others.")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- graph


class TrendState(TypedDict, total=False):
    input: str
    stage: str
    findings: Annotated[list[dict], operator.add]
    trends: list[dict]
    trend_report: str


class ResearchTask(TypedDict):
    lens: dict
    brief: str
    max_tokens: int
    timeout: float


def swarm_size(stage: str | None) -> int:
    if stage == "scripts":
        return _int("TREND_SCRIPTS_SWARM_SIZE", 3, 1, MAX_SWARM)
    return _int("TREND_SWARM_SIZE", 5, 1, MAX_SWARM)


def pick_lenses(stage: str | None, size: int) -> list[Lens]:
    by_id = {lens.id: lens for lens in LENSES}
    order = [by_id[i] for i in SCRIPT_LENS_ORDER] if stage == "scripts" else list(LENSES)
    picked = order[: min(size, len(order))]
    extra = size - len(picked)  # more agents than lenses: repeat the niche lens with a different angle
    picked += [Lens(f"niche_{i + 2}", f"Niche lens {i + 2}", by_id["niche"].focus + f" Angle {i + 2}: sub-niches and adjacent audiences.") for i in range(max(0, extra))]
    return picked


def _brief(state: TrendState) -> str:
    return re.sub(r"\[stage:[a-z]+\]", "", state.get("input", ""), flags=re.IGNORECASE).strip()


def build_trend_graph(searcher: Searcher | None = None, page_fetcher: PageFetcher | None = None):
    search = searcher or openrouter_search
    fetch = page_fetcher or fetch_page

    def plan_swarm(state: TrendState) -> list[Send]:
        lenses = pick_lenses(state.get("stage"), swarm_size(state.get("stage")))
        budget = _int("TREND_TOKEN_BUDGET", 60000, 2000, 500000)
        per_agent = max(800, min(_int("TREND_MAX_TOKENS", 3000, 500, 16000), budget // max(1, len(lenses)) // 2))
        timeout = float(_int("TREND_TIMEOUT_S", 120, 10, 600))
        return [
            Send("researcher", {"lens": lens.__dict__, "brief": _brief(state), "max_tokens": per_agent, "timeout": timeout})
            for lens in lenses
        ]

    def researcher(task: ResearchTask) -> TrendState:
        lens = task["lens"]
        finding: dict = {"lens": lens["id"], "lens_name": lens["name"], "trends": [], "tokens": 0, "cost": 0.0}
        started = time.monotonic()
        try:
            extra_pages: list[dict] = []
            if lens["id"] == "tiktok_creative_center":
                extra_pages, finding["note"] = probe_creative_center(fetch, min(20.0, task["timeout"]))
            today = datetime.now(timezone.utc).date().isoformat()
            user = prompts.TREND_RESEARCHER_TASK.format(today=today, lens=lens["name"], focus=lens["focus"], brief=task["brief"] or "(no niche given: general short-form video)")
            if extra_pages:
                user += "\n\nDirectly fetched page data (you may cite this URL): " + json.dumps(extra_pages)[:2000]
            result = search(prompts.TREND_RESEARCHER, user, max_tokens=task["max_tokens"], timeout=task["timeout"])
            finding["tokens"], finding["cost"] = result.tokens, result.cost
            try:
                raw = parse_json(result.text)
            except ValueError:  # one retry, still inside the per-agent token cap
                retry = search(prompts.TREND_RESEARCHER, user + "\n\nReturn ONLY the JSON object.", max_tokens=task["max_tokens"], timeout=task["timeout"])
                finding["tokens"] += retry.tokens
                finding["cost"] += retry.cost
                result = retry
                raw = parse_json(result.text)
            trends, stats = validate_trends(raw, [*result.citations, *extra_pages], lens["id"])
            finding.update(trends=trends, stats=stats, citations=len(result.citations))
        except Exception as error:  # isolate: one failing researcher must not fail the swarm
            finding["error"] = f"{type(error).__name__}: {str(error)[:160]}"
        finding["seconds"] = round(time.monotonic() - started, 1)
        return {"findings": [finding]}

    def aggregate(state: TrendState) -> TrendState:
        findings = sorted(state.get("findings", []), key=lambda f: f["lens"])
        today = datetime.now(timezone.utc).date()
        trends = merge([t for f in findings for t in f.get("trends", [])])
        for trend in trends:
            trend["score"] = score(trend, today)
        trends.sort(key=lambda t: t["score"], reverse=True)
        report = render(trends, findings, today=today, brief=_brief(state))
        for trend in trends:
            trend["platforms"] = sorted(trend.get("platforms", []))
        return {"trends": trends, "trend_report": report}

    graph = StateGraph(TrendState)
    graph.add_node("researcher", researcher)
    graph.add_node("aggregate", aggregate)
    graph.add_conditional_edges(START, plan_swarm, ["researcher"])
    graph.add_edge("researcher", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()
