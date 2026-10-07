"""Onboarding stage: turn a real creator's answers into a reusable virtual-avatar spec.

Two LLM steps: profile extraction (facts only, from the creator's own words) -> avatar spec (Markdown + Avatar JSON).

Reuse in later stages: any brief that contains the "## Avatar JSON" fenced block from an Onboarding run can be
parsed with `extract_avatar(text)`; `avatar_context(text)` renders it as a short block to append to a prompt.
"""
import json
import re
from typing import Callable

AVATAR_KEYS = ("name", "handle", "niche", "traits", "interests", "values", "moat", "voice", "visual_prompt", "boundaries", "pillars")
SECTIONS = (
    "## Avatar profile",
    "## Voice & speaking style",
    "## Visual identity",
    "## Moat & positioning",
    "## Authenticity guardrails",
    "## Content pillars & first 5 video ideas",
    "## Avatar JSON",
)

_HEADING = re.compile(r"^#{1,6}\s*Avatar JSON\s*$", re.IGNORECASE | re.MULTILINE)
_FENCE = re.compile(r"```[ \t]*(?:json)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _parse(blob: str) -> dict | None:
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not any(key in data for key in AVATAR_KEYS):
        return None
    return data


def extract_avatar(text: str) -> dict | None:
    """Return the Avatar JSON object from an Onboarding output (or a brief that pastes it), else None.

    Prefers the fenced block under an "Avatar JSON" heading; falls back to any fenced JSON object that
    carries avatar keys. Never raises.
    """
    if not text or not isinstance(text, str):
        return None
    heading = _HEADING.search(text)
    if heading:
        match = _FENCE.search(text, heading.end())
        if match and (data := _parse(match.group(1).strip())):
            return data
    for match in _FENCE.finditer(text):
        if data := _parse(match.group(1).strip()):
            return data
    return None


def avatar_context(text: str) -> str:
    """A prompt-ready block describing the reusable avatar found in `text`, or "" when there is none."""
    avatar = extract_avatar(text)
    if not avatar:
        return ""
    return (
        "\n\n---\n# Creator avatar (from Onboarding; stay consistent with it, respect its boundaries)\n"
        + json.dumps({k: avatar[k] for k in AVATAR_KEYS if k in avatar}, ensure_ascii=False, indent=2)
    )


def missing_sections(markdown: str) -> list[str]:
    return [heading for heading in SECTIONS if heading.lower() not in markdown.lower()]


def run(ask: Callable[[str, str], str], brief: str, profile_prompt: str, spec_prompt: str) -> list[str]:
    """Run profile extraction then avatar spec; returns the output sections for the graph."""
    profile = ask(profile_prompt, brief)
    spec = ask(spec_prompt, f"{brief}\n\n---\n# Extracted creator profile\n{profile}")
    sections = [spec]
    if extract_avatar(spec) is None:
        sections.append("## Avatar JSON status\n\nThe model did not return a parseable Avatar JSON block; rerun Onboarding before reusing this avatar.")
    return sections
