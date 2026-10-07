"""Reel / video-ad builder for the Create stage.

Strategy (each step degrades instead of failing):
1. AI video model via OpenRouter's async video API (POST /api/v1/videos, poll, download): one image-to-video clip
   per scene with the scene keyframe as the first frame. Capped by VIDEO_MAX_CLIPS and the remaining
   MAX_USD_PER_TASK budget. Scenes without a clip fall back to a Ken Burns move over their keyframe.
2. Voiceover per scene: OpenRouter TTS (/api/v1/audio/speech) -> Windows built-in TTS (System.Speech) -> silence.
3. ffmpeg assembles everything: 9:16 H.264 + AAC, crossfades, burned-in captions inside the Reels safe area.

The final file is PROJECT_DIR/.local/media/<run_id>/reel.mp4, served read-only on loopback by GET /media/<run>/reel.mp4.
Intermediate files live in a `work/` sub-folder that the media route never serves and that is removed afterwards.
"""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import math
import os
import re
import shutil
import subprocess
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from . import config, media

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_VIDEO_MODEL = "x-ai/grok-imagine-video-1.5-lite"
DEFAULT_TTS_MODEL = "microsoft/mai-voice-2.1-flash"
DEFAULT_TTS_VOICE = "en-US-Harper:MAI-Voice-2.1-Flash"
DEFAULT_USD_PER_VIDEO_SECOND = 0.20  # used only when live pricing is unparseable; deliberately pessimistic
DEFAULT_TTS_USD_PER_CHAR = 0.00003
REEL_NAME = "reel.mp4"
MAX_REEL_SECONDS = 60.0
MAX_VIDEO_BYTES = 200 * 1024 * 1024
FPS = 30
CROSSFADE = 0.35
SIZES = {"720x1280": (720, 1280), "1080x1920": (1080, 1920)}
FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
MOTION_SAFETY = (
    " Vertical 9:16 social video. Keep the same original fictional character from the first frame; do not depict or "
    "resemble any real, identifiable person. No logos, watermarks or on-screen text. Adults only, fully clothed."
)

Runner = Callable[..., subprocess.CompletedProcess]


class VideoError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Scene:
    index: int
    start: float
    end: float
    visual: str
    on_screen: str = ""
    voiceover: str = ""
    motion: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class VideoResult:
    path: Path
    url_path: str
    duration: float
    size_bytes: int
    sha256: str
    width: int
    height: int
    path_used: str
    ai_clips: int
    scenes: int
    voice: str
    cost_usd: float
    scene_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- settings helpers


