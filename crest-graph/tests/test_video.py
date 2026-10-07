import json
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from crest_graph import config, media, server, trends, video
from crest_graph.graph import build_graph, has_pasted_trends, video_section

from test_graph import fake
from test_trends import CITES, REAL, no_page, payload, searcher_returning, trend

RUN = "b" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

PERSONA = """## Persona card
- **Name:** Nova Lin (invented)
- **Image-generation reference prompt:** Portrait of Nova, an original AI character with a cropped silver bob, teal jacket
"""

CONTENT = f"""## Trend pick
- Trend: kpop dance challenge
- URL: {REAL}
- Why it fits: high-energy movement suits a fitness persona

## Reel / video ad script
Title: 10-minute kpop cardio
Total length: 16 seconds

### Scene 1 (0-4s)
- Visual prompt: Nova in teal activewear striking the opening kpop pose on a rooftop at sunrise, vertical 9:16
- Motion: slow push-in
- On-screen text: Cardio, but make it kpop
- Voiceover: Ten minutes, one chorus, zero excuses.

### Scene 2 (4-8s)
- **Visual prompt:** Nova mid-jump, arms up, city skyline behind, golden light
- **On-screen text:** Burn 100 cal [verify]
- **Voiceover:** Follow the beat, not the clock.

### Scene 3 (8-12s)
- Visual prompt: close-up of Nova laughing, towel on shoulder
- On-screen text: Save this for tomorrow
- Voiceover: Save it, then try it with me tomorrow.

### Scene 4 (12-16s)
- Visual prompt: Nova pointing at camera, sunrise flare
- On-screen text: Follow for day 2
- Voiceover: Follow for day two.

## Caption & CTA
Dance cardio for busy mornings #kpopdance

## 7-day post plan
| Day | Format |
|---|---|
| 1 | reel |
"""


def settings(tmp_path, monkeypatch, **values):
    base = {"OPENROUTER_API_KEY": "sk-test", "CREST_GRAPH_PORT": "21951", "VOICE_ENGINE": "none"}
    base.update(values)
    monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(config, "get", lambda name, default=None: base.get(name, default))


