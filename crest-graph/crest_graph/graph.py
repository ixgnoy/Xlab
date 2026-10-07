"""PersonaLab supervisor graph: routes a request to the Create, Schedule, Engage, Analyze, Trends or Scripts agents.

Create: trend_swarm (small; skipped when the brief already carries a trend report or script) -> persona_agent ->
content_agent (one cited trend -> one timed reel / video-ad script) -> media_agent (persona reference portrait +
one keyframe per scene) -> video_agent (reel.mp4: AI image-to-video clips or local ffmpeg assembly) -> finalize.
Instagram and approval tools attach to these same nodes in later phases.
"""
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import config, ig_workflows, media, prompts, trends, video

Stage = Literal["create", "schedule", "engage", "analyze", "trends", "scripts"]
STAGES: tuple[Stage, ...] = ("create", "schedule", "engage", "analyze", "trends", "scripts")
STAGE_TAG = re.compile(r"\[stage:(create|schedule|engage|analyze|trends|scripts)\]", re.IGNORECASE)
TITLES = {
    "create": "Create",
    "schedule": "Schedule",
    "engage": "Engage",
    "analyze": "Analyze",
    "trends": "Trend Analyzer",
    "scripts": "Trend-based Script Writer",
}
OFF = ("off", "0", "false", "no", "disabled")


class CrestState(TypedDict, total=False):
    input: str
    stage: Stage
    persona: str
    sections: list[str]
    output: str
    trends: list[dict]  # written by the trend swarm subgraph
    trend_report: str
    trend_cost: float
    content: str
    media_run: str
    media_files: list[dict]  # {"path", "label", "scene", "cost"}
    media_cost: float


def parse_stage(text: str) -> Stage | None:
    match = STAGE_TAG.search(text)
    return match.group(1).lower() if match else None  # type: ignore[return-value]


def strip_stage_tag(text: str) -> str:
    return STAGE_TAG.sub("", text).strip()


def _text(message) -> str:
    content = message.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    text = str(content).strip()
    if not text:
        raise RuntimeError("Model returned an empty answer")
    return text


ImageGenerator = Callable[..., list[media.MediaFile]]
VideoMaker = Callable[..., video.VideoResult]
PASTED_TREND_REPORT = re.compile(
    r"^\s{0,3}#{1,3}\s*(hot trends right now|trend analysis|evidence log|script\s+\d+\b|reel\s*/\s*video ad script)", re.I | re.M
)
DISCLOSURE = (
    "AI disclosure: this reel is fully AI-generated (original synthetic persona, AI images/video and synthetic voice). "
    'Turn on the platform\'s AI label (Instagram "AI info", TikTok "AI-generated content") and say so in the caption and bio.'
)


def _off(name: str, default: str = "on") -> bool:
    return (config.get(name, default) or default).strip().lower() in OFF


def has_pasted_trends(text: str) -> bool:
    """True when the brief already contains a trend report or a script, so Create need not research again."""
    return bool(PASTED_TREND_REPORT.search(text or ""))


@dataclass
class MediaOutcome:
    section: str
    run_id: str
    files: list[dict] = field(default_factory=list)
    cost: float = 0.0


