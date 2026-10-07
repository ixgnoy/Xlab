"""Local HTTP front door for the PersonaLab graph. The Sokosumi worker calls POST /run."""
import hmac
import logging
import uuid
from functools import lru_cache

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from . import config
from .graph import STAGES, build_graph
from .model import MissingModelConfig, chat_model

MAX_INPUT = 16000
log = logging.getLogger("crest_graph")


class RunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=MAX_INPUT)
    stage: str | None = None
    thread_id: str | None = Field(default=None, max_length=200)


class RunResponse(BaseModel):
    stage: str
    thread_id: str
    output: str


@lru_cache(maxsize=1)
def graph():
    # Phase 1: in-memory checkpoints. Phase 2 swaps in the Postgres checkpointer for durable interrupts.
    return build_graph(chat_model(), InMemorySaver())


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = config.get("CREST_GRAPH_TOKEN")
    if not expected:
        raise HTTPException(503, "CREST_GRAPH_TOKEN is not configured")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Unauthorized")


app = FastAPI(title="PersonaLab graph", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_configured": bool(config.get("MODEL_API_KEY") and config.get("MODEL_ID"))}


@app.post("/run", response_model=RunResponse, dependencies=[Depends(require_token)])
def run(request: RunRequest) -> RunResponse:
    text = request.input.strip()
    if not text:
        raise HTTPException(422, "Input must not be blank")
    if request.stage is not None:
        if request.stage not in STAGES:
            raise HTTPException(422, f"stage must be one of {', '.join(STAGES)}")
        text = f"[stage:{request.stage}] {text}"
    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        state = graph().invoke({"input": text}, {"configurable": {"thread_id": thread_id}})
    except MissingModelConfig as error:
        raise HTTPException(503, str(error)) from None
    except Exception as error:
        # Log the error class and HTTP status only; never the request, prompt, or credentials.
        log.error("Model turn failed: %s status=%s", type(error).__name__, getattr(error, "status_code", None))
        raise HTTPException(502, "Model turn failed") from None
    return RunResponse(stage=state["stage"], thread_id=thread_id, output=state["output"])


# ---- Engage approvals (sends only drafts a human approved; DRY-RUN without Instagram credentials) ----
class ApproveRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=200)
    ids: list[int] = Field(min_length=1, max_length=50)


@app.post("/approve", dependencies=[Depends(require_token)])
def approve_drafts(request: ApproveRequest) -> dict:
    from .ig_workflows import approve_ids

    return {"thread_id": request.thread_id, "results": approve_ids(request.ids, request.thread_id)}


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(config.get("CREST_GRAPH_PORT", "21951")), log_level="info")


if __name__ == "__main__":
    main()
