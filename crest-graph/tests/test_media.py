import base64
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from crest_graph import config, media, server
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from crest_graph.graph import build_graph, media_section


def fake(*replies: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter(AIMessage(r) for r in replies))

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 64
PRICING = {"prompt": "0.00000025", "completion": "0.0000015", "image_output": "0.00003"}
RUN = "a" * 32

PERSONA = """## Persona card
- **Name:** Nova Lin (invented)
- **Visual identity:** late-20s, cropped silver bob, teal and sand palette, rooftop gardens
- **Image-generation reference prompt:**
  > Portrait of Nova, an original AI character with a cropped silver bob, teal jacket, rooftop garden, soft light
"""

CONTENT = """## 3 on-brand photo concepts
### 1. Sunrise stretch
- Scene: rooftop at sunrise
- **Generation prompt:** Nova stretching on a rooftop at sunrise, teal activewear
### 2. Market run
- **Generation prompt**: Nova jogging through a morning market, sand hoodie
### 3. Desk reset
- Generation prompt:
```
Nova at a plant-filled desk writing a planner, warm lamp light
```
## Reel (8 seconds)
- Generation prompt: should not be used
"""


def settings(tmp_path, monkeypatch, **values):
    base = {"OPENROUTER_API_KEY": "sk-test", "CREST_GRAPH_PORT": "21951"}
    base.update(values)
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(config, "get", lambda name, default=None: base.get(name, default))


def image_response(data: bytes, cost: float | None = 0.04, mime: str = "image/png") -> dict:
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    usage = {"cost": cost} if cost is not None else {}
    return {"choices": [{"message": {"role": "assistant", "content": "", "images": [{"type": "image_url", "image_url": {"url": url}}]}}], "usage": usage}


