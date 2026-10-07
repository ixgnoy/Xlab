"""Persona-consistent image generation through OpenRouter chat completions (modalities: image + text).

The first prompt produces the persona reference portrait; every later prompt sends that portrait (or the
caller's reference) back as an input image so the character stays consistent. Files are written to
PROJECT_DIR/.local/media/<run_id>/ and served read-only by GET /media/{run_id}/{name} on loopback.
"""
import base64
import binascii
import hashlib
import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import config

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-3.1-flash-lite-image"
DEFAULT_USD_PER_IMAGE = 0.10  # used only when live pricing is unavailable; deliberately pessimistic
MAX_PROMPT_CHARS = 1500
MAX_IMAGE_BYTES = 20 * 1024 * 1024

# Token assumptions for the budget estimate (Gemini image output is ~1290 tokens per ~1MP image).
EST_IMAGE_OUTPUT_TOKENS = 1400
EST_TEXT_OUTPUT_TOKENS = 300
EST_TEXT_INPUT_TOKENS = 500
EST_REFERENCE_INPUT_TOKENS = 1300

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
FILE_NAME = re.compile(r"^[0-9]{2}-[0-9a-f]{16}\.(png|jpg|webp)$")
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
EXT_MIME = {ext: mime for mime, ext in MIME_EXT.items()}

SAFETY_SUFFIX = (
    "\n\nStyle and safety requirements: depict only the original, fictional AI-generated character described "
    "above. Do not depict, imitate, or resemble any real, identifiable person, celebrity, or public figure. "
    "No logos, brand marks, watermarks, or readable text. Adults only, fully clothed, non-sexual. "
    "Clean editorial social-media look with soft natural light."
)
CONSISTENCY_NOTE = (
    "Use the attached reference image as the same fictional character: keep face, hair, skin tone, and overall "
    "look identical while following the new scene below.\n\n"
)
BLOCKED = re.compile(
    r"\b(look[- ]?alike|deep[- ]?fake|doppelg[aä]nger|celebrity|impersonat\w*|face[- ]?swap|real person)\b",
    re.IGNORECASE,
)


class MediaError(RuntimeError):
    """Generation stopped. `files` holds any images that were saved before the failure."""

    def __init__(self, reason: str, files: list["MediaFile"] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.files = files or []


@dataclass(frozen=True)
class MediaFile:
    run_id: str
    name: str
    path: Path
    sha256: str
    mime: str
    prompt: str
    cost_usd: float | None = None

    @property
    def url_path(self) -> str:
        return f"/media/{self.run_id}/{self.name}"


@dataclass
class Budget:
    model: str
    usd_per_image: float
    limit_usd: float
    max_images: int
    spent_usd: float = 0.0
    priced: bool = True
    notes: list[str] = field(default_factory=list)

    def allowed(self, wanted: int) -> int:
        by_cost = math.floor(self.limit_usd / self.usd_per_image) if self.usd_per_image > 0 else wanted
        return max(0, min(wanted, self.max_images, by_cost))


def media_root() -> Path:
    return config.PROJECT_DIR / ".local" / "media"


def resolve_media_file(run_id: str, name: str) -> Path | None:
    """Strictly validated lookup used by the HTTP route; returns None for anything not generated here."""
    if not RUN_ID.fullmatch(run_id or "") or not FILE_NAME.fullmatch(name or ""):
        return None
    root = media_root().resolve()
    candidate = (root / run_id / name).resolve()
    if candidate.parent.parent != root or not candidate.is_file():
        return None
    return candidate


def _float_env(name: str, default: float) -> float:
    try:
        value = float(config.get(name, str(default)))
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(config.get(name, str(default))))
    except ValueError:
        return default


