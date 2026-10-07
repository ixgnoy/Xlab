"""PersonaLab supervisor graph: routes a request to the Create, Schedule, Engage or Analyze agents.

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

from . import config, media, prompts

Stage = Literal["create", "schedule", "engage", "analyze"]
STAGES: tuple[Stage, ...] = ("create", "schedule", "engage", "analyze")
STAGE_TAG = re.compile(r"\[stage:(create|schedule|engage|analyze)\]", re.IGNORECASE)
TITLES = {"create": "Create", "schedule": "Schedule", "engage": "Engage", "analyze": "Analyze"}


class CrestState(TypedDict, total=False):
    input: str
    stage: Stage
    persona: str
    sections: list[str]
    output: str


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
):
    generate = image_generator or media.generate_images

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

    def persona_agent(state: CrestState) -> CrestState:
        persona = ask(prompts.PERSONA, brief(state))
        return {"persona": persona, "sections": [persona]}

    def content_agent(state: CrestState) -> CrestState:
        content = ask(prompts.CONTENT, f"{brief(state)}\n\n---\n{state['persona']}")
        return {"sections": [*state["sections"], content]}

    def media_agent(state: CrestState) -> CrestState:
        content = state["sections"][-1] if state["sections"] else ""
        return {"sections": [*state["sections"], media_section(state.get("persona", ""), content, generate)]}

    def scheduler_agent(state: CrestState) -> CrestState:
        return {"sections": [ask(prompts.SCHEDULER, brief(state))]}

    def engage_agent(state: CrestState) -> CrestState:
        return {"sections": [ask(prompts.ENGAGE, brief(state))]}

    def analyst_agent(state: CrestState) -> CrestState:
        return {"sections": [ask(prompts.ANALYST, brief(state))]}

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
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["stage"],
        {"create": "persona_agent", "schedule": "scheduler_agent", "engage": "engage_agent", "analyze": "analyst_agent"},
    )
    graph.add_edge("persona_agent", "content_agent")
    graph.add_edge("content_agent", "media_agent")
    for node in ("media_agent", "scheduler_agent", "engage_agent", "analyst_agent"):
        graph.add_edge(node, "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