def transport(images: list, pricing: dict | None = PRICING, log: list | None = None):
    queue = list(images)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            data = [{"id": "google/gemini-3.1-flash-lite-image", "pricing": pricing}] if pricing is not None else []
            return httpx.Response(200, json={"data": data})
        body = json.loads(request.content)
        if log is not None:
            log.append({"body": body, "auth": request.headers.get("authorization")})
        item = queue.pop(0)
        return item if isinstance(item, httpx.Response) else httpx.Response(200, json=item)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_first_image_becomes_reference_for_the_rest(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    log: list = []
    client = transport([image_response(PNG), image_response(JPEG, mime="image/jpeg"), image_response(PNG)], log=log)
    files = media.generate_images(["portrait", "concept one", "concept two"], None, run_id=RUN, client=client)
    assert [f.mime for f in files] == ["image/png", "image/jpeg", "image/png"]
    assert files[0].sha256 == hashlib.sha256(PNG).hexdigest()
    assert files[0].path.read_bytes() == PNG and files[0].path.parent == tmp_path / ".local" / "media" / RUN
    assert files[1].name.endswith(".jpg") and files[1].url_path == f"/media/{RUN}/{files[1].name}"
    first, second = log[0]["body"], log[1]["body"]
    assert first["modalities"] == ["image", "text"] and first["model"] == media.DEFAULT_MODEL
    assert len(first["messages"][0]["content"]) == 1  # text only: no reference yet
    parts = second["messages"][0]["content"]
    assert parts[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert "real, identifiable person" in parts[0]["text"] and "same fictional character" in parts[0]["text"]
    assert log[0]["auth"] == "Bearer sk-test"


def test_supplied_reference_is_sent_with_every_prompt(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, IMAGE_MODEL_ID="google/gemini-3.1-flash-lite-image")
    log: list = []
    media.generate_images(["a", "b"], JPEG, run_id=RUN, client=transport([image_response(PNG)] * 2, log=log))
    assert all(len(entry["body"]["messages"][0]["content"]) == 2 for entry in log)


def test_max_images_and_budget_guard(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, MAX_IMAGES="2")
    with pytest.raises(media.MediaError) as error:
        media.generate_images(["a", "b", "c"], None, run_id=RUN, client=transport([image_response(PNG)] * 3))
    assert len(error.value.files) == 2 and "2 of 3" in error.value.reason

    settings(tmp_path, monkeypatch, MAX_USD_PER_TASK="0.01")
    with pytest.raises(media.MediaError) as error:
        media.generate_images(["a"], None, run_id=RUN, client=transport([]))
    assert "budget guard" in error.value.reason and not error.value.files

    # actual reported cost stops the run even when the estimate looked affordable
    settings(tmp_path, monkeypatch, MAX_USD_PER_TASK="0.1")
    with pytest.raises(media.MediaError) as error:
        media.generate_images(["a", "b"], None, run_id=RUN, client=transport([image_response(PNG, cost=0.09), image_response(PNG)]))
    assert len(error.value.files) == 1 and "budget guard" in error.value.reason


def test_estimate_uses_live_pricing_and_falls_back(tmp_path, monkeypatch):
    estimate = media.estimate_usd_per_image(PRICING)
    assert 0.04 < estimate < 0.05
    assert media.estimate_usd_per_image({"prompt": "-1", "completion": "-1"}) is None
    settings(tmp_path, monkeypatch)
    budget = media.build_budget(transport([], pricing=None), media.DEFAULT_MODEL)
    assert budget.usd_per_image == media.DEFAULT_USD_PER_IMAGE and not budget.priced


def test_failures_are_reported_without_secrets(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, OPENROUTER_API_KEY="")
    with pytest.raises(media.MediaError, match="OPENROUTER_API_KEY"):
        media.generate_images(["a"], None, run_id=RUN, client=transport([]))
    settings(tmp_path, monkeypatch)
    error_body = httpx.Response(402, json={"error": {"message": "Insufficient credits"}})
    with pytest.raises(media.MediaError) as error:
        media.generate_images(["a", "b"], None, run_id=RUN, client=transport([image_response(PNG), error_body]))
    assert "HTTP 402" in error.value.reason and "sk-test" not in error.value.reason and len(error.value.files) == 1
    with pytest.raises(media.MediaError, match="no image"):
        media.generate_images(["a"], None, run_id=RUN, client=transport([{"choices": [{"message": {"content": "I can't"}}]}]))
    with pytest.raises(media.MediaError, match="real-person"):
        media.generate_images(["a celebrity lookalike"], None, run_id=RUN, client=transport([]))


def test_prompt_extraction_from_markdown():
    assert media.reference_prompt(PERSONA).startswith("Portrait of Nova, an original AI character")
    assert media.concept_prompts(CONTENT) == [
        "Nova stretching on a rooftop at sunrise, teal activewear",
        "Nova jogging through a morning market, sand hoodie",
        "Nova at a plant-filled desk writing a planner, warm lamp light",
    ]
    no_label = PERSONA.split("- **Image-generation")[0]
    assert "cropped silver bob" in media.reference_prompt(no_label)
    table = "## 3 on-brand photo concepts\n| # | Scene | Generation prompt |\n|---|---|---|\n| 1 | roof | Nova on a roof |\n| 2 | park | Nova in a park |\n"
    assert media.concept_prompts(table) == ["Nova on a roof", "Nova in a park"]
    loose = "## 3 on-brand photo concepts\n1. Rooftop sunrise stretch in teal activewear\n2. Market jog in a sand hoodie at dawn\n"
    assert len(media.concept_prompts(loose)) == 2


def test_media_route_is_strict_and_loopback_only(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    [saved] = media.generate_images(["a"], None, run_id=RUN, client=transport([image_response(PNG)]))
    local = TestClient(server.app, client=("127.0.0.1", 5000))
    ok = local.get(saved.url_path)
    assert ok.status_code == 200 and ok.content == PNG and ok.headers["content-type"] == "image/png"
    for bad in (f"/media/{RUN}/..%2F..%2Fsecret.png", f"/media/{RUN}/x.png", f"/media/../{saved.name}", f"/media/{'b' * 32}/{saved.name}"):
        assert local.get(bad).status_code == 404
    assert TestClient(server.app, client=("10.0.0.5", 5000)).get(saved.url_path).status_code == 403


def test_create_graph_appends_generated_media(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    calls = []

    def generator(prompts, reference, run_id):
        calls.append(prompts)
        return [media.MediaFile(run_id, f"0{i}-{'c' * 16}.png", tmp_path / "x.png", "d" * 64, "image/png", p) for i, p in enumerate(prompts)]

    out = build_graph(fake(PERSONA, CONTENT), image_generator=generator).invoke({"input": "[stage:create] fitness persona"})
    assert calls[0][0].startswith("Portrait of Nova") and len(calls[0]) == 4
    section = out["output"].split("## Generated media")[1]
    assert "1. Reference portrait: http://127.0.0.1:21951/media/" in section and "sha256 `" + "d" * 64 in section
    assert "4. Photo concept 3" in section


def test_media_failure_or_disable_never_fails_the_task(tmp_path, monkeypatch):
    def broken(prompts, reference, run_id):
        raise media.MediaError("OpenRouter HTTP 500")

    settings(tmp_path, monkeypatch)
    out = build_graph(fake(PERSONA, CONTENT), image_generator=broken).invoke({"input": "[stage:create] x"})
    assert "media not generated: OpenRouter HTTP 500" in out["output"]
    assert "media not generated: image generation failed (ValueError)" in media_section(PERSONA, CONTENT, lambda *a, **k: (_ for _ in ()).throw(ValueError("k")))
    assert "no image-generation reference prompt" in media_section("## Persona card\nNova", CONTENT, broken)
    settings(tmp_path, monkeypatch, IMAGE_GENERATION="off")
    assert media_section(PERSONA, CONTENT, broken).endswith("media not generated: IMAGE_GENERATION=off")
    settings(tmp_path, monkeypatch, OPENROUTER_API_KEY="")
    assert "media not generated: OPENROUTER_API_KEY is not configured" in media_section(PERSONA, CONTENT, media.generate_images)


def test_other_stages_never_generate_media(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    out = build_graph(fake("## Posting calendar"), image_generator=lambda *a, **k: pytest.fail("no media")).invoke({"input": "[stage:schedule] x"})
    assert "Generated media" not in out["output"]
