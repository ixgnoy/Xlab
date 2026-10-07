"""PersonaLab supervisor graph: routes a request to the Create, Schedule, Engage or Analyze agents.

Phase 1 agents are LLM-only. Media, Instagram and approval tools attach to these same nodes in later phases.
"""
import re
from typing import Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import prompts
from . import ig_workflows

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


def build_graph(model: BaseChatModel, checkpointer: BaseCheckpointSaver | None = None):
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

    def finalize(state: CrestState) -> CrestState:
        header = f"# PersonaLab - {TITLES[state['stage']]}"
        return {"output": "\n\n".join([header, *state["sections"]]).strip() + "\n"}

    graph = StateGraph(CrestState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("persona_agent", persona_agent)
    graph.add_node("content_agent", content_agent)
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
    for node in ("content_agent", "scheduler_agent", "engage_agent", "analyst_agent"):
        graph.add_edge(node, "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
