"""Aplicar suggestion e decidir o Enter. Sem Textual, sem SessionStore."""

from __future__ import annotations

from dataclasses import dataclass

from b3code.commands.types import Suggestion
from b3code.utils.prompt import current_token


@dataclass(frozen=True)
class Decision:
    kind: str  # apply | execute | chat | empty
    line: str = ""
    cursor: int = 0
    suggestion: Suggestion | None = None


def apply_suggestion(text: str, cursor: int, suggestion: Suggestion) -> tuple[str, int]:
    start, end, token = current_token(text, cursor)
    if _already_applied(text, cursor, suggestion):
        stripped = text.rstrip() if suggestion.kind != "file" else text
        return stripped, len(stripped)

    if suggestion.kind == "file":
        inserted = suggestion.value if suggestion.value.startswith("@") else f"@{suggestion.value}"
    elif suggestion.kind == "cmd":
        inserted = suggestion.value.rstrip()
        if not suggestion.consume:
            inserted += " "
    elif token.startswith("/"):
        inserted = f"{token} {suggestion.value}"
    else:
        inserted = suggestion.value

    new = text[:start] + inserted + text[end:]
    return new, start + len(inserted)


def decide_submit(
    line: str, cursor: int, suggestion: Suggestion | None
) -> Decision:
    if suggestion is not None and not _already_applied(line, cursor, suggestion):
        new, cur = apply_suggestion(line, cursor, suggestion)
        return Decision("apply", new, cur, suggestion)

    stripped = line.strip()
    if suggestion is not None and suggestion.consume:
        if suggestion.kind == "arg" and stripped.startswith("/"):
            built = apply_suggestion(line, cursor, suggestion)[0].strip()
            return Decision("execute", built, len(built), suggestion)
        if stripped.startswith("/"):
            return Decision("execute", stripped, cursor, suggestion)

    if not stripped:
        return Decision("empty")
    if stripped.startswith("/"):
        return Decision("execute", stripped)
    return Decision("chat", stripped)


def _already_applied(text: str, cursor: int, suggestion: Suggestion) -> bool:
    _, _, token = current_token(text, cursor)
    if suggestion.kind == "file":
        return token == suggestion.value or token == f"@{suggestion.value.lstrip('@')}"
    if token == suggestion.value:
        return True
    if token == "":
        return _previous_token(text, cursor) == suggestion.value
    return False


def _previous_token(text: str, cursor: int) -> str:
    start, _, token = current_token(text, cursor)
    if token:
        return ""
    before = text[:start].rstrip()
    if not before:
        return ""
    return before[before.rfind(" ") + 1 :]
