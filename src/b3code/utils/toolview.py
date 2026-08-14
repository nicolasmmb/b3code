"""Títulos e preview de tool calls, no recorte do Grok Build."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

PREVIEW_LINES = 20
PREVIEW_CHARS = 4000

_Args = dict[str, Any]


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
    handler = _TITLES.get(name)
    if handler is None:
        return f"Ran {name}"
    return handler(parsed)


def preview_output(text: str) -> str:
    if not text:
        return ""
    body = text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "\n…"
    lines = body.splitlines()
    if len(lines) <= PREVIEW_LINES:
        return body.rstrip("\n")
    return "\n".join(lines[:PREVIEW_LINES]) + "\n…"


def _field(parsed: _Args, *keys: str) -> str:
    for key in keys:
        value = parsed.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _title_command(parsed: _Args) -> str:
    command = _field(parsed, "command")
    return f"$ {command}" if command else "Ran run_command"


def _title_read(parsed: _Args) -> str:
    path = _field(parsed, "path") or "?"
    start, end = parsed.get("start_line"), parsed.get("end_line")
    if start is None and end is None:
        return f"Read {path}"
    lo = start if start is not None else 1
    hi = end if end is not None else lo
    return f"Read {path} ({lo}-{hi})"


def _title_list(parsed: _Args) -> str:
    return f"Listed {_field(parsed, 'path') or '.'}"


def _title_grep(parsed: _Args) -> str:
    pattern = _field(parsed, "pattern")
    title = f'Searched "{pattern}"' if pattern else "Searched"
    path = _field(parsed, "path") or "."
    if path != ".":
        title += f" in {path}"
    return title


def _title_edit(parsed: _Args) -> str:
    path = _field(parsed, "path", "dest", "src")
    return f"Editing {path}" if path else "Editing"


_TITLES: dict[str, Callable[[_Args], str]] = {
    "run_command": _title_command,
    "start_command": _title_command,
    "read_file": _title_read,
    "list_dir": _title_list,
    "grep": _title_grep,
    "write_file": _title_edit,
    "replace_in_file": _title_edit,
    "delete_file": _title_edit,
    "move_file": _title_edit,
}