class FakeFFmpeg:
    """Stands in for subprocess.run: writes the output file of each encode and answers `ffmpeg -i` probes."""

    def __init__(self, reel_seconds: float = 12.3, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.reel_seconds = reel_seconds
        self.fail_on = fail_on

    def __call__(self, args, cwd=None, capture_output=True, timeout=None):
        self.calls.append(list(args))
        if len(args) == 4 and args[2] == "-i":  # probe
            name = Path(args[3]).name
            if name.startswith("vo-"):
                text = "Duration: 00:00:02.50, start: 0\n  Stream #0:0: Audio: mp3, 24000 Hz"
            else:
                text = (f"Duration: 00:00:{self.reel_seconds:05.2f}, start: 0\n  Stream #0:0(und): Video: h264 (High), yuv420p, 720x1280, 30 fps\n"
                        "  Stream #0:1(und): Audio: aac (LC), 44100 Hz, stereo")
            return subprocess.CompletedProcess(args, 1, b"", text.encode())
        joined = " ".join(args)
        if self.fail_on and self.fail_on in joined:
            return subprocess.CompletedProcess(args, 1, b"", b"Error while decoding stream")
        (Path(cwd) / args[-1]).write_bytes(MP4)
        return subprocess.CompletedProcess(args, 0, b"", b"")


def keyframes(tmp_path, n=4):
    paths = []
    for i in range(n):
        path = tmp_path / f"kf{i}.png"
        path.write_bytes(PNG)
        paths.append(path)
    return paths


def video_api(models: list[dict], log: list, *, status="completed", cost=0.12, tts=b"ID3" + b"\x00" * 200):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        log.append((request.method, path))
        if path.endswith("/videos/models"):
            return httpx.Response(200, json={"data": models})
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": video.DEFAULT_TTS_MODEL, "pricing": {"prompt": "0.000015"}}]})
        if path.endswith("/audio/speech"):
            return httpx.Response(200, content=tts, headers={"content-type": "audio/mpeg"})
        if request.method == "POST" and path.endswith("/videos"):
            body = json.loads(request.content)
            assert body["frame_images"][0]["frame_type"] == "first_frame"
            assert body["frame_images"][0]["image_url"]["url"].startswith("data:image/png;base64,")
            assert body["aspect_ratio"] == "9:16" and body["generate_audio"] is False
            return httpx.Response(202, json={"id": f"gen-vid-{len(log)}", "status": "pending"})
        if path.endswith("/content"):
            return httpx.Response(200, content=MP4, headers={"content-type": "video/mp4"})
        return httpx.Response(200, json={"status": status, "usage": {"cost": cost}, "error": "policy" if status == "failed" else None})

    return httpx.Client(transport=httpx.MockTransport(handler))


GROK = {
    "id": video.DEFAULT_VIDEO_MODEL,
    "supported_durations": list(range(1, 16)),
    "supported_resolutions": ["480p", "720p", "1080p"],
    "supported_aspect_ratios": ["16:9", "9:16"],
    "supported_frame_images": ["first_frame"],
    "pricing_skus": {"cents_per_image_input": "1", "cents_per_video_output_second_720p": "3"},
}


# ---------------------------------------------------------------- parsing


def test_scene_and_trend_parsing():
    scenes = video.parse_scenes(CONTENT)
    assert [(s.start, s.end) for s in scenes] == [(0, 4), (4, 8), (8, 12), (12, 16)]
    assert scenes[0].visual.startswith("Nova in teal activewear") and scenes[0].motion == "slow push-in"
    assert scenes[1].on_screen == "Burn 100 cal [verify]" and scenes[1].voiceover == "Follow the beat, not the clock."
    assert video.trend_pick(CONTENT) == ("kpop dance challenge", REAL)
    table = "## Reel / video ad script\n| Time | Visual prompt | On-screen text | Voiceover |\n|---|---|---|---|\n| 0-3s | Nova waves | Hi | Hello |\n| 3-6s | Nova runs | Go | Let's go |\n"
    assert [(s.visual, s.end) for s in video.parse_scenes(table)] == [("Nova waves", 3), ("Nova runs", 6)]
    assert video.parse_scenes("## Reel\nno scenes here") == []
    two_tables = "| Do | Don't |\n|---|---|\n| a | b |\n\n| # | Time | Shot | On-screen text | Voiceover |\n|---|---|---|---|---|\n| 1 | 0:00–0:05 | Nova at counter | POV | Hi |\n"
    [only] = video.parse_scenes(two_tables)
    assert only.visual == "Nova at counter" and only.end == 5 and only.voiceover == "Hi"
    long_name = CONTENT.replace("- Trend: kpop dance challenge", "- Trend: Home cafe counter setup (creators carve out a dedicated station and film it as a ritual)")
    assert video.trend_pick(long_name)[0] == "Home cafe counter setup"


def test_safety_filter_allows_negated_safety_phrasing():
    for ok in ("Portrait of Mira, not based on any real person", "Negative: celebrity likeness, logos", "no real person's likeness"):
        assert media.check_prompt(ok)
    for bad in ("a celebrity lookalike of a pop star", "not blurry, a lookalike of a famous actor", "face swap onto a real person"):
        with pytest.raises(media.MediaError, match="real-person"):
            media.check_prompt(bad)
    assert has_pasted_trends("brief\n## Hot trends right now\n| 1 |") and has_pasted_trends("## Script 1: Morning reset")
    assert not has_pasted_trends("fitness coach persona for Gen Z")


def test_video_pricing_is_read_from_skus():
    assert video._sku_usd(GROK["pricing_skus"], "720p") == (0.03, 0.01)
    assert video._sku_usd({"image_to_video_duration_seconds_720p": "0.10", "text_to_video_duration_seconds_720p": "0.08"}, "720p")[0] == 0.10
    assert video._sku_usd({"duration_seconds": "0.084", "duration_seconds_with_audio": "0.126"}, "720p")[0] == 0.084
    assert video._sku_usd({"video_tokens": "0.0000035"}, "720p")[0] is None


# ---------------------------------------------------------------- ffmpeg command construction


def test_ffmpeg_commands_are_well_formed():
    caps = video.caption_filters(["Cardio, but", "make it kpop"], ["cap-00-0.txt", "cap-00-1.txt"], 720, 1280, 46, "C:/Windows/Fonts/arialbd.ttf")
    assert len(caps) == 2 and "fontfile='C\\:/Windows/Fonts/arialbd.ttf'" in caps[0] and "textfile=cap-00-0.txt" in caps[0]
    ys = [int(c.rsplit("y=", 1)[1]) for c in caps]
    assert all(1280 * 0.15 <= y <= 1280 * 0.64 for y in ys) and ys[0] < ys[1]  # inside the Reels safe area
    image = video.segment_command("ffmpeg", "kf.png", "image", 4.0, "seg-00.mp4", index=0, width=720, height=1280, captions=caps, font=None, font_px=46)
    chain = image[image.index("-vf") + 1]
    assert "scale=1440:2560" in chain and "zoompan=" in chain and "d=120" in chain and "s=720x1280" in chain
    assert chain.index("zoompan") < chain.index("drawtext") and chain.endswith("format=yuv420p,setsar=1")
    assert image[-1] == "seg-00.mp4" and "-an" in image and "libx264" in image
    clip = video.segment_command("ffmpeg", "clip.mp4", "clip", 4.5, "seg-01.mp4", index=1, width=720, height=1280, captions=[], font=None, font_px=46)
    clip_chain = clip[clip.index("-vf") + 1]
    assert "crop=720:1280" in clip_chain and "tpad=stop_mode=clone" in clip_chain and "zoompan" not in clip_chain

    durations = [4.35, 4.35, 4.35, 4.0]
    cmd = video.assemble_command("ffmpeg", ["seg-00.mp4", "seg-01.mp4", "seg-02.mp4", "seg-03.mp4"], durations, [(0, "vo-00.mp3"), (2, "vo-02.mp3")], "reel.mp4")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.35:offset=4.000" in graph and "offset=8.000" in graph and "offset=12.000" in graph
    assert "[4:a]" in graph and "adelay=150|150" in graph and "[5:a]" in graph and "adelay=8150|8150" in graph
    assert "amix=inputs=2:normalize=0" in graph
    for flag in ("-c:v", "libx264", "-c:a", "aac", "+faststart", "yuv420p"):
        assert flag in cmd
    assert cmd[cmd.index("-t") + 1] == f"{video.total_length(durations):.3f}" == "16.000"
    silent = video.assemble_command("ffmpeg", ["a.mp4"], [5.0], [], "reel.mp4")
    assert "anullsrc=r=44100:cl=stereo" in silent[silent.index("-filter_complex") + 1]


def test_durations_fit_short_form_window_7_to_15s():
    long = [video.Scene(i, i * 8, i * 8 + 8, "x") for i in range(6)]
    capped = video.plan_durations(long, {i: 7.9 for i in range(6)})
    assert video.MIN_REEL_SECONDS <= video.total_length(capped) <= video.MAX_REEL_SECONDS
    assert all(d >= 1.0 for d in capped)
    many = [video.Scene(i, i * 5, i * 5 + 5, "x") for i in range(video.MAX_REEL_SCENES)]
    assert video.total_length(video.plan_durations(many, {})) <= video.MAX_REEL_SECONDS
    short = video.plan_durations([video.Scene(0, 0, 2, "x"), video.Scene(1, 2, 4, "x")], {})
    assert video.MIN_REEL_SECONDS <= video.total_length(short) <= video.MAX_REEL_SECONDS
    within = video.plan_durations([video.Scene(0, 0, 4, "x"), video.Scene(1, 4, 8, "x"), video.Scene(2, 8, 12, "x")], {0: 3.0})
    assert within == [4.35, 4.35, 4.0]  # already in the window: planned lengths kept


def test_final_encode_caps_bitrate():
    cmd = video.assemble_command("ffmpeg", ["a.mp4"], [10.0], [], "reel.mp4")
    assert cmd[cmd.index("-maxrate") + 1] == video.MAX_VIDEO_BITRATE and "-bufsize" in cmd


def test_compress_targets_under_100mb(tmp_path):
    src = tmp_path / "reel.mp4"
    src.write_bytes(b"x")
    calls = []

    def runner(args, cwd, **_):
        calls.append(args)
        (Path(cwd) / args[-1]).write_bytes(b"small")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    out = video.compress("ffmpeg", src, 15.0, runner)
    assert out.name == "reel-small.mp4" and out.read_bytes() == b"small"
    kbps = int(calls[0][calls[0].index("-b:v") + 1].rstrip("k"))
    assert (kbps + 128) * 1000 * 15 / 8 < video.MAX_REEL_BYTES


# ---------------------------------------------------------------- make_reel paths


def test_ai_video_model_path(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, VOICE_ENGINE="openrouter")
    log: list = []
    runner = FakeFFmpeg()
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    result = video.make_reel(video.parse_scenes(CONTENT), keyframes(tmp_path), run_id=RUN, budget_usd=2.0, runner=runner,
                             client=video_api([GROK], log), sleep=lambda s: None)
    assert result.path == tmp_path / ".local" / "media" / RUN / "reel.mp4" and result.path.read_bytes() == MP4
    assert result.url_path == f"/media/{RUN}/reel.mp4" and result.ai_clips == 4
    assert result.path_used.startswith("AI video model (x-ai/grok-imagine-video-1.5-lite")
    assert result.scene_sources == ["AI clip"] * 4 and result.voice.startswith("OpenRouter TTS")
    assert result.cost_usd == pytest.approx(4 * 0.12 + 0.00153, abs=0.001)  # reported clip cost + TTS chars * price
    assert sum(1 for m, p in log if m == "POST" and p.endswith("/videos")) == 4
    assert not (tmp_path / ".local" / "media" / RUN / "work").exists()  # intermediates removed
    assert result.duration == 12.3 and result.width == 720 and len(result.sha256) == 64


def test_falls_back_to_local_assembly_when_video_model_unavailable(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    log: list = []
    runner = FakeFFmpeg()
    result = video.make_reel(video.parse_scenes(CONTENT), keyframes(tmp_path), run_id=RUN, budget_usd=2.0, runner=runner,
                             client=video_api([], log), sleep=lambda s: None)
    assert result.ai_clips == 0 and result.path_used.startswith("assembled locally with ffmpeg from 4 scene keyframes")
    assert any("is not available on OpenRouter" in n for n in result.notes)
    assert result.voice.startswith("none (silent AAC track)") and result.cost_usd == 0
    assert not any(m == "POST" for m, _ in log)
    encodes = [c for c in runner.calls if "-vf" in c]
    assert len(encodes) == 4 and all("zoompan=" in c[c.index("-vf") + 1] for c in encodes)


def test_budget_and_failed_clips_degrade_to_hybrid(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, VIDEO_MAX_CLIPS="4")
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    log: list = []
    # 4s clip at $0.03/s + $0.01 image = $0.13 -> a $0.30 budget affords 2 clips
    result = video.make_reel(video.parse_scenes(CONTENT), keyframes(tmp_path), run_id=RUN, budget_usd=0.30, runner=FakeFFmpeg(),
                             client=video_api([GROK], log), sleep=lambda s: None)
    assert result.ai_clips == 2 and result.path_used.startswith("hybrid") and result.scene_sources[2:] == ["keyframe (Ken Burns)"] * 2
    failed = video.make_reel(video.parse_scenes(CONTENT), keyframes(tmp_path), run_id=RUN, budget_usd=2.0, runner=FakeFFmpeg(),
                             client=video_api([GROK], [], status="failed"), sleep=lambda s: None)
    assert failed.ai_clips == 0 and any("video job failed" in n for n in failed.notes)
    none_left = video.make_reel(video.parse_scenes(CONTENT), keyframes(tmp_path), run_id=RUN, budget_usd=0.0, runner=FakeFFmpeg(),
                                client=video_api([GROK], []), sleep=lambda s: None)
    assert any("budget guard" in n for n in none_left.notes)


def test_make_reel_errors_are_reasons_not_crashes(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, VIDEO_AI="off")
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    scenes = video.parse_scenes(CONTENT)
    with pytest.raises(video.VideoError, match="no keyframe"):
        video.make_reel(scenes, [None] * 4, run_id=RUN, budget_usd=1, runner=FakeFFmpeg())
    with pytest.raises(video.VideoError, match="no parseable reel scenes"):
        video.make_reel([], keyframes(tmp_path), run_id=RUN, budget_usd=1, runner=FakeFFmpeg())
    with pytest.raises(video.VideoError, match="ffmpeg failed on scene 1"):
        video.make_reel(scenes, keyframes(tmp_path), run_id=RUN, budget_usd=1, runner=FakeFFmpeg(fail_on="seg-00.mp4"))
    with pytest.raises(video.VideoError, match="failed verification"):
        video.make_reel(scenes, keyframes(tmp_path), run_id=RUN, budget_usd=1, runner=FakeFFmpeg(reel_seconds=75))
    with pytest.raises(video.VideoError, match="invalid run id"):
        video.make_reel(scenes, keyframes(tmp_path), run_id="../x", budget_usd=1, runner=FakeFFmpeg())


# ---------------------------------------------------------------- graph integration


def test_create_pipeline_order_and_video_section(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, TREND_CREATE_SWARM_SIZE="2")
    order: list[str] = []
    search = searcher_returning(payload(trend("kpop dance challenge", REAL)), citations=CITES, cost=0.002)

    def searching(*a, **k):
        order.append("trend_swarm")
        return search(*a, **k)

    def generator(prompts, reference, run_id, aspect_ratio=None):
        order.append("media_agent")
        assert aspect_ratio == "9:16" and len(prompts) == 5 and prompts[1].startswith("Nova in teal activewear")
        files = []
        for i, p in enumerate(prompts):
            path = tmp_path / f"{i}.png"
            path.write_bytes(PNG)
            files.append(media.MediaFile(run_id, f"0{i}-{'c' * 16}.png", path, "d" * 64, "image/png", p, 0.04))
        return files

    seen = {}

    def maker(scenes, frames, *, run_id, budget_usd):
        order.append("video_agent")
        seen.update(scenes=scenes, frames=frames, budget=budget_usd, run=run_id)
        return video.VideoResult(tmp_path / "reel.mp4", f"/media/{run_id}/reel.mp4", 16.3, 2_000_000, "e" * 64, 720, 1280,
                                 "AI video model (x-ai/grok-imagine-video-1.5-lite, image-to-video from each scene keyframe), assembled with ffmpeg",
                                 4, 4, "OpenRouter TTS (m, voice en-US-Harper)", 0.5, ["AI clip"] * 4)

    model = fake("## Persona card\n" + PERSONA, CONTENT)
    out = build_graph(model, image_generator=generator, trend_searcher=searching, page_fetcher=no_page, video_maker=maker).invoke(
        {"input": "[stage:create] fitness persona, 4 scenes"}
    )
    assert order == ["trend_swarm", "trend_swarm", "media_agent", "video_agent"]
    assert len(model.calls) == 2 and REAL in model.calls[1][1].content  # content agent sees the cited trend analysis
    assert [f.name for f in seen["frames"]] == ["1.png", "2.png", "3.png", "4.png"] and len(seen["scenes"]) == 4
    assert seen["budget"] == pytest.approx(3.0 - 0.004 - 0.2)  # MAX_USD_PER_TASK minus trend and image spend
    text = out["output"]
    for heading in ("## Persona card", "## Trend pick", "## Reel / video ad script", "## Generated media", "## Video", "# Trend analysis used"):
        assert heading in text
    video_part = text.split("## Video")[1]
    assert f"- Reel: http://127.0.0.1:21951/media/{seen['run']}/reel.mp4" in video_part
    assert f"Based on trend: kpop dance challenge - {REAL} (URL verified" in video_part
    assert "Length: 16.3 s" in video_part and "Path used: AI video model" in video_part and "AI disclosure" in video_part
    assert "2. Scene 1 keyframe (0-4s)" in text


def test_create_skips_swarm_when_brief_has_trend_report(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    calls = []
    brief = f"[stage:create] fitness persona\n\n## Hot trends right now\n| 1 | kpop dance challenge | {REAL} |"
    out = build_graph(fake(PERSONA, CONTENT), image_generator=lambda *a, **k: [], trend_searcher=lambda *a, **k: calls.append(1),
                      page_fetcher=no_page, video_maker=video.make_reel).invoke({"input": brief})
    assert calls == [] and "video not generated: no keyframe images were generated" in out["output"]
    assert "(URL verified against the cited trend analysis)" in out["output"]  # URL found in the pasted report


def test_video_failure_never_fails_the_task(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch, TREND_CREATE_SWARM_SIZE="0")
    state = {"content": CONTENT, "media_files": [{"path": str(p), "scene": i} for i, p in enumerate(keyframes(tmp_path))], "media_run": RUN}

    def broken(*a, **k):
        raise video.VideoError("ffmpeg not found (install imageio-ffmpeg or set FFMPEG_PATH)")

    assert video_section(state, broken).endswith("video not generated: ffmpeg not found (install imageio-ffmpeg or set FFMPEG_PATH)")
    assert "video not generated: video build failed (KeyError)" in video_section(state, lambda *a, **k: {}["x"])
    out = build_graph(fake(PERSONA, CONTENT), image_generator=lambda *a, **k: [], video_maker=broken).invoke({"input": "[stage:create] x"})
    assert out["output"].startswith("# PersonaLab - Create") and "video not generated:" in out["output"]
    settings(tmp_path, monkeypatch, VIDEO_GENERATION="off")
    assert video_section(state, broken).endswith("video not generated: VIDEO_GENERATION=off")


def test_unverified_trend_url_is_not_trusted(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    content = CONTENT.replace(REAL, "https://made-up.example.com/trend")
    cited = [{"trend": "kpop dance challenge", "evidence": [{"url": REAL}]}]
    section = video_section({"content": content, "trend_report": f"[1]({REAL})", "trends": cited}, lambda *a, **k: (_ for _ in ()).throw(video.VideoError("x")))
    assert "made-up.example.com" not in section and f"{REAL} (URL taken from the cited analysis" in section


# ---------------------------------------------------------------- serving


def test_reel_is_served_and_traversal_is_blocked(tmp_path, monkeypatch):
    settings(tmp_path, monkeypatch)
    folder = tmp_path / ".local" / "media" / RUN
    (folder / "work").mkdir(parents=True)
    (folder / "reel.mp4").write_bytes(MP4)
    (folder / "work" / "clip-00.mp4").write_bytes(MP4)
    (tmp_path / ".local" / "media" / "reel.mp4").write_bytes(MP4)
    local = TestClient(server.app, client=("127.0.0.1", 5000))
    ok = local.get(f"/media/{RUN}/reel.mp4")
    assert ok.status_code == 200 and ok.content == MP4 and ok.headers["content-type"] == "video/mp4"
    assert ok.headers["x-content-type-options"] == "nosniff"
    for bad in (f"/media/{RUN}/work%2Fclip-00.mp4", f"/media/{RUN}/clip-00.mp4", f"/media/{RUN}/..%2Freel.mp4", f"/media/{RUN}/reel.mp4.png",
                f"/media/{RUN}/REEL.mp4", f"/media/{RUN}/reel.mov", f"/media/{'c' * 32}/reel.mp4", "/media/../reel.mp4"):
        assert local.get(bad).status_code == 404, bad
    assert media.resolve_media_file(RUN, "work/clip-00.mp4") is None
    assert TestClient(server.app, client=("10.0.0.5", 5000)).get(f"/media/{RUN}/reel.mp4").status_code == 403


def test_trend_swarm_size_for_create(monkeypatch):
    monkeypatch.setenv("TREND_CREATE_SWARM_SIZE", "1")
    assert trends.swarm_size("create") == 1 and trends.pick_lenses("create", 1)[0].id == "niche"
    monkeypatch.delenv("TREND_CREATE_SWARM_SIZE")
    assert trends.swarm_size("create") == 2
