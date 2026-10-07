"""Hosted-deployment knobs: DATA_DIR, MEDIA_PUBLIC / PUBLIC_MEDIA_BASE_URL, HOSTED path hiding, bind address."""
from fastapi.testclient import TestClient

from crest_graph import config, media, server, store, video
from crest_graph.graph import media_section, video_section

import test_media
import test_video

RUN = "a" * 32
PUBLIC = "https://graph-xyz.up.railway.app"


def test_data_dir_defaults_to_local_and_follows_env(tmp_path, monkeypatch):
    test_media.settings(tmp_path, monkeypatch)
    assert config.data_dir() == tmp_path / ".local"
    assert media.media_root() == tmp_path / ".local" / "media"
    test_media.settings(tmp_path, monkeypatch, DATA_DIR="vol")
    assert config.data_dir() == tmp_path / "vol"
    absolute = tmp_path / "data"
    test_media.settings(tmp_path, monkeypatch, DATA_DIR=str(absolute))
    assert media.media_root() == absolute / "media"
    assert store.default_path() == absolute / "personalab.db"
    test_media.settings(tmp_path, monkeypatch, DATA_DIR=str(absolute), PERSONALAB_DB=str(tmp_path / "x.db"))
    assert store.default_path() == tmp_path / "x.db"


def test_bind_address_defaults_to_loopback(monkeypatch):
    values = {}
    monkeypatch.setattr(config, "get", lambda name, default=None: values.get(name, default))
    assert (config.graph_host(), config.graph_port()) == ("127.0.0.1", 21951)
    values.update(PORT="8080", CREST_GRAPH_HOST="::")
    assert (config.graph_host(), config.graph_port()) == ("::", 8080)
    values.update(CREST_GRAPH_PORT="21960")
    assert config.graph_port() == 21960


def test_media_public_serves_remote_clients_but_stays_strict(tmp_path, monkeypatch):
    test_media.settings(tmp_path, monkeypatch, MEDIA_PUBLIC="1")
    [saved] = media.generate_images(["a"], None, run_id=RUN, client=test_media.transport([test_media.image_response(test_media.PNG)]))
    remote = TestClient(server.app, client=("203.0.113.9", 5000))
    ok = remote.get(saved.url_path)
    assert ok.status_code == 200 and ok.content == test_media.PNG
    (tmp_path / ".local" / "media" / RUN / "notes.txt").write_text("x")
    for bad in (f"/media/{RUN}/..%2F..%2Fsecret.png", f"/media/{RUN}/notes.txt", f"/media/{RUN}/x.png", f"/media/{'b' * 32}/{saved.name}"):
        assert remote.get(bad).status_code == 404
    test_media.settings(tmp_path, monkeypatch)
    assert remote.get(saved.url_path).status_code == 403


def test_public_base_url_in_media_markdown(tmp_path, monkeypatch):
    def generator(prompts, reference, run_id, **_):
        return [media.MediaFile(run_id, f"0{i}-{'c' * 16}.png", tmp_path / "x.png", "d" * 64, "image/png", p) for i, p in enumerate(prompts)]

    test_media.settings(tmp_path, monkeypatch, MEDIA_PUBLIC="1", PUBLIC_MEDIA_BASE_URL=PUBLIC + "/")
    section = media_section(test_media.PERSONA, test_media.CONTENT, generator)
    assert f"1. Reference portrait: {PUBLIC}/media/" in section and "127.0.0.1" not in section
    assert "public links" in section
    # PUBLIC_MEDIA_BASE_URL without MEDIA_PUBLIC=1 keeps loopback links.
    test_media.settings(tmp_path, monkeypatch, PUBLIC_MEDIA_BASE_URL=PUBLIC)
    assert "http://127.0.0.1:21951/media/" in media_section(test_media.PERSONA, test_media.CONTENT, generator)


def _video_state_and_maker(tmp_path):
    frames = test_video.keyframes(tmp_path)
    state = {"content": test_video.CONTENT, "media_files": [{"path": str(p), "scene": i} for i, p in enumerate(frames)], "media_run": RUN}
    secret_path = tmp_path / "srv" / "reel.mp4"

    def maker(scenes, keyframes, *, run_id, budget_usd):
        return video.VideoResult(secret_path, f"/media/{run_id}/reel.mp4", 16.3, 2_000_000, "e" * 64, 720, 1280, "ffmpeg slideshow",
                                 0, len(scenes), "none", 0.0, ["still"] * len(scenes))

    return state, maker, secret_path


def test_hosted_video_section_hides_server_paths(tmp_path, monkeypatch):
    state, maker, secret_path = _video_state_and_maker(tmp_path)
    test_video.settings(tmp_path, monkeypatch, TREND_CREATE_SWARM_SIZE="0")
    local = video_section(state, maker)
    assert f"- File: `{secret_path}`" in local and "http://127.0.0.1:21951/media/" in local
    test_video.settings(tmp_path, monkeypatch, TREND_CREATE_SWARM_SIZE="0", HOSTED="1", MEDIA_PUBLIC="1", PUBLIC_MEDIA_BASE_URL=PUBLIC)
    hosted = video_section(state, maker)
    assert str(secret_path) not in hosted and str(tmp_path) not in hosted and "File:" not in hosted
    assert f"- Reel: {PUBLIC}/media/{RUN}/reel.mp4" in hosted and "SHA-256: `" + "e" * 64 in hosted
