import json
import threading
from datetime import date

import pytest

from crest_graph import trends
from crest_graph.graph import build_graph, parse_stage
from crest_graph.trends import SearchResult, normalize_url, validate_trends

from test_graph import fake

REAL = "https://tokconnect.com/trends/weekly/2026-10-05/"
REAL2 = "https://www.socialmediatoday.com/news/instagram-reels-trends-october-2026/"
FAKE = "https://made-up.example.com/viral-stats"


def no_page(url, timeout):
    raise OSError("offline in tests")


def payload(*items):
    return json.dumps({"trends": list(items)})


def trend(name, url, platform="TikTok", quote="kpop dances up 447%", signals=("up 447% to 564,143 searches",), confidence="medium"):
    return {
        "trend": name,
        "platform": platform,
        "format": "dance challenge",
        "why_hot": "Search interest jumped this week",
        "evidence": [{"url": url, "title": "Weekly report", "quote_or_metric": quote, "published_date": "2026-10-05"}],
        "engagement_signals": list(signals),
        "confidence": confidence,
    }


CITES = [
    {"url": REAL, "title": "TikTok Trends October 2026", "content": "kpop tiktok dances, up 447% to 564,143 searches"},
    {"url": REAL2, "title": "Reels trends", "content": "Instagram says Reels with trending audio are rising; kpop dance remixes lead"},
]


def searcher_returning(text, citations=CITES, tokens=100, cost=0.001):
    calls = []

    def search(system, user, *, max_tokens, timeout):
        calls.append(user)
        return SearchResult(text=text, citations=citations, tokens=tokens, cost=cost)

    search.calls = calls
    return search


@pytest.fixture(autouse=True)
def swarm_env(monkeypatch):
    monkeypatch.setenv("TREND_SWARM_SIZE", "5")
    monkeypatch.setenv("TREND_SCRIPTS_SWARM_SIZE", "3")


def test_stage_tags_for_new_stages():
    assert parse_stage("[stage:trends] fitness") == "trends"
    assert parse_stage("[stage:Scripts] x") == "scripts"


def test_url_validation_rejects_non_http_and_normalizes():
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("ftp://x.com/a") is None
    assert normalize_url("not a url") is None
    assert normalize_url("https://WWW.Example.com/a/") == normalize_url("https://example.com/a")


def test_fabricated_urls_and_unsupported_figures_are_dropped():
    raw = {
        "trends": [
            trend("K-pop dances", REAL),
            trend("Invented trend", FAKE),  # URL not returned by the search tool -> whole trend dropped
            trend("Bad scheme", "javascript:alert(1)"),
            trend("K-pop remix", REAL2, quote="views up 900%", signals=("2.1M views",)),  # numbers not in source
        ]
    }
    kept, stats = validate_trends(raw, CITES, "press")
    names = [t["trend"] for t in kept]
    assert names == ["K-pop dances", "K-pop remix"]
    assert stats["trends_dropped"] == 2 and stats["evidence_dropped"] == 2
    assert kept[0]["engagement_signals"] == ["up 447% to 564,143 searches"]
    assert kept[1]["engagement_signals"] == [] and kept[1]["evidence"][0]["quote_or_metric"] == ""
    assert stats["figures_dropped"] == 2


def test_swarm_fans_out_in_parallel_with_distinct_lenses():
    barrier = threading.Barrier(5, timeout=10)  # passes only if all 5 researchers run concurrently
    seen = []

    def search(system, user, *, max_tokens, timeout):
        seen.append(user)
        barrier.wait()
        return SearchResult(text=payload(trend("K-pop dances", REAL)), citations=CITES, tokens=50, cost=0.002)

    out = build_graph(fake(), trend_searcher=search, page_fetcher=no_page).invoke({"input": "[stage:trends] fitness, US, last 7 days"})
    assert out["stage"] == "trends" and len(seen) == 5
    lenses = {line for user in seen for line in user.splitlines() if line.startswith("Lens:")}
    assert len(lenses) == 5
    assert all("fitness, US, last 7 days" in user for user in seen)
    report = out["output"]
    assert report.startswith("# PersonaLab - Trend Analyzer")
    for heading in ("## Hot trends right now", "## Evidence log", "## How to use this trend", "## Method & limits"):
        assert heading in report
    assert REAL in report and FAKE not in report
    assert "No logged-in feed scrolling" in report and "Date of research" in report
    assert len(out["trends"]) == 1 and len(out["trends"][0]["lenses"]) == 5  # deduped across lenses
    assert "$0.0100" in report  # cost summed across the swarm