def _float(name: str, default: float) -> float:
    try:
        value = float(config.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(config.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _off(name: str) -> bool:
    return (config.get(name, "on") or "on").strip().lower() in ("off", "0", "false", "no", "disabled")


def output_size() -> tuple[int, int]:
    return SIZES.get((config.get("VIDEO_SIZE", "720x1280") or "").strip().lower(), SIZES["720x1280"])


# ---------------------------------------------------------------- script parsing (LLM-free)

_TIME = re.compile(r"(\d{1,2}(?::\d{2})?(?:\.\d+)?)\s*s?\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2}(?::\d{2})?(?:\.\d+)?)\s*s?", re.I)
_SCENE_HEADING = re.compile(r"^\s{0,3}#{2,4}\s*(?:\*\*)?\s*scene\s*(\d+)\b(.*)$", re.I)
_URL = re.compile(r"https?://[^\s)\]>\"'|`]+")
_LABELS = {
    "visual": re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*(?:visual(?:\s+prompt)?|keyframe(?:\s+prompt)?|image\s+prompt)\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
    "motion": re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*(?:motion|camera(?:\s+motion)?)\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
    "on_screen": re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*(?:on[- ]screen\s+text|text\s+overlay|caption)\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
    "voiceover": re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*(?:voice[- ]?over|vo|narration)\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
}


def _seconds(token: str) -> float:
    if ":" in token:
        minutes, seconds = token.split(":", 1)
        return int(minutes) * 60 + float(seconds)
    return float(token)


def _clean(text: str) -> str:
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = " ".join(text.split()).strip(" -\u2013\u2014*_")
    if len(text) >= 2 and text[0] in "\"'\u201c" and text[-1] in "\"'\u201d":
        text = text[1:-1].strip()
    return text


def _times(text: str) -> tuple[float, float] | None:
    match = _TIME.search(text or "")
    if not match:
        return None
    start, end = _seconds(match.group(1)), _seconds(match.group(2))
    return (start, end) if end > start else None


def _scene_blocks(markdown: str) -> list[tuple[int, str, list[str]]]:
    blocks: list[tuple[int, str, list[str]]] = []
    for line in markdown.splitlines():
        heading = _SCENE_HEADING.match(line)
        if heading:
            blocks.append((int(heading.group(1)), heading.group(2), []))
        elif blocks:
            if re.match(r"^\s{0,3}#{1,3}\s+(?!scene)", line, re.I):
                blocks.append((-1, "", []))  # a non-scene heading ends the scene list
            else:
                blocks[-1][2].append(line)
    return [b for b in blocks if b[0] >= 0]


def _tables(markdown: str) -> list[list[str]]:
    tables, current = [], []
    for line in markdown.splitlines():
        if line.strip().startswith("|"):
            current.append(line.strip())
        elif current:
            tables.append(current)
            current = []
    return [t for t in [*tables, current] if len(t) >= 3]


def _table_scenes(markdown: str) -> list[dict]:
    """First table that has a time column and a visual/shot column (the scene table, not the post plan)."""
    cells = lambda row: [c.strip() for c in row.strip("|").split("|")]
    for rows in _tables(markdown):
        head = [h.lower() for h in cells(rows[0])]

        def column(*names: str) -> int | None:
            return next((i for i, h in enumerate(head) if any(n in h for n in names)), None)

        cols = {"time": column("time", "timestamp"), "visual": column("visual", "keyframe", "prompt", "shot"),
                "on_screen": column("on-screen", "on screen", "overlay", "text"), "voiceover": column("voice", "narration")}
        if cols["visual"] is None or cols["time"] is None:
            continue
        out = []
        for row in rows[2:]:
            parts = cells(row)
            get = lambda key: _clean(parts[cols[key]]) if cols[key] is not None and cols[key] < len(parts) else ""
            out.append({"time": get("time"), "visual": get("visual"), "on_screen": get("on_screen"), "voiceover": get("voiceover")})
        rows_ok = [r for r in out if r["visual"]]
        if rows_ok:
            return rows_ok
    return []


def parse_scenes(markdown: str, default_seconds: float = 4.0) -> list[Scene]:
    """Scenes of the reel script: '### Scene N (0-4s)' blocks with labelled lines, or a scene table."""
    raw: list[dict] = []
    for _, title, lines in _scene_blocks(markdown):
        item = {"time": title, "visual": "", "on_screen": "", "voiceover": "", "motion": ""}
        for line in lines:
            for key, label in _LABELS.items():
                match = label.match(line)
                if match and not item[key]:
                    item[key] = _clean(match.group(1))
                    break
            else:
                if not item["time"].strip() or not _times(item["time"]):
                    if _times(line):
                        item["time"] = line
        if item["visual"]:
            raw.append(item)
    if not raw:
        raw = _table_scenes(markdown)
    scenes: list[Scene] = []
    cursor = 0.0
    for index, item in enumerate(raw[:6]):
        span = _times(item.get("time", ""))
        length = (span[1] - span[0]) if span else default_seconds
        length = min(8.0, max(1.5, length))
        scenes.append(Scene(index, round(cursor, 2), round(cursor + length, 2), item["visual"][:1200],
                            item.get("on_screen", "")[:120], item.get("voiceover", "")[:300], item.get("motion", "")[:200]))
        cursor += length
    return scenes


def trend_pick(markdown: str) -> tuple[str, str | None]:
    """(trend name, URL) from the content's '## Trend pick' section, or the 'Trend used' line."""
    section = media._section(markdown, re.compile(r"trend (pick|used)", re.I)) or ""
    scope = section or markdown
    name = ""
    for line in scope.splitlines():
        match = re.match(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*trend(?:\s+used|\s+name)?\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", line, re.I)
        if match:
            name = _URL.sub("", _clean(match.group(1))).strip(" -\u2013\u2014()[]:")
            if len(name) > 60 and " (" in name:  # drop a long parenthetical description
                name = name.split(" (", 1)[0].strip()
            break
    url = next(iter(_URL.findall(section)), None) if section else None
    return name, (url.rstrip(".,;") if url else None)


# ---------------------------------------------------------------- binaries


def find_ffmpeg() -> str:
    explicit = config.get("FFMPEG_PATH")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # pip/uv-installable static build; no admin rights needed
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise VideoError("ffmpeg not found (install imageio-ffmpeg or set FFMPEG_PATH)") from None


def find_font() -> str | None:
    explicit = config.get("VIDEO_FONT_FILE")
    if explicit and Path(explicit).is_file():
        return explicit
    return next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)


def _filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter option value."""
    return "'" + path.replace("\\", "/").replace(":", "\\:").replace("'", "") + "'"


def _run(runner: Runner, args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    try:
        result = runner(args, cwd=str(cwd), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise VideoError(f"{Path(args[0]).stem} timed out after {int(timeout)}s") from None
    except OSError as error:
        raise VideoError(f"could not run {Path(args[0]).stem} ({type(error).__name__})") from None
    return result


def _stderr(result: subprocess.CompletedProcess) -> str:
    data = result.stderr or b""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)


def probe(ffmpeg: str, path: Path, runner: Runner = subprocess.run) -> dict:
    """Duration and streams from `ffmpeg -i` (works with static ffmpeg builds that ship no ffprobe)."""
    result = _run(runner, [ffmpeg, "-hide_banner", "-i", str(path)], path.parent, 60)
    text = _stderr(result)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    info = {"duration": 0.0, "video": None, "audio": None, "width": 0, "height": 0}
    if match:
        info["duration"] = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    video = re.search(r"Stream #\S+.*?Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})", text)
    if video:
        info.update(video=video.group(1), width=int(video.group(2)), height=int(video.group(3)))
    audio = re.search(r"Stream #\S+.*?Audio:\s*(\w+)", text)
    if audio:
        info["audio"] = audio.group(1)
    return info


# ---------------------------------------------------------------- ffmpeg command construction


def wrap_caption(text: str, width_px: int, font_px: int) -> list[str]:
    chars = max(10, int(width_px * 0.80 / (font_px * 0.56)))
    return textwrap.wrap(" ".join(text.split()), chars)[:3]


def caption_filters(lines: list[str], files: list[str], width: int, height: int, font_px: int, font: str | None) -> list[str]:
    """One centred drawtext per line; the block's bottom edge sits at 64% of the height (above the Reels UI zone)."""
    line_h = int(font_px * 1.35)
    bottom = int(height * 0.64)
    top = bottom - line_h * len(lines)
    top = max(int(height * 0.15), top)  # never inside the top 15% (status bar / tabs)
    font_opt = f"fontfile={_filter_path(font)}:" if font else ""
    out = []
    for i, name in enumerate(files):
        out.append(
            f"drawtext={font_opt}textfile={name}:expansion=none:fontsize={font_px}:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw={max(8, font_px // 3)}:borderw=0:"
            f"x=(w-text_w)/2:y={top + i * line_h}"
        )
    return out


def segment_command(
    ffmpeg: str,
    source: str,
    kind: str,
    duration: float,
    out: str,
    *,
    index: int,
    width: int,
    height: int,
    captions: list[str],
    font: str | None,
    font_px: int,
) -> list[str]:
    """Build one scene segment (video only): an AI clip fitted to 9:16, or a Ken Burns move over a keyframe."""
    frames = max(1, int(round(duration * FPS)))
    if kind == "clip":
        args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source]
        chain = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={FPS},"
            f"tpad=stop_mode=clone:stop_duration={duration:.2f},trim=duration={duration:.3f},setpts=PTS-STARTPTS"
        )
    else:
        args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source]
        zoom = f"min(1+0.0009*on,1.14)" if index % 2 == 0 else f"max(1.14-0.0009*on,1.0)"
        pans = ("iw/2-(iw/zoom/2)", "(iw-iw/zoom)*on/{f}", "(iw-iw/zoom)*(1-on/{f})")
        x = pans[index % 3].format(f=frames)
        chain = (
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
            f"zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={FPS},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"
        )
    if captions:
        chain += "," + ",".join(captions)
    chain += ",format=yuv420p,setsar=1"
    return [*args, "-vf", chain, "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", out]