def _price(pricing: dict, key: str) -> float:
    try:
        value = float(pricing.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


def estimate_usd_per_image(pricing: dict, with_reference: bool = True) -> float | None:
    """Per-image cost from OpenRouter per-token pricing; None when the model publishes no image price."""
    image_output = _price(pricing, "image_output")
    if not image_output:
        return None
    prompt = _price(pricing, "prompt")
    image_input = _price(pricing, "image") or prompt
    cost = (
        EST_IMAGE_OUTPUT_TOKENS * image_output
        + EST_TEXT_OUTPUT_TOKENS * _price(pricing, "completion")
        + EST_TEXT_INPUT_TOKENS * prompt
        + (EST_REFERENCE_INPUT_TOKENS * image_input if with_reference else 0)
    )
    return round(cost, 6)


def fetch_pricing(client: httpx.Client, model: str) -> dict | None:
    response = client.get(f"{OPENROUTER_URL}/models", params={"output_modalities": "image"})
    response.raise_for_status()
    for entry in response.json().get("data", []):
        if entry.get("id") == model:
            return entry.get("pricing") or {}
    return None


def build_budget(client: httpx.Client, model: str) -> Budget:
    limit = _float_env("MAX_USD_PER_TASK", 3.0)
    max_images = _int_env("MAX_IMAGES", 4)
    override = config.get("IMAGE_USD_PER_IMAGE")
    if override:
        return Budget(model, _float_env("IMAGE_USD_PER_IMAGE", DEFAULT_USD_PER_IMAGE), limit, max_images)
    try:
        pricing = fetch_pricing(client, model)
    except (httpx.HTTPError, ValueError):
        pricing = None
    estimate = estimate_usd_per_image(pricing) if pricing is not None else None
    if estimate is None:
        budget = Budget(model, DEFAULT_USD_PER_IMAGE, limit, max_images, priced=False)
        budget.notes.append(f"pricing unavailable; assumed ${DEFAULT_USD_PER_IMAGE:.2f}/image")
        return budget
    return Budget(model, estimate, limit, max_images)


def _sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _data_url(data: bytes) -> str:
    mime = _sniff_mime(data) or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _decode_data_url(url: str) -> bytes:
    match = re.fullmatch(r"data:(image/[a-z0-9.+-]+);base64,(.+)", url.strip(), re.DOTALL)
    if not match:
        raise MediaError("model returned an image that is not a base64 data URL")
    try:
        data = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError):
        raise MediaError("model returned undecodable image data") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise MediaError("model returned an empty or oversized image")
    return data


def extract_image_urls(payload: dict) -> list[str]:
    """Image URLs from an OpenRouter chat completion: message.images[] (documented) or image_url content parts."""
    urls: list[str] = []
    for choice in payload.get("choices") or []:
        message = (choice or {}).get("message") or {}
        for image in message.get("images") or []:
            url = ((image or {}).get("image_url") or {}).get("url")
            if isinstance(url, str):
                urls.append(url)
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url")
                    if isinstance(url, str):
                        urls.append(url)
    return urls


def _api_error(response: httpx.Response) -> str:
    try:
        message = str(((response.json() or {}).get("error") or {}).get("message") or "")[:200]
    except ValueError:
        message = ""
    return f"OpenRouter HTTP {response.status_code}" + (f": {message}" if message else "")


def _request_image(client: httpx.Client, api_key: str, model: str, prompt: str, reference: bytes | None) -> tuple[bytes, float | None]:
    text = (CONSISTENCY_NOTE if reference else "") + prompt + SAFETY_SUFFIX
    content: list[dict] = [{"type": "text", "text": text}]
    if reference:
        content.append({"type": "image_url", "image_url": {"url": _data_url(reference)}})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": config.get("IMAGE_ASPECT_RATIO", "4:5")},
        "usage": {"include": True},
    }
    response = client.post(
        f"{OPENROUTER_URL}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "X-Title": "PersonaLab"},
    )
    if response.status_code >= 400:
        raise MediaError(_api_error(response))
    try:
        payload = response.json()
    except ValueError:
        raise MediaError("OpenRouter returned a non-JSON response") from None
    if payload.get("error"):
        raise MediaError(f"OpenRouter error: {str((payload['error'] or {}).get('message', ''))[:200]}")
    urls = extract_image_urls(payload)
    if not urls:
        raise MediaError("model returned no image (it may have refused the prompt)")
    cost = (payload.get("usage") or {}).get("cost")
    return _decode_data_url(urls[0]), float(cost) if isinstance(cost, (int, float)) else None


