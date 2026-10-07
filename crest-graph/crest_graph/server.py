"""Local HTTP front door for the PersonaLab graph. The Sokosumi worker calls POST /run."""
import hmac
import ipaddress
import logging
import uuid
from functools import lru_cache

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from . import config, media
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


def _is_loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address((host or "").strip("[]")).is_loopback
    except ValueError:
        return False


@app.get("/media/{run_id}/{name}")
def media_file(run_id: str, name: str, request: Request) -> FileResponse:
    # Loopback only by default: local previews for the operator. MEDIA_PUBLIC=1 (hosted) lets Task readers open the
    # links; name validation and traversal protection below still apply, so only generated images and reel.mp4 serve.
    if not config.media_public() and not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "Media is served on loopback only")
    path = media.resolve_media_file(run_id, name)
    if path is None:
        raise HTTPException(404, "Not found")
    return FileResponse(
        path,
        media_type=media.EXT_MIME[path.suffix.lstrip(".")],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


# ---- Engage approvals (sends only drafts a human approved; DRY-RUN without Instagram credentials) ----
class ApproveRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=200)
    ids: list[int] = Field(min_length=1, max_length=50)


@app.post("/approve", dependencies=[Depends(require_token)])
def approve_drafts(request: ApproveRequest) -> dict:
    from .ig_workflows import approve_ids

    return {"thread_id": request.thread_id, "results": approve_ids(request.ids, request.thread_id)}


def main() -> None:
    # Local default 127.0.0.1:21951. Hosted: CREST_GRAPH_HOST=0.0.0.0 (or :: for Railway private IPv6) and PORT.
    uvicorn.run(app, host=config.graph_host(), port=config.graph_port(), log_level="info")


if __name__ == "__main__":
    main()