def scene_starts(durations: list[float], crossfade: float = CROSSFADE) -> list[float]:
    starts, cursor = [], 0.0
    for i, d in enumerate(durations):
        starts.append(round(cursor, 3))
        cursor += d - (crossfade if i < len(durations) - 1 else 0)
    return starts


def total_length(durations: list[float], crossfade: float = CROSSFADE) -> float:
    return round(sum(durations) - crossfade * max(0, len(durations) - 1), 3)


def assemble_command(
    ffmpeg: str,
    segments: list[str],
    durations: list[float],
    voices: list[tuple[int, str]],
    out: str,
    crossfade: float = CROSSFADE,
) -> list[str]:
    """Crossfade the segments, lay each scene's voiceover at its start, encode H.264 + AAC with faststart."""
    total = total_length(durations, crossfade)
    starts = scene_starts(durations, crossfade)
    args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for segment in segments:
        args += ["-i", segment]
    for _, path in voices:
        args += ["-i", path]
    filters: list[str] = []
    label = "[0:v]"
    for k in range(1, len(segments)):
        offset = sum(durations[:k]) - k * crossfade
        filters.append(f"{label}[{k}:v]xfade=transition=fade:duration={crossfade}:offset={offset:.3f}[x{k}]")
        label = f"[x{k}]"
    fade_out = max(0.0, total - 0.5)
    filters.append(f"{label}fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out:.3f}:d=0.5,format=yuv420p[vout]")
    if voices:
        mixed = []
        for j, (scene, _) in enumerate(voices):
            delay = int(round((starts[scene] + 0.15) * 1000))
            filters.append(f"[{len(segments) + j}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={delay}|{delay}[a{j}]")
            mixed.append(f"[a{j}]")
        filters.append(f"{''.join(mixed)}amix=inputs={len(mixed)}:normalize=0:duration=longest,apad,atrim=0:{total:.3f}[aout]")
    else:
        filters.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{total:.3f}[aout]")
    return [
        *args, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-t", f"{total:.3f}", "-movflags", "+faststart", out,
    ]


