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
