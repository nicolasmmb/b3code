"""Diff unificado puro — sem Textual, sem pydantic_ai."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

MAX_DIFF_LINES = 40
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class DiffLine:
    kind: str  # + | - | space
    text: str
    number: int


@dataclass(frozen=True)
class FileChange:
    path: str
    added: int
    removed: int
    lines: tuple[DiffLine, ...]
    truncated: bool = False


def summary(change: FileChange) -> str:
    return f"{change.path}  +{change.added} −{change.removed}"


def diff_texts(
    path: str, old: str, new: str, *, max_lines: int = MAX_DIFF_LINES
) -> FileChange:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    if not old_lines and new_lines:
        added = len(new_lines)
        shown = tuple(
            DiffLine("+", line, i) for i, line in enumerate(new_lines[:max_lines], 1)
        )
        return FileChange(path, added, 0, shown, truncated=added > max_lines)

    parsed: list[DiffLine] = []
    added = 0
    removed = 0
    old_i = 1
    new_i = 1
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=3):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            match = _HUNK.match(line)
            if match:
                old_i = int(match.group(1))
                new_i = int(match.group(2))
            continue
        if line.startswith("+"):
            added += 1
            parsed.append(DiffLine("+", line[1:], new_i))
            new_i += 1
            continue
        if line.startswith("-"):
            removed += 1
            parsed.append(DiffLine("-", line[1:], old_i))
            old_i += 1
            continue
        if line.startswith("\\"):
            continue
        body = line[1:] if line.startswith(" ") else line
        parsed.append(DiffLine(" ", body, new_i))
        old_i += 1
        new_i += 1

    truncated = len(parsed) > max_lines
    return FileChange(path, added, removed, tuple(parsed[:max_lines]), truncated)