def test_failed_researcher_is_isolated_and_reported():
    calls = {"n": 0}
    lock = threading.Lock()

    def search(system, user, *, max_tokens, timeout):
        with lock:
            calls["n"] += 1
        if "Lens: Instagram Reels" in user:
            raise TimeoutError("read timed out")
        if "Lens: News" in user:
            return SearchResult(text="sorry, no JSON here", citations=CITES)
        return SearchResult(text=payload(trend("K-pop dances", REAL)), citations=CITES)

    out = build_graph(fake(), trend_searcher=search, page_fetcher=no_page).invoke({"input": "[stage:trends] beauty"})
    assert calls["n"] == 6  # 5 researchers + one JSON retry for the News lens
    report = out["output"]
    assert "Instagram Reels researcher failed: TimeoutError" in report
    assert "News & marketing press researcher failed: ValueError" in report
    assert "2 failed" in report and REAL in report


def test_all_evidence_fabricated_yields_honest_empty_report():
    search = searcher_returning(payload(trend("Ghost trend", FAKE)))
    out = build_graph(fake(), trend_searcher=search, page_fetcher=no_page).invoke({"input": "[stage:trends] x"})
    assert out["trends"] == []
    assert "No trend survived evidence validation" in out["output"] and FAKE not in out["output"]


def test_swarm_size_is_capped(monkeypatch):
    monkeypatch.setenv("TREND_SWARM_SIZE", "50")
    search = searcher_returning(payload())
    build_graph(fake(), trend_searcher=search, page_fetcher=no_page).invoke({"input": "[stage:trends] x"})
    assert len(search.calls) == trends.MAX_SWARM


def test_creative_center_probe_extracts_only_real_page_data():
    html = '<script>{"hashtagName":"fallvibes"},{"hashtag_name":"gymtok"}</script>'
    pages, note = trends.probe_creative_center(lambda url, timeout: html, 5)
    assert pages[0]["url"] == trends.CREATIVE_CENTER_URL and "fallvibes" in pages[0]["content"]
    assert "2 hashtag names" in note
    pages, note = trends.probe_creative_center(lambda url, timeout: "<div id=root></div>", 5)
    assert pages == [] and "JavaScript-rendered" in note


def test_scoring_rewards_sources_recency_and_cross_platform():
    today = date(2026, 10, 7)
    one = trends.merge([{**validate_trends({"trends": [trend("A", REAL)]}, CITES, "x")[0][0]}])[0]
    both = trends.merge(
        [
            validate_trends({"trends": [trend("A", REAL)]}, CITES, "x")[0][0],
            validate_trends({"trends": [trend("A", REAL2, platform="Instagram", quote="", signals=())]}, CITES, "y")[0][0],
        ]
    )[0]
    assert trends.score(both, today) > trends.score(one, today)


def test_scripts_stage_runs_smaller_swarm_then_script_writer():
    search = searcher_returning(payload(trend("K-pop dances", REAL)))
    model = fake("## Script 1: Gym K-pop\nTrend used: K-pop dances " + REAL)
    out = build_graph(model, trend_searcher=search, page_fetcher=no_page).invoke(
        {"input": "[stage:scripts] Niche: fitness\nAudience: busy moms\nPlatform: TikTok and Reels\nScripts: 3"}
    )
    assert out["stage"] == "scripts" and len(search.calls) == 3
    lenses = [line for user in search.calls for line in user.splitlines() if line.startswith("Lens:")]
    assert sorted(lenses) == ["Lens: Instagram Reels", "Lens: Niche lens", "Lens: TikTok Creative Center"]
    assert len(model.calls) == 1
    writer_input = model.calls[0][1].content
    assert "busy moms" in writer_input and REAL in writer_input and "## Hot trends right now" in writer_input
    assert out["output"].startswith("# PersonaLab - Trend-based Script Writer")
    assert "## Script 1" in out["output"] and "# Trend analysis used" in out["output"]


def test_supervisor_can_route_untagged_requests_to_new_stages():
    search = searcher_returning(payload())
    out = build_graph(fake("trends"), trend_searcher=search, page_fetcher=no_page).invoke({"input": "what's hot on tiktok this week?"})
    assert out["stage"] == "trends"
    out = build_graph(fake("scripts", "## Script 1"), trend_searcher=search, page_fetcher=no_page).invoke({"input": "write me reel scripts"})
    assert out["stage"] == "scripts"


def test_researcher_retries_once_when_json_is_missing(monkeypatch):
    monkeypatch.setenv("TREND_SWARM_SIZE", "1")
    replies = iter(["Here are trends: none in JSON", payload(trend("K-pop dances", REAL)) + "\nHope this helps!"])

    def search(system, user, *, max_tokens, timeout):
        return SearchResult(text=next(replies), citations=CITES, tokens=10)

    out = build_graph(fake(), trend_searcher=search, page_fetcher=no_page).invoke({"input": "[stage:trends] x"})
    assert [t["trend"] for t in out["trends"]] == ["K-pop dances"] and "0 failed" in out["output"]
    assert "20 tokens" in out["output"]


def test_schedule_stage_still_works():
    out = build_graph(fake("## Posting calendar")).invoke({"input": "[stage:schedule] plan"})
    assert out["output"].startswith("# PersonaLab - Schedule")
