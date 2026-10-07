"""PersonaLab supervisor graph: routes a request to the Create, Schedule, Engage, Analyze, Trends, Scripts or Onboarding agents.

The Create path ends with media_agent, which renders the persona reference portrait and photo concepts.
Instagram and approval tools attach to these same nodes in later phases.
"""
import re
import uuid
from typing import Callable, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import config, ig_workflows, media, onboarding, prompts, trends

Stage = Literal["create", "schedule", "engage", "analyze", "trends", "scripts", "onboarding"]
STAGES: tuple[Stage, ...] = ("create", "schedule", "engage", "analyze", "trends", "scripts", "onboarding")
STAGE_TAG = re.compile(r"\[stage:(create|schedule|engage|analyze|trends|scripts|onboarding)\]", re.IGNORECASE)
TITLES = {
    "create": "Create",
    "schedule": "Schedule",
    "engage": "Engage",
    "analyze": "Analyze",
    "trends": "Trend Analyzer",
    "scripts": "Trend-based Script Writer",
    "onboarding": "Onboarding - Virtual Avatar",
}


class CrestState(TypedDict, total=False):
    input: str
    stage: Stage
    persona: str
    sections: list[str]
    output: str
    trends: list[dict]  # written by the trend swarm subgraph
    trend_report: str


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


def media_section(persona: str, content: str, generator: ImageGenerator) -> str:
    """Generate images for the Create output; never raises, so a media failure cannot fail the Task."""
    heading = "## Generated media"
    if (config.get("IMAGE_GENERATION", "on") or "on").strip().lower() in ("off", "0", "false", "no", "disabled"):
        return f"{heading}\n\nmedia not generated: IMAGE_GENERATION=off"
    reference = media.reference_prompt(persona)
    concepts = media.concept_prompts(content)
    if not reference:
        return f"{heading}\n\nmedia not generated: no image-generation reference prompt found in the persona card"
    labels = ["Reference portrait", *(f"Photo concept {i}" for i in range(1, len(concepts) + 1))]
    files: list[media.MediaFile] = []
    reason = None
    try:
        files = generator([reference, *concepts], None, run_id=uuid.uuid4().hex)
    except media.MediaError as error:
        files, reason = error.files, error.reason
    except Exception as error:  # never surface request details or credentials
        reason = f"image generation failed ({type(error).__name__})"
    base = f"http://127.0.0.1:{config.get('CREST_GRAPH_PORT', '21951')}"
    lines = [heading, ""]
    for index, item in enumerate(files):
        label = labels[index] if index < len(labels) else f"Image {index + 1}"
        lines.append(f"{index + 1}. {label}: {base}{item.url_path} (sha256 `{item.sha256}`)")
    if files:
        lines += ["", "Images are AI-generated; disclose this in captions and bio. Local URLs are served on loopback only."]
    if reason:
        lines += (["", f"media not generated: {reason}"] if not files else ["", f"media not generated for the remaining prompts: {reason}"])
    return "\n".join(lines).strip()


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    image_generator: ImageGenerator | None = None,
    trend_searcher: trends.Searcher | None = None,
    page_fetcher: trends.PageFetcher | None = None,
):
    generate = image_generator or media.generate_images
    trend_swarm = trends.build_trend_graph(trend_searcher, page_fetcher)

    def ask(system: str, user: str) -> str:
        system += prompts.AVATAR_REUSE_RULE if onboarding.extract_avatar(user) else ""  # reuse an Onboarding avatar in any stage
        return _text(model.invoke([SystemMessage(system), HumanMessage(user)]))

    def supervisor(state: CrestState) -> CrestState:
        stage = parse_stage(state["input"])
        if stage is None:
            word = ask(prompts.SUPERVISOR, state["input"]).lower()
            stage = next((s for s in STAGES if s in word), "create")
        return {"stage": stage, "sections": []}

    def brief(state: CrestState) -> str:
        return strip_stage_tag(state["input"])

    def persona_agent(state: CrestState) -> CrestState:
        persona = ask(prompts.PERSONA, brief(state))
        return {"persona": persona, "sections": [persona]}

    def content_agent(state: CrestState) -> CrestState:
        content = ask(prompts.CONTENT, f"{brief(state)}\n\n---\n{state['persona']}")
        return {"sections": [*state["sections"], content]}

    def media_agent(state: CrestState) -> CrestState:
        content = state["sections"][-1] if state["sections"] else ""
        return {"sections": [*state["sections"], media_section(state.get("persona", ""), content, generate)]}

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
        return {"output": "\n\n".join([header, *state["sections"]]).strip() + "\n"}

    graph = StateGraph(CrestState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("persona_agent", persona_agent)
    graph.add_node("content_agent", content_agent)
    graph.add_node("media_agent", media_agent)
    graph.add_node("scheduler_agent", scheduler_agent)
    graph.add_node("engage_agent", engage_agent)
    graph.add_node("analyst_agent", analyst_agent)
    graph.add_node("trend_swarm", trend_swarm)  # compiled subgraph: Send fan-out to parallel researchers
    graph.add_node("trend_writer", trend_writer)
    graph.add_node("script_writer", script_writer)
    graph.add_node("onboarding_agent", lambda state: {"sections": onboarding.run(ask, brief(state), prompts.ONBOARDING_PROFILE, prompts.ONBOARDING_SPEC)})
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["stage"],
        {
            "create": "persona_agent",
            "schedule": "scheduler_agent",
            "engage": "engage_agent",
            "analyze": "analyst_agent",
            "trends": "trend_swarm",
            "scripts": "trend_swarm",
            "onboarding": "onboarding_agent",
        },
    )
    graph.add_conditional_edges(
        "trend_swarm",
        lambda state: "script_writer" if state["stage"] == "scripts" else "trend_writer",
        ["script_writer", "trend_writer"],
    )
    graph.add_edge("persona_agent", "content_agent")
    graph.add_edge("content_agent", "media_agent")
    for node in ("media_agent", "scheduler_agent", "engage_agent", "analyst_agent", "trend_writer", "script_writer", "onboarding_agent"):
        graph.add_edge(node, "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