# ---------------------------------------------------------------- AI video model (OpenRouter)


@dataclass
class VideoModel:
    id: str
    durations: list[int]
    resolution: str
    usd_per_second: float
    usd_per_image: float
    priced: bool


def _sku_usd(skus: dict, resolution: str) -> tuple[float | None, float]:
    """(USD per output second, USD per input image) from OpenRouter pricing_skus; None when no per-second price."""
    def value(key: str) -> float | None:
        try:
            amount = float(skus[key])
        except (KeyError, TypeError, ValueError):
            return None
        return amount / 100 if key.startswith("cents") else amount

    res = resolution.lower()
    candidates = [k for k in skus if "second" in k and "reference" not in k and "continuation" not in k and "text_to_video" not in k]
    exact = [k for k in candidates if k.lower().endswith(res) and "with_audio" not in k]
    image_to_video = [k for k in exact if "image_to_video" in k]
    generic = [k for k in candidates if not re.search(r"\d+p|\dk", k.lower()) and "with_audio" not in k]
    without_audio = [k for k in generic if "without_audio" in k]
    for group in (image_to_video, exact, without_audio, generic):
        prices = [p for p in (value(k) for k in group) if p]
        if prices:
            per_image = value("cents_per_image_input") or 0.0
            return max(prices), per_image
    return None, value("cents_per_image_input") or 0.0


def pick_model(client: httpx.Client, model_id: str, wanted_resolution: str) -> VideoModel:
    response = client.get(f"{OPENROUTER_URL}/videos/models")
    response.raise_for_status()
    entry = next((m for m in response.json().get("data", []) if m.get("id") == model_id), None)
    if entry is None:
        raise VideoError(f"video model {model_id} is not available on OpenRouter")
    if "9:16" not in (entry.get("supported_aspect_ratios") or ["9:16"]):
        raise VideoError(f"video model {model_id} does not support 9:16")
    frames = entry.get("supported_frame_images")
    if frames is not None and "first_frame" not in frames:
        raise VideoError(f"video model {model_id} does not support image-to-video (first_frame)")
    resolutions = entry.get("supported_resolutions") or [wanted_resolution]
    order = [wanted_resolution, "720p", "768p", "480p", "1080p"]
    resolution = next((r for r in order if r in resolutions), resolutions[0])
    per_second, per_image = _sku_usd(entry.get("pricing_skus") or {}, resolution)
    durations = sorted(int(d) for d in (entry.get("supported_durations") or [4, 5, 6, 8]))
    if per_second is None:
        return VideoModel(model_id, durations, resolution, DEFAULT_USD_PER_VIDEO_SECOND, 0.01, False)
    return VideoModel(model_id, durations, resolution, per_second, per_image, True)


