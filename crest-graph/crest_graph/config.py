"""Single configuration loader shared by the graph, server and checks.

Precedence: real process environment > ../.env.local > ../.env (same order as the Node scripts).
Files are re-read on each call so a newly added key works without a restart.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def settings() -> dict[str, str]:
    merged = _parse(PROJECT_DIR / ".env")
    merged.update(_parse(PROJECT_DIR / ".env.local"))
    merged.update({k: v for k, v in os.environ.items()})
    return merged


def get(name: str, default: str | None = None) -> str | None:
    value = settings().get(name)
    return value if value not in (None, "") else default


def flag(name: str) -> bool:
    return (get(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def data_dir() -> Path:
    """DATA_DIR (default .local) holds media and personalab.db; relative paths resolve against PROJECT_DIR."""
    path = Path((get("DATA_DIR", ".local") or ".local").strip())
    return path if path.is_absolute() else PROJECT_DIR / path


def hosted() -> bool:
    return flag("HOSTED")


def media_public() -> bool:
    return flag("MEDIA_PUBLIC")


def graph_host() -> str:
    return (get("CREST_GRAPH_HOST", "127.0.0.1") or "127.0.0.1").strip()


def graph_port() -> int:
    return int(get("CREST_GRAPH_PORT") or get("PORT") or "21951")


def media_base_url() -> str:
    """Origin used in result Markdown for /media links: PUBLIC_MEDIA_BASE_URL when MEDIA_PUBLIC=1, else loopback."""
    public = (get("PUBLIC_MEDIA_BASE_URL", "") or "").strip().rstrip("/")
    if media_public() and public.startswith(("https://", "http://")):
        return public
    return f"http://127.0.0.1:{graph_port()}"