def run_media(persona: str, content: str, generator: ImageGenerator) -> MediaOutcome:
    """Reference portrait + one keyframe per reel scene (or the photo concepts). Never raises."""
    heading = "## Generated media"
    run_id = uuid.uuid4().hex
    if _off("IMAGE_GENERATION"):
        return MediaOutcome(f"{heading}\n\nmedia not generated: IMAGE_GENERATION=off", run_id)
    reference = media.reference_prompt(persona)
    scenes = video.parse_scenes(content)
    if scenes:
        concepts = [s.visual for s in scenes]
        labels = ["Reference portrait", *(f"Scene {s.index + 1} keyframe ({s.start:g}-{s.end:g}s)" for s in scenes)]
    else:
        concepts = media.concept_prompts(content)
        labels = ["Reference portrait", *(f"Photo concept {i}" for i in range(1, len(concepts) + 1))]
    if not reference:
        return MediaOutcome(f"{heading}\n\nmedia not generated: no image-generation reference prompt found in the persona card", run_id)
    files: list[media.MediaFile] = []
    reason = None
    try:
        if scenes:  # keyframes feed a 9:16 reel
            files = generator([reference, *concepts], None, run_id=run_id, aspect_ratio="9:16")
        else:
            files = generator([reference, *concepts], None, run_id=run_id)
    except media.MediaError as error:
        files, reason = error.files, error.reason
    except Exception as error:  # never surface request details or credentials
        reason = f"image generation failed ({type(error).__name__})"
    base = f"http://127.0.0.1:{config.get('CREST_GRAPH_PORT', '21951')}"
    lines = [heading, ""]
    records = []
    for index, item in enumerate(files):
        label = labels[index] if index < len(labels) else f"Image {index + 1}"
        lines.append(f"{index + 1}. {label}: {base}{item.url_path} (sha256 `{item.sha256}`)")
        records.append({"path": str(item.path), "label": label, "scene": index - 1 if scenes and index else None, "cost": item.cost_usd})
    if files:
        lines += ["", "Images are AI-generated; disclose this in captions and bio. Local URLs are served on loopback only."]
    if reason:
        lines += (["", f"media not generated: {reason}"] if not files else ["", f"media not generated for the remaining prompts: {reason}"])
    cost = sum(f.cost_usd for f in files if f.cost_usd is not None)
    return MediaOutcome("\n".join(lines).strip(), run_id, records, round(cost, 4))


def media_section(persona: str, content: str, generator: ImageGenerator) -> str:
    """Generate images for the Create output; never raises, so a media failure cannot fail the Task."""
    return run_media(persona, content, generator).section


def _urls(text: str) -> set[str]:
    return {u for u in (trends.normalize_url(m.rstrip(".,;)")) for m in video._URL.findall(text or "")) if u}


def based_on_trend(content: str, report: str, brief: str, state_trends: list[dict]) -> tuple[str, str | None, str]:
    """(trend name, URL, check). The URL is trusted only if it appears in the cited analysis or the user's brief."""
    name, url = video.trend_pick(content)
    if url and trends.normalize_url(url) in (_urls(report) | _urls(brief)):
        return name or "(unnamed trend)", url, "URL verified against the cited trend analysis"
    for trend in state_trends or []:
        if name and (name.lower() in trend["trend"].lower() or trend["trend"].lower() in name.lower()):
            return trend["trend"], trend["evidence"][0]["url"], "URL taken from the cited analysis for the named trend"
    if state_trends:
        top = state_trends[0]
        return top["trend"], top["evidence"][0]["url"], "the script's trend URL was not in the cited analysis; top-ranked cited trend shown"
    if name and name.lower().startswith("none"):
        return "none validated (not trend-based)", None, "no validated trend was available"
    return name or "not stated", None, "no cited trend URL could be verified"