def _save(run_id: str, index: int, data: bytes, prompt: str, cost: float | None) -> MediaFile:
    mime = _sniff_mime(data)
    if mime is None:
        raise MediaError("model returned bytes that are not PNG, JPEG, or WebP")
    digest = hashlib.sha256(data).hexdigest()
    name = f"{index:02d}-{digest[:16]}.{MIME_EXT[mime]}"
    folder = media_root() / run_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return MediaFile(run_id, name, path, digest, mime, prompt, cost)


def check_prompt(prompt: str) -> str:
    cleaned = " ".join(prompt.split())[:MAX_PROMPT_CHARS]
    if not cleaned:
        raise MediaError("empty image prompt")
    hit = BLOCKED.search(cleaned)
    if hit:
        raise MediaError(f"prompt rejected: it asks for real-person imitation ('{hit.group(0)}')")
    return cleaned


def generate_images(
    prompts: list[str],
    reference: bytes | None = None,
    *,
    run_id: str | None = None,
    client: httpx.Client | None = None,
) -> list[MediaFile]:
    """Generate one image per prompt. prompts[0] is the reference portrait unless `reference` is supplied.

    Raises MediaError (with any already-saved files attached) on missing key, budget, or API failure.
    """
    api_key = config.get("OPENROUTER_API_KEY")
    if not api_key:
        raise MediaError("OPENROUTER_API_KEY is not configured")
    cleaned = [check_prompt(p) for p in prompts]
    if not cleaned:
        raise MediaError("no image prompts")
    run_id = run_id or uuid.uuid4().hex
    if not RUN_ID.fullmatch(run_id):
        raise MediaError("invalid run id")
    model = config.get("IMAGE_MODEL_ID", DEFAULT_MODEL)
    owns_client = client is None
    http = client or httpx.Client(timeout=_float_env("IMAGE_TIMEOUT_S", 120.0))
    files: list[MediaFile] = []
    try:
        budget = build_budget(http, model)
        allowed = budget.allowed(len(cleaned))
        if allowed == 0:
            raise MediaError(
                f"budget guard: ~${budget.usd_per_image:.3f}/image exceeds MAX_USD_PER_TASK=${budget.limit_usd:.2f} "
                f"or MAX_IMAGES={budget.max_images}"
            )
        current = reference
        for index, prompt in enumerate(cleaned[:allowed]):
            if budget.spent_usd + budget.usd_per_image > budget.limit_usd + 1e-9:
                raise MediaError(f"budget guard: stopping at ${budget.spent_usd:.3f} of ${budget.limit_usd:.2f}", files)
            try:
                data, cost = _request_image(http, api_key, model, prompt, current)
                budget.spent_usd += cost if cost is not None else budget.usd_per_image
                files.append(_save(run_id, index, data, prompt, cost))
            except httpx.HTTPError as error:
                raise MediaError(f"OpenRouter request failed ({type(error).__name__})", files) from None
            except MediaError as error:
                raise MediaError(error.reason, files) from None
            if current is None:
                current = data  # the first image becomes the consistency reference
        if allowed < len(cleaned):
            raise MediaError(
                f"generated {allowed} of {len(cleaned)} images (MAX_IMAGES={budget.max_images}, "
                f"MAX_USD_PER_TASK=${budget.limit_usd:.2f})",
                files,
            )
        return files
    finally:
        if owns_client:
            http.close()


# ---------------------------------------------------------------------------
# LLM-free prompt extraction from the Create stage markdown.
# ---------------------------------------------------------------------------
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LABEL_LINE = re.compile(r"^(?:[-*+]|\d+[.)])\s*\S|^[A-Z][\w /&()'-]{0,40}:\s")
REFERENCE_LABEL = re.compile(
    r"\b(?:image[- ]?generation\s+)?reference\s+(?:image\s+)?prompt\b[^:\n]{0,40}?(?:[:\-\u2013\u2014]|$)", re.IGNORECASE
)
CONCEPT_LABEL = re.compile(
    r"\b(?:image[- ]?)?(?:generation|gen|image)[- ]prompt\b[^:\n]{0,20}?(?:[:\-\u2013\u2014]|$)", re.IGNORECASE
)
VISUAL_LABEL = re.compile(r"\bvisual identity\b[^:\n]{0,20}?(?:[:\-\u2013\u2014]|$)", re.IGNORECASE)