def clip_seconds(model: VideoModel, wanted: float) -> int:
    need = math.ceil(wanted - 1e-6)
    return next((d for d in model.durations if d >= need), model.durations[-1])


def _is_mp4(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == b"ftyp"


def generate_clip(client: httpx.Client, api_key: str, model: VideoModel, scene: Scene, keyframe: Path, out: Path,
                  *, poll_s: float, timeout_s: float, sleep: Callable[[float], None] = time.sleep) -> float | None:
    """Submit one image-to-video job, poll it, download the MP4. Returns the reported cost (None if not reported)."""
    image = keyframe.read_bytes()
    mime = media._sniff_mime(image) or "image/png"
    prompt = media.check_prompt(f"{scene.visual}. Motion: {scene.motion or 'slow cinematic push-in, subtle natural movement'}.")
    body = {
        "model": model.id,
        "prompt": prompt + MOTION_SAFETY,
        "duration": clip_seconds(model, scene.duration),
        "resolution": model.resolution,
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "frame_images": [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}, "frame_type": "first_frame"}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "PersonaLab"}
    response = client.post(f"{OPENROUTER_URL}/videos", json=body, headers=headers)
    if response.status_code >= 400:
        raise VideoError(media._api_error(response))
    job = response.json()
    job_id = str(job.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise VideoError("video API returned no job id")
    deadline = time.monotonic() + timeout_s
    status: dict = job
    while status.get("status") not in ("completed", "failed", "cancelled", "expired"):
        if time.monotonic() > deadline:
            raise VideoError(f"video job timed out after {int(timeout_s)}s")
        sleep(poll_s)
        poll = client.get(f"{OPENROUTER_URL}/videos/{job_id}", headers=headers)
        if poll.status_code >= 400:
            raise VideoError(media._api_error(poll))
        status = poll.json()
    if status.get("status") != "completed":
        raise VideoError(f"video job {status.get('status')}: {str(status.get('error') or '')[:160]}")
    content = client.get(f"{OPENROUTER_URL}/videos/{job_id}/content", params={"index": 0}, headers=headers, follow_redirects=True)
    if content.status_code >= 400:
        raise VideoError(media._api_error(content))
    if not _is_mp4(content.content) or len(content.content) > MAX_VIDEO_BYTES:
        raise VideoError("video API returned a file that is not an MP4")
    out.write_bytes(content.content)
    cost = (status.get("usage") or {}).get("cost")
    return float(cost) if isinstance(cost, (int, float)) else None


def ai_clips(scenes: list[Scene], keyframes: list[Path], work: Path, budget_usd: float, notes: list[str],
             client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep) -> tuple[dict[int, Path], float, str | None]:
    """Generate up to VIDEO_MAX_CLIPS clips within budget. Returns ({scene index: clip}, cost, model id or None)."""
    if _off("VIDEO_AI"):
        notes.append("AI video model skipped: VIDEO_AI=off")
        return {}, 0.0, None
    api_key = config.get("OPENROUTER_API_KEY")
    if not api_key:
        notes.append("AI video model skipped: OPENROUTER_API_KEY is not configured")
        return {}, 0.0, None
    model_id = config.get("VIDEO_MODEL_ID", DEFAULT_VIDEO_MODEL)
    owns = client is None
    http = client or httpx.Client(timeout=_float("VIDEO_HTTP_TIMEOUT_S", 120.0))
    try:
        try:
            model = pick_model(http, model_id, config.get("VIDEO_RESOLUTION", "720p"))
        except (httpx.HTTPError, ValueError) as error:
            notes.append(f"AI video model skipped: model list unavailable ({type(error).__name__})")
            return {}, 0.0, None
        except VideoError as error:
            notes.append(f"AI video model skipped: {error.reason}")
            return {}, 0.0, None
        if not model.priced:
            notes.append(f"video pricing unavailable; assumed ${model.usd_per_second:.2f}/s")
        estimates = [model.usd_per_second * clip_seconds(model, s.duration) + model.usd_per_image for s in scenes]
        wanted = min(len(scenes), _int("VIDEO_MAX_CLIPS", 4))
        chosen: list[int] = []
        planned = 0.0
        for i in range(wanted):
            if planned + estimates[i] > budget_usd + 1e-9:
                break
            chosen.append(i)
            planned += estimates[i]
        if not chosen:
            notes.append(f"AI video model skipped: budget guard (~${estimates[0]:.2f}/clip, ${budget_usd:.2f} left of MAX_USD_PER_TASK)")
            return {}, 0.0, model.id
        if len(chosen) < len(scenes):
            notes.append(f"AI clips for {len(chosen)} of {len(scenes)} scenes (VIDEO_MAX_CLIPS={_int('VIDEO_MAX_CLIPS', 4)}, budget ${budget_usd:.2f}); the rest use Ken Burns")
        poll_s, timeout_s = _float("VIDEO_POLL_S", 5.0), _float("VIDEO_TIMEOUT_S", 600.0)
        clips: dict[int, Path] = {}
        cost = 0.0

        def one(i: int) -> tuple[int, Path, float]:
            out = work / f"clip-{i:02d}.mp4"
            reported = generate_clip(http, api_key, model, scenes[i], keyframes[i], out, poll_s=poll_s, timeout_s=timeout_s, sleep=sleep)
            return i, out, reported if reported is not None else estimates[i]

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(chosen))) as pool:
            futures = [pool.submit(one, i) for i in chosen]
            for future in concurrent.futures.as_completed(futures):
                try:
                    i, path, spent = future.result()
                    clips[i] = path
                    cost += spent
                except VideoError as error:
                    notes.append(f"AI clip failed, scene uses Ken Burns instead: {error.reason}")
                except httpx.HTTPError as error:
                    notes.append(f"AI clip failed, scene uses Ken Burns instead: OpenRouter request failed ({type(error).__name__})")
                except media.MediaError as error:
                    notes.append(f"AI clip skipped: {error.reason}")
        return clips, round(cost, 4), model.id
    finally:
        if owns:
            http.close()


