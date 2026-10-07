from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from crest_graph import server
from crest_graph.graph import build_graph, parse_stage, strip_stage_tag


class RecordingModel(GenericFakeChatModel):
    calls: list = []

    def _generate(self, messages, *args, **kwargs):
        self.calls.append(messages)
        return super()._generate(messages, *args, **kwargs)


def fake(*replies: str) -> RecordingModel:
    model = RecordingModel(messages=iter(AIMessage(r) for r in replies))
    model.calls = []
    return model


def test_stage_tag_parsing():
    assert parse_stage("[stage:Analyze] numbers") == "analyze"
    assert parse_stage("no tag") is None
    assert strip_stage_tag("[stage:create]  brief ") == "brief"


def test_create_runs_persona_then_content():
    model = fake("## Persona card\nNova", "## Reel (8 seconds)\nhook")
    out = build_graph(model, image_generator=lambda *a, **k: []).invoke({"input": "[stage:create] fitness coach persona"})
    assert out["stage"] == "create"
    assert len(model.calls) == 2
    assert "Nova" in model.calls[1][1].content  # content agent sees the persona card
    assert out["output"].startswith("# PersonaLab - Create")
    assert "## Persona card" in out["output"] and "## Reel" in out["output"]
    assert "## Generated media" in out["output"]  # media_agent runs last on the Create path


def test_each_tagged_stage_routes_without_classification():
    for stage, heading in (("schedule", "Schedule"), ("engage", "Engage"), ("analyze", "Analyze")):
        model = fake(f"## {heading} body")
        out = build_graph(model).invoke({"input": f"[stage:{stage}] go"})
        assert out["stage"] == stage and len(model.calls) == 1
        assert out["output"].startswith(f"# PersonaLab - {heading}")


def test_untagged_input_is_classified_by_supervisor():
    model = fake("engage", "## Inbox triage")
    out = build_graph(model).invoke({"input": "reply to these comments: love it!"})
    assert out["stage"] == "engage" and len(model.calls) == 2


def test_empty_model_answer_fails_instead_of_completing():
    model = fake("   ")
    try:
        build_graph(model).invoke({"input": "[stage:analyze] x"})
    except RuntimeError as error:
        assert "empty" in str(error)
    else:
        raise AssertionError("empty answer must fail")


def test_server_requires_token_and_validates_stage(monkeypatch):
    monkeypatch.setattr(server.config, "get", lambda name, default=None: {"CREST_GRAPH_TOKEN": "t0ken"}.get(name, default))
    monkeypatch.setattr(server, "graph", lambda: build_graph(fake("## Posting calendar")))
    client = TestClient(server.app)
    assert client.post("/run", json={"input": "x"}).status_code == 401
    assert client.post("/run", json={"input": "x", "stage": "bogus"}, headers={"Authorization": "Bearer t0ken"}).status_code == 422
    ok = client.post("/run", json={"input": "plan week", "stage": "schedule"}, headers={"Authorization": "Bearer t0ken"})
    assert ok.status_code == 200 and ok.json()["stage"] == "schedule"
    assert ok.json()["output"].startswith("# PersonaLab - Schedule")
