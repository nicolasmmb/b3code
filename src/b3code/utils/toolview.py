"""Títulos e preview de tool calls. Sem whitelist de nomes."""

from __future__ import annotations

import json
from typing import Any

PREVIEW_LINES = 20
PREVIEW_CHARS = 4000

_Args = dict[str, Any]
_SKIP = frozenset(
    {
        "command",
        "pattern",
        "query",
        "content",
        "code",
        "old",
        "new",
        "text",
        "prompt",
        "start_line",
        "end_line",
        "start",
        "end",
    }
)
_SHORT = 120


def parse_args(raw: Any) -> _Args:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def tool_title(name: str, args: Any) -> str:
    parsed = parse_args(args)
    command = _short(parsed.get("command"))
    if command:
        return f"$ {command}"
    needle = _short(parsed.get("pattern")) or _short(parsed.get("query"))
    if needle:
        return _search_title(needle, parsed)
    subject = _subject(parsed)
    if not subject:
        return f"Ran {name}"
    verb = _verb(name)
    extra = _range_suffix(parsed)
    return f"{verb} {subject}{extra}"


def preview_output(text: str) -> str:
    if not text:
        return ""
    body = text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "\n…"
    lines = body.splitlines()
    if len(lines) <= PREVIEW_LINES:
        return body.rstrip("\n")
    return "\n".join(lines[:PREVIEW_LINES]) + "\n…"


def _search_title(needle: str, parsed: _Args) -> str:
    title = f'Searched "{needle}"'
    path = _short(parsed.get("path"))
    if path and path != ".":
        title += f" in {path}"
    return title


def _subject(parsed: _Args) -> str:
    src, dest = _short(parsed.get("src")), _short(parsed.get("dest"))
    if src and dest:
        return f"{src} → {dest}"
    for key, value in parsed.items():
        if key in _SKIP or isinstance(value, bool):
            continue
        text = _short(value)
        if text:
            return text
    return ""


def _verb(name: str) -> str:
    word = name.replace("-", "_").split("_", 1)[0]
    return word[:1].upper() + word[1:] if word else name


def _range_suffix(parsed: _Args) -> str:
    start = parsed.get("start_line", parsed.get("start"))
    end = parsed.get("end_line", parsed.get("end"))
    if start is None and end is None:
        return ""
    lo = start if start is not None else 1
    hi = end if end is not None else lo
    return f" ({lo}-{hi})"


def _short(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if len(text) > _SHORT:
        return ""
    return text