# ---------------------------------------------------------------- voiceover

WINDOWS_TTS = """param([string]$In, [string]$Out)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.Rate = 1; $s.SetOutputToWaveFile($Out); $s.Speak([IO.File]::ReadAllText($In)) } finally { $s.Dispose() }
"""


def _tts_price(client: httpx.Client, model_id: str) -> float:
    try:
        response = client.get(f"{OPENROUTER_URL}/models", params={"output_modalities": "speech"})
        response.raise_for_status()
        entry = next((m for m in response.json().get("data", []) if m.get("id") == model_id), None)
        price = float(((entry or {}).get("pricing") or {}).get("prompt") or 0)
        return price if price > 0 else DEFAULT_TTS_USD_PER_CHAR
    except (httpx.HTTPError, ValueError, TypeError):
        return DEFAULT_TTS_USD_PER_CHAR


def openrouter_voice(lines: dict[int, str], work: Path, client: httpx.Client | None = None) -> tuple[dict[int, Path], float, str]:
    api_key = config.get("OPENROUTER_API_KEY")
    if not api_key:
        raise VideoError("OPENROUTER_API_KEY is not configured")
    model = config.get("TTS_MODEL_ID", DEFAULT_TTS_MODEL)
    voice = config.get("TTS_VOICE", DEFAULT_TTS_VOICE)
    owns = client is None
    http = client or httpx.Client(timeout=_float("TTS_TIMEOUT_S", 60.0))
    try:
        per_char = _tts_price(http, model)
        out: dict[int, Path] = {}
        chars = 0
        for i, text in lines.items():
            response = http.post(
                f"{OPENROUTER_URL}/audio/speech",
                json={"model": model, "input": text, "voice": voice, "response_format": "mp3"},
                headers={"Authorization": f"Bearer {api_key}", "X-Title": "PersonaLab"},
            )
            if response.status_code >= 400:
                raise VideoError(media._api_error(response))
            if len(response.content) < 100 or response.headers.get("content-type", "").startswith("application/json"):
                raise VideoError("TTS returned no audio")
            path = work / f"vo-{i:02d}.mp3"
            path.write_bytes(response.content)
            out[i] = path
            chars += len(text)
        return out, round(chars * per_char, 5), f"OpenRouter TTS ({model}, voice {voice.split(':')[0]})"
    except httpx.HTTPError as error:
        raise VideoError(f"TTS request failed ({type(error).__name__})") from None
    finally:
        if owns:
            http.close()


