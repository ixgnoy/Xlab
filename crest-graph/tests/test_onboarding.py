import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from crest_graph import onboarding, prompts
from crest_graph.graph import STAGES, build_graph, parse_stage

OFFERS = Path(__file__).resolve().parents[2] / "coworker" / "offers.json"

AVATAR = {
    "name": "Maya Lim", "handle": "@mayamakes", "niche": "home baking", "traits": ["warm", "nerdy"],
    "interests": ["sourdough"], "values": ["honesty"], "moat": "20 years running a family bakery",
    "voice": {"tone": "warm", "pacing": "calm", "catchphrases": ["crumb check!"], "sample_lines": ["a", "b", "c"]},
    "visual_prompt": "original illustrated baker, flour-dusted apron", "boundaries": ["diet advice"], "pillars": ["bread science"],
}
SPEC = "\n\n".join(
    [f"{heading}\nbody" for heading in onboarding.SECTIONS[:-1]]
    + ["## Avatar JSON\n```json\n" + json.dumps(AVATAR) + "\n```"]
)


class RecordingModel(GenericFakeChatModel):
    calls: list = []

    def _generate(self, messages, *args, **kwargs):
        self.calls.append(messages)
        return super()._generate(messages, *args, **kwargs)


def fake(*replies: str) -> RecordingModel:
    model = RecordingModel(messages=iter(AIMessage(r) for r in replies))
    model.calls = []
    return model


def test_onboarding_stage_is_registered_last():
    assert STAGES[-1] == "onboarding"
    assert parse_stage("[stage:Onboarding] me") == "onboarding"
    assert "onboarding" in prompts.SUPERVISOR


def test_onboarding_routes_profile_then_spec_with_all_sections():
    model = fake("## Creator profile (extracted)\n- niche: baking", SPEC)
    out = build_graph(model).invoke({"input": "[stage:onboarding] I'm Maya, a baker"})
    assert out["stage"] == "onboarding" and len(model.calls) == 2
    assert "onboarding interviewer" in model.calls[0][0].content
    assert "avatar architect" in model.calls[1][0].content
    assert "Creator profile (extracted)" in model.calls[1][1].content  # spec step sees the extracted profile
    assert out["output"].startswith("# PersonaLab - Onboarding")
    assert onboarding.missing_sections(out["output"]) == []
    assert onboarding.extract_avatar(out["output"]) == AVATAR
    assert "Avatar JSON status" not in out["output"]


def test_untagged_onboarding_request_is_classified():
    model = fake("onboarding", "profile", SPEC)
    out = build_graph(model).invoke({"input": "help me build a virtual avatar of myself"})
    assert out["stage"] == "onboarding" and len(model.calls) == 3


def test_unparseable_avatar_json_is_flagged():
    model = fake("profile", "## Avatar profile\nno json here")
    out = build_graph(model).invoke({"input": "[stage:onboarding] x"})
    assert "Avatar JSON status" in out["output"]


def test_extract_avatar_parsing():
    assert onboarding.extract_avatar(SPEC) == AVATAR
    assert onboarding.extract_avatar("## Avatar JSON\n```\n" + json.dumps(AVATAR) + "\n```") == AVATAR  # no language tag
    other = "```json\n{\"unrelated\": 1}\n```\n## Avatar JSON\n```json\n" + json.dumps(AVATAR) + "\n```"
    assert onboarding.extract_avatar(other) == AVATAR  # heading wins over earlier unrelated blocks
    assert onboarding.extract_avatar("```json\n" + json.dumps(AVATAR) + "\n```") == AVATAR  # pasted without heading
    assert onboarding.extract_avatar("## Avatar JSON\n```json\n{broken\n```") is None
    assert onboarding.extract_avatar("```json\n[1, 2]\n```") is None
    assert onboarding.extract_avatar("") is None and onboarding.extract_avatar(None) is None  # type: ignore[arg-type]
    assert onboarding.avatar_context("nothing") == ""
    assert "@mayamakes" in onboarding.avatar_context(SPEC)


def test_create_and_scripts_prompts_receive_avatar_rule():
    brief = "[stage:create] persona from my avatar\n" + SPEC
    model = fake("## Persona card\nMaya", "## Reel (8 seconds)\nhook")
    build_graph(model, image_generator=lambda *a, **k: []).invoke({"input": brief})
    assert all(prompts.AVATAR_REUSE_RULE in call[0].content for call in model.calls)
    assert "@mayamakes" in model.calls[0][1].content
    plain = fake("## Posting calendar")
    build_graph(plain).invoke({"input": "[stage:schedule] plan"})
    assert prompts.AVATAR_REUSE_RULE not in plain.calls[0][0].content


def test_offers_json_shape_has_onboarding_and_no_analyze():
    data = json.loads(OFFERS.read_text(encoding="utf-8"))
    offers = data["offers"]
    titles = [offer["title"] for offer in offers]
    assert not any(title.startswith("Analyze") for title in titles)
    assert all("[stage:analyze]" not in offer["prompt"] for offer in offers)
    assert titles[0] == "Onboarding: Build Your Virtual Avatar"
    card = offers[0]
    assert card["prompt"].startswith("[stage:onboarding]")
    for field in ("Name / handle", "Niche", "5 interests", "Values", "story", "Expertise", "Signature phrases", "Likes / dislikes",
                  "Audience", "Moat", "Boundaries", "Look preferences", "Voice preferences"):
        assert field in card["prompt"], field
    allowed = {"pdf", "image", "slides", "doc", "sheet", "text", "html"}
    for offer in offers:
        for key in ("title", "prompt", "category", "description", "deliverable"):
            assert isinstance(offer[key], str) and offer[key].strip(), key
        assert offer["outputs"] and all(set(o) == {"type"} and o["type"] in allowed for o in offer["outputs"])
    assert isinstance(data["channels"], dict)
    assert isinstance(data["profile"]["llm"], list) and all(isinstance(x, str) for x in data["profile"]["llm"])
    assert isinstance(data["profile"]["hosting"], str)