def video_section(state: dict, maker: VideoMaker) -> str:
    """Build the reel; never raises, so a video failure cannot fail the Task."""
    content = state.get("content", "")
    name, url, check = based_on_trend(content, state.get("trend_report", ""), state.get("input", ""), state.get("trends") or [])
    trend_line = f"- Based on trend: {name}" + (f" - {url}" if url else "") + f" ({check})"
    head = ["## Video", ""]
    if _off("VIDEO_GENERATION"):
        return "\n".join([*head, trend_line, "", "video not generated: VIDEO_GENERATION=off"])
    scenes = video.parse_scenes(content)
    keyframes: list[Path | None] = [None] * len(scenes)
    for item in state.get("media_files") or []:
        if item.get("scene") is not None and 0 <= item["scene"] < len(scenes):
            keyframes[item["scene"]] = Path(item["path"])
    if not any(keyframes):  # no scene keyframes: animate the reference portrait rather than nothing
        portrait = next((Path(i["path"]) for i in state.get("media_files") or [] if i.get("scene") is None), None)
        keyframes = [portrait] * len(scenes)
    trend_cost, media_cost = float(state.get("trend_cost") or 0), float(state.get("media_cost") or 0)
    limit = video._float("MAX_USD_PER_TASK", 3.0)
    try:
        result = maker(scenes, keyframes, run_id=state.get("media_run") or uuid.uuid4().hex, budget_usd=max(0.0, limit - trend_cost - media_cost))
    except video.VideoError as error:
        return "\n".join([*head, trend_line, "", f"video not generated: {error.reason}"])
    except Exception as error:  # never surface request details or credentials
        return "\n".join([*head, trend_line, "", f"video not generated: video build failed ({type(error).__name__})"])
    base = f"http://127.0.0.1:{config.get('CREST_GRAPH_PORT', '21951')}"
    total = trend_cost + media_cost + result.cost_usd
    lines = [
        *head,
        f"- Reel: {base}{result.url_path}",
        f"- Length: {result.duration:.1f} s, {result.width}x{result.height} (9:16), H.264 + AAC, {video.FPS} fps, {result.size_bytes / 1_048_576:.2f} MB",
        f"- Path used: {result.path_used}",
        f"- Voiceover: {result.voice}",
        trend_line,
        f"- File: `{result.path}` (sha256 `{result.sha256}`)",
        f"- Cost: video ${result.cost_usd:.3f}; task total about ${total:.3f} (trends ${trend_cost:.3f}, images ${media_cost:.3f}) "
        f"of MAX_USD_PER_TASK=${limit:.2f}",
        "",
        "| Scene | Time | On-screen text | Source |",
        "|---|---|---|---|",
    ]
    for scene, source in zip(scenes, result.scene_sources):
        lines.append(f"| {scene.index + 1} | {scene.start:g}-{scene.end:g}s | {scene.on_screen.replace('|', '/') or '-'} | {source} |")
    if result.notes:
        lines += ["", "Notes:", *(f"- {note}" for note in result.notes)]
    lines += ["", DISCLOSURE, "The local URL is served on loopback only; upload the MP4 yourself when publishing."]
    return "\n".join(lines).strip()


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    image_generator: ImageGenerator | None = None,
    trend_searcher: trends.Searcher | None = None,
    page_fetcher: trends.PageFetcher | None = None,
    video_maker: VideoMaker | None = None,
):
    generate = image_generator or media.generate_images
    make_video = video_maker or video.make_reel
    trend_swarm = trends.build_trend_graph(trend_searcher, page_fetcher)

    def ask(system: str, user: str) -> str:
        return _text(model.invoke([SystemMessage(system), HumanMessage(user)]))

    def supervisor(state: CrestState) -> CrestState:
        stage = parse_stage(state["input"])
        if stage is None:
            word = ask(prompts.SUPERVISOR, state["input"]).lower()
            stage = next((s for s in STAGES if s in word), "create")
        return {"stage": stage, "sections": []}

    def brief(state: CrestState) -> str:
        return strip_stage_tag(state["input"])

    def route(state: CrestState) -> str:
        if state["stage"] != "create":
            return state["stage"]
        if has_pasted_trends(brief(state)) or trends.swarm_size("create") == 0:
            return "persona_agent"
        return "trend_swarm"

    def persona_agent(state: CrestState) -> CrestState:
        persona = ask(prompts.PERSONA, brief(state))
        return {"persona": persona, "sections": [persona]}

    def content_agent(state: CrestState) -> CrestState:
        analysis = state.get("trend_report") or (
            "(use the trend report / script pasted in the brief above)" if has_pasted_trends(brief(state)) else "(no trend research ran)"
        )
        content = ask(prompts.CONTENT, f"{brief(state)}\n\n---\n{state['persona']}\n\n---\n# Trend analysis\n{analysis}")
        return {"content": content, "sections": [*state["sections"], content]}

    def media_agent(state: CrestState) -> CrestState:
        content = state.get("content") or (state["sections"][-1] if state["sections"] else "")
        outcome = run_media(state.get("persona", ""), content, generate)
        return {"sections": [*state["sections"], outcome.section], "media_run": outcome.run_id,
                "media_files": outcome.files, "media_cost": outcome.cost}

    def video_agent(state: CrestState) -> CrestState:
        return {"sections": [*state["sections"], video_section(state, make_video)]}

    def scheduler_agent(state: CrestState, config=None) -> CrestState:
        calendar = ask(prompts.SCHEDULER, brief(state))
        queue = ig_workflows.queue_calendar(calendar, thread_id=ig_workflows.thread_id_of(config), persona=state.get("persona"))
        return {"sections": [calendar, queue]}

    def engage_agent(state: CrestState, config=None) -> CrestState:
        thread_id = ig_workflows.thread_id_of(config)
        if ig_workflows.is_approval(brief(state)):
            return {"sections": [ig_workflows.approve(brief(state), thread_id)]}
        items = ig_workflows.fetch_inbox(thread_id)
        triage = ask(prompts.ENGAGE, ig_workflows.engage_input(brief(state), items))
        return {"sections": [triage, ig_workflows.record_drafts(triage, items, thread_id=thread_id)]}

    def analyst_agent(state: CrestState) -> CrestState:
        data, source = ig_workflows.analyst_input(brief(state))
        return {"sections": [ask(prompts.ANALYST, data), f"## Data source\n{source}"]}

    def trend_writer(state: CrestState) -> CrestState:
        return {"sections": [state.get("trend_report", "")]}

    def script_writer(state: CrestState) -> CrestState:
        analysis = state.get("trend_report", "")
        scripts = ask(prompts.SCRIPT_WRITER, f"{brief(state)}\n\n---\n# Trend analysis\n{analysis}")
        return {"sections": [scripts, "# Trend analysis used\n\n" + analysis]}

    def finalize(state: CrestState) -> CrestState:
        header = f"# PersonaLab - {TITLES[state['stage']]}"
        sections = list(state["sections"])
        if state["stage"] == "create" and state.get("trend_report"):
            sections.append("# Trend analysis used\n\n" + state["trend_report"])
        return {"output": "\n\n".join([header, *sections]).strip() + "\n"}

    graph = StateGraph(CrestState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("persona_agent", persona_agent)
    graph.add_node("content_agent", content_agent)
    graph.add_node("media_agent", media_agent)
    graph.add_node("video_agent", video_agent)
    graph.add_node("scheduler_agent", scheduler_agent)
    graph.add_node("engage_agent", engage_agent)
    graph.add_node("analyst_agent", analyst_agent)
    graph.add_node("trend_swarm", trend_swarm)  # compiled subgraph: Send fan-out to parallel researchers
    graph.add_node("trend_writer", trend_writer)
    graph.add_node("script_writer", script_writer)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route,
        {
            "trend_swarm": "trend_swarm",
            "persona_agent": "persona_agent",
            "schedule": "scheduler_agent",
            "engage": "engage_agent",
            "analyze": "analyst_agent",
            "trends": "trend_swarm",
            "scripts": "trend_swarm",
        },
    )
    graph.add_conditional_edges(
        "trend_swarm",
        lambda state: {"scripts": "script_writer", "create": "persona_agent"}.get(state["stage"], "trend_writer"),
        ["script_writer", "trend_writer", "persona_agent"],
    )
    graph.add_edge("persona_agent", "content_agent")
    graph.add_edge("content_agent", "media_agent")
    graph.add_edge("media_agent", "video_agent")
    for node in ("video_agent", "scheduler_agent", "engage_agent", "analyst_agent", "trend_writer", "script_writer"):
        graph.add_edge(node, "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