def windows_voice(lines: dict[int, str], work: Path, runner: Runner = subprocess.run) -> tuple[dict[int, Path], float, str]:
    if os.name != "nt":
        raise VideoError("Windows built-in TTS is only available on Windows")
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        raise VideoError("PowerShell not found")
    script = work / "tts.ps1"
    script.write_text(WINDOWS_TTS, encoding="utf-8")
    out: dict[int, Path] = {}
    for i, text in lines.items():
        text_file, wav = work / f"vo-{i:02d}.txt", work / f"vo-{i:02d}.wav"
        text_file.write_text(text, encoding="utf-8")
        result = _run(runner, [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               "-In", str(text_file), "-Out", str(wav)], work, 60)
        if result.returncode != 0 or not wav.is_file() or wav.stat().st_size < 100:
            raise VideoError("Windows TTS produced no audio")
        out[i] = wav
    return out, 0.0, "Windows built-in TTS (System.Speech)"


def voiceover(lines: dict[int, str], work: Path, notes: list[str], runner: Runner = subprocess.run,
              client: httpx.Client | None = None) -> tuple[dict[int, Path], float, str]:
    if not lines:
        return {}, 0.0, "none (silent AAC track): the script has no voiceover lines"
    engine = (config.get("VOICE_ENGINE", "auto") or "auto").strip().lower()
    if engine in ("none", "off", "silent"):
        return {}, 0.0, "none (silent AAC track): VOICE_ENGINE=none"
    chain = {"openrouter": ["openrouter"], "windows": ["windows"]}.get(engine, ["openrouter", "windows"])
    for name in chain:
        try:
            if name == "openrouter":
                return openrouter_voice(lines, work, client)
            return windows_voice(lines, work, runner)
        except VideoError as error:
            notes.append(f"voiceover via {name} failed: {error.reason}")
    return {}, 0.0, "none (silent AAC track): every TTS option failed"


# ---------------------------------------------------------------- orchestration


def plan_durations(scenes: list[Scene], voice_lengths: dict[int, float]) -> list[float]:
    """Scene length = planned length, stretched so its voiceover fits before the crossfade; total capped at 60 s."""
    out = []
    for i, scene in enumerate(scenes):
        tail = CROSSFADE if i < len(scenes) - 1 else 0.0
        need = voice_lengths.get(i, 0.0) + 0.15 + 0.25 + tail
        out.append(round(min(8.0, max(scene.duration + tail, need, 1.5)), 2))
    total = total_length(out)
    if total > MAX_REEL_SECONDS:
        scale = MAX_REEL_SECONDS / total
        out = [round(max(1.0, d * scale), 2) for d in out]
    return out