def _strip_md(line: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
    text = re.sub(r"^\s*(?:>\s*)+", "", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return text.strip()


def _clean_value(text: str) -> str:
    text = " ".join(text.split()).strip(" :-\u2013\u2014*_")
    if len(text) >= 2 and text[0] in "\"'\u201c" and text[-1] in "\"'\u201d":
        text = text[1:-1].strip()
    return text[:MAX_PROMPT_CHARS]


def _section(markdown: str, title: re.Pattern) -> str | None:
    lines = markdown.splitlines()
    for start, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading and title.search(heading.group(2)):
            level = len(heading.group(1))
            body = []
            for nxt in lines[start + 1:]:
                other = _HEADING.match(nxt)
                if other and len(other.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body)
    return None


def _continuation(lines: list[str], start: int) -> str:
    """Text that follows a label with nothing after its colon: a fenced block, a quote, or a paragraph."""
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return ""
    if _FENCE.match(lines[i]):
        block = []
        for line in lines[i + 1:]:
            if _FENCE.match(line):
                break
            block.append(line)
        return " ".join(block)
    block = []
    for line in lines[i:]:
        raw = line.strip()
        if not raw or _HEADING.match(line):
            break
        plain = _strip_md(line)
        if block and (_LABEL_LINE.match(raw) or re.match(r"^\w[\w /&()'-]{0,40}:\s", plain)):
            break
        block.append(plain)
    return " ".join(block)


def _table_column(text: str, header: re.Pattern) -> list[str]:
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(rows) < 3:
        return []
    cells = lambda row: [c.strip() for c in row.strip("|").split("|")]
    head = cells(rows[0])
    column = next((i for i, name in enumerate(head) if header.search(_strip_md(name))), None)
    if column is None:
        return []
    values = []
    for row in rows[2:]:
        parts = cells(row)
        if column < len(parts) and _clean_value(_strip_md(parts[column])):
            values.append(_clean_value(_strip_md(parts[column])))
    return values


def labeled_values(text: str, label: re.Pattern) -> list[str]:
    values: list[str] = []
    lines = text.splitlines()
    in_fence = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.strip().startswith("|"):
            continue
        plain = _strip_md(line)
        match = label.search(plain)
        if not match or match.start() > 40:
            continue
        after = plain[match.end():]
        value = _clean_value(after) or _clean_value(_continuation(lines, index + 1))
        if value:
            values.append(value)
    return values


def reference_prompt(persona_markdown: str) -> str | None:
    """The persona card's image-generation reference prompt, or a portrait prompt built from its visual identity."""
    found = labeled_values(persona_markdown, REFERENCE_LABEL) or _table_column(persona_markdown, re.compile("reference", re.I))
    if found:
        return found[0]
    visual = labeled_values(persona_markdown, VISUAL_LABEL)
    if visual:
        return f"Head-and-shoulders reference portrait of an original fictional AI influencer. {visual[0]}"
    return None


def concept_prompts(content_markdown: str, limit: int = 3) -> list[str]:
    """Generation prompts of the photo concepts; falls back to each concept's description."""
    section = _section(content_markdown, re.compile(r"photo concepts?", re.IGNORECASE))
    scope = section if section is not None else content_markdown
    prompts = labeled_values(scope, CONCEPT_LABEL) or _table_column(scope, re.compile(r"prompt", re.I))
    if not prompts and section is not None:
        prompts = _concept_chunks(section)
    unique = list(dict.fromkeys(p for p in prompts if p))
    return unique[:limit]


def _concept_chunks(section: str) -> list[str]:
    """Heuristic: one prompt per sub-heading or top-level numbered item inside the photo concepts section."""
    chunks: list[list[str]] = []
    for line in section.splitlines():
        if _HEADING.match(line) or re.match(r"^\d+[.)]\s", line):
            chunks.append([_strip_md(line)])
        elif chunks and line.strip():
            chunks[-1].append(_strip_md(line))
    return [_clean_value("Photo of the same character. " + " ".join(chunk)) for chunk in chunks if len(" ".join(chunk)) > 20]