def make_reel(
    scenes: list[Scene],
    keyframes: list[Path | None],
    *,
    run_id: str,
    budget_usd: float,
    runner: Runner = subprocess.run,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> VideoResult:
    """Build reel.mp4 for the run. Raises VideoError; callers turn that into 'video not generated: <reason>'."""
    if not media.RUN_ID.fullmatch(run_id or ""):
        raise VideoError("invalid run id")
    if not scenes:
        raise VideoError("the content has no parseable reel scenes")
    usable = [k for k in keyframes if k is not None and Path(k).is_file()]
    if not usable:
        raise VideoError("no keyframe images were generated")
    frames: list[Path] = []
    last = usable[0]
    for i in range(len(scenes)):
        candidate = keyframes[i] if i < len(keyframes) else None
        last = Path(candidate) if candidate is not None and Path(candidate).is_file() else last
        frames.append(last)
    ffmpeg = find_ffmpeg()
    folder = media.media_root() / run_id
    work = folder / "work"
    work.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    try:
        clips, clip_cost, model_id = ai_clips(scenes, frames, work, budget_usd, notes, client, sleep)
        lines = {s.index: s.voiceover for s in scenes if s.voiceover.strip()}
        voices, voice_cost, voice_name = voiceover(lines, work, notes, runner, client)
        lengths = {i: probe(ffmpeg, p, runner)["duration"] for i, p in voices.items()}
        voices = {i: p for i, p in voices.items() if lengths.get(i, 0) > 0}
        durations = plan_durations(scenes, lengths)
        width, height = output_size()
        font_px = int(width * 0.064)
        font = find_font()
        if font is None:
            notes.append("no TrueType font found; captions use ffmpeg's default font")
        segments, sources = [], []
        for i, scene in enumerate(scenes):
            on_screen = scene.on_screen
            if re.search(r"\[verify\]", on_screen, re.I):
                on_screen = re.sub(r"\s*\[verify\]", "", on_screen, flags=re.I).strip()
                notes.append(f"scene {i + 1} caption has a figure marked [verify]; check it before posting")
            lines_ = wrap_caption(on_screen, width, font_px) if on_screen else []
            names = []
            for j, text in enumerate(lines_):
                name = f"cap-{i:02d}-{j}.txt"
                (work / name).write_text(text, encoding="utf-8")
                names.append(name)
            captions = caption_filters(lines_, names, width, height, font_px, font)
            kind = "clip" if i in clips else "image"
            source = str(clips[i] if kind == "clip" else frames[i])
            out = f"seg-{i:02d}.mp4"
            result = _run(runner, segment_command(ffmpeg, source, kind, durations[i], out, index=i, width=width,
                                                  height=height, captions=captions, font=font, font_px=font_px), work, 300)
            if result.returncode != 0 and kind == "clip":  # a broken clip falls back to its keyframe
                notes.append(f"scene {i + 1}: AI clip could not be decoded; used Ken Burns")
                kind = "image"
                result = _run(runner, segment_command(ffmpeg, str(frames[i]), kind, durations[i], out, index=i, width=width,
                                                      height=height, captions=captions, font=font, font_px=font_px), work, 300)
            if result.returncode != 0:
                raise VideoError(f"ffmpeg failed on scene {i + 1}: {_stderr(result).strip()[-200:]}")
            segments.append(out)
            sources.append("AI clip" if kind == "clip" else "keyframe (Ken Burns)")
        voice_inputs = [(i, str(voices[i])) for i in sorted(voices)]
        result = _run(runner, assemble_command(ffmpeg, segments, durations, voice_inputs, REEL_NAME), work, 600)
        if result.returncode != 0:
            raise VideoError(f"ffmpeg assembly failed: {_stderr(result).strip()[-200:]}")
        built = work / REEL_NAME
        if not built.is_file():
            raise VideoError("ffmpeg produced no file")
        info = probe(ffmpeg, built, runner)
        if info["video"] != "h264" or info["audio"] != "aac" or not 0 < info["duration"] <= MAX_REEL_SECONDS + 0.5:
            raise VideoError(f"output failed verification (video={info['video']}, audio={info['audio']}, {info['duration']:.1f}s)")
        final = folder / REEL_NAME
        os.replace(built, final)
        data = final.read_bytes()
        ai = sum(1 for s in sources if s == "AI clip")
        if ai == len(scenes):
            path_used = f"AI video model ({model_id}, image-to-video from each scene keyframe), assembled with ffmpeg"
        elif ai:
            path_used = f"hybrid: AI video model ({model_id}) for {ai} of {len(scenes)} scenes + local ffmpeg Ken Burns for the rest"
        else:
            path_used = f"assembled locally with ffmpeg from {len(scenes)} scene keyframes (Ken Burns zoom/pan, crossfades)"
        return VideoResult(
            path=final, url_path=f"/media/{run_id}/{REEL_NAME}", duration=round(info["duration"], 2), size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), width=info["width"] or width, height=info["height"] or height,
            path_used=path_used, ai_clips=ai, scenes=len(scenes), voice=voice_name, cost_usd=round(clip_cost + voice_cost, 4),
            scene_sources=sources, notes=notes,
        )
    finally:
        if not config.get("VIDEO_KEEP_WORK"):
            shutil.rmtree(work, ignore_errors=True)
