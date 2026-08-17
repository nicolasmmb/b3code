"""Tokens `@arquivo` no prompt e blocos `<file>` enviados ao modelo.

Anexos entram no *user turn* (não no system prompt) para o prefixo
estático do cache Azure continuar válido.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic_ai import BinaryContent

from b3code.utils.attachments import (
    AttachKind,
    Attachment,
    chip_token,
    classify_path,
    label_for_text,
)

AT_TOKEN = re.compile(r"(?<!\S)@([^\s]+)")
FILE_BLOCK = re.compile(r'<file path="([^"]+)">.*?</file>\s*', re.DOTALL)
SKILL_BLOCK = re.compile(r'<skill\s+name="([^"]+)"[^>]*>.*?</skill>\s*', re.DOTALL)
SKILL_MENTION = re.compile(r"(?<!\S)!([^\s]+)")
SKILL_CHIP = re.compile(r"\[SKILL - ([^\]]+)\]")
CHIP_TOKEN = re.compile(r"\[([A-Z0-9]+) - ([^\]]+)\]")
ATTACH_CHAR_LIMIT = 80_000


def current_token(text: str, cursor: int) -> tuple[int, int, str]:
    """Token sob o cursor (do último whitespace até o cursor)."""
    start = cursor
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return start, cursor, text[start:cursor]


def find_at_refs(text: str) -> list[str]:
    return AT_TOKEN.findall(text)


def expand_attachments(text: str, cwd: Path, read_file) -> str:
    """Troca `@path` por menção + bloco `<file>` com o conteúdo."""
    seen: set[str] = set()
    chunks = [text, ""]
    for rel in find_at_refs(text):
        if rel in seen:
            continue
        seen.add(rel)
        try:
            body = read_file(rel)
        except (OSError, ValueError, UnicodeDecodeError):
            chunks.append(f"(could not read @{rel})")
            continue
        chunks.append(f'<file path="{rel}">\n{body}\n</file>')
    return "\n".join(chunks).rstrip()


def strip_file_blocks(text: str) -> str:
    """Tira blocos `<file>` na hora de *mostrar* o user turn."""
    return FILE_BLOCK.sub("", text).strip()


def replace_skill_blocks(text: str) -> str:
    """Troca blocos `<skill>` por chips `[SKILL - nome]` na exibição."""
    return SKILL_BLOCK.sub(
        lambda match: chip_token("SKILL", match.group(1)), text
    )


def replace_skill_mentions(text: str) -> str:
    """Troca `!nome` por chips `[SKILL - nome]` na exibição."""
    return SKILL_MENTION.sub(
        lambda match: chip_token("SKILL", match.group(1)), text
    )


def replace_skill_refs(text: str) -> str:
    """Troca `!nome` e blocos `<skill>` por chips (exibição do user turn)."""
    return replace_skill_blocks(replace_skill_mentions(text))


def expand_skills(text: str, load_skill) -> str:
    """Troca `!nome` e `[SKILL - nome]` por blocos `<skill>` (vai ao modelo)."""

    def _replace(match: re.Match[str]) -> str:
        block = load_skill(match.group(1))
        return block or match.group(0)

    text = SKILL_MENTION.sub(_replace, text)
    return SKILL_CHIP.sub(_replace, text)


def _maybe_expand_skills(text: str, load_skill) -> str:
    if load_skill is None:
        return text
    return expand_skills(text, load_skill)


def split_display_chips(text: str) -> tuple[list[tuple[str, str]], str]:
    chips = [(label, name) for label, name in CHIP_TOKEN.findall(text)]
    body = CHIP_TOKEN.sub("", text)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return chips, body


def display_user_content(content: Any) -> str:
    if isinstance(content, str):
        return _display_text(content)
    if not isinstance(content, list):
        return str(content)
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str):
            piece = _display_text(item)
            if piece:
                chunks.append(piece)
            continue
        chip = _chip_from_binary(item)
        if chip:
            chunks.append(chip)
    return "\n".join(chunks).strip()


def _display_text(text: str) -> str:
    chips: list[str] = []

    def _keep_chip(match: re.Match[str]) -> str:
        chips.append(
            chip_token(label_for_text(match.group(1)), Path(match.group(1)).name)
        )
        return ""

    text = replace_skill_blocks(text)
    cleaned = FILE_BLOCK.sub(_keep_chip, text).strip()
    if not chips:
        return cleaned
    prefix = " ".join(chips)
    return f"{prefix}\n{cleaned}".strip() if cleaned else prefix


def _chip_from_binary(item: Any) -> str:
    mime = str(getattr(item, "media_type", "") or "")
    name = str(getattr(item, "identifier", "") or "")
    if mime.startswith("image/"):
        label = "IMG"
        name = name or "image"
    elif mime == "application/pdf":
        label = "PDF"
        name = name or "document.pdf"
    else:
        label = "FILE"
        name = name or "file"
    return chip_token(label, Path(name).name)


def _resolve_ref(rel: str, cwd: Path) -> Path | None:
    path = Path(rel).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _inline_file_block(item: Attachment) -> str:
    try:
        body = item.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        body = f"(could not read @{item.filename})"
    return f'<file path="{item.filename}">\n{body}\n</file>'


def _binary_part(item: Attachment) -> BinaryContent:
    return BinaryContent(
        data=item.path.read_bytes(),
        media_type=item.media_type or "application/octet-stream",
        identifier=item.filename,
    )


def _pull_chips(
    text: str, attachments: dict[str, Attachment]
) -> tuple[str, list[Attachment]]:
    found: list[Attachment] = []
    leftover = text
    for token in sorted(attachments, key=len, reverse=True):
        if token not in leftover:
            continue
        leftover = leftover.replace(token, " ")
        found.append(attachments[token])
    leftover = re.sub(r"[ \t]{2,}", " ", leftover)
    leftover = re.sub(r" *\n *", "\n", leftover).strip()
    return leftover, found


def _pull_at_binaries(text: str, cwd: Path) -> tuple[str, list[Attachment]]:
    extra: list[Attachment] = []

    def _maybe_drop(match: re.Match[str]) -> str:
        rel = match.group(1)
        path = _resolve_ref(rel, cwd)
        if path is None:
            return match.group(0)
        item = classify_path(path)
        if item is None or item.kind not in {AttachKind.IMAGE, AttachKind.PDF}:
            return match.group(0)
        extra.append(item)
        return " "

    leftover = AT_TOKEN.sub(_maybe_drop, text)
    leftover = re.sub(r"[ \t]{2,}", " ", leftover).strip()
    return leftover, extra


def build_user_content(
    text: str,
    cwd: Path,
    read_file,
    attachments: dict[str, Attachment] | None = None,
    load_skill=None,
) -> str | list[str | BinaryContent]:
    leftover, chip_items = _pull_chips(text, attachments or {})
    leftover, at_binaries = _pull_at_binaries(leftover, cwd)
    binaries = [
        _binary_part(item)
        for item in (*chip_items, *at_binaries)
        if item.kind in {AttachKind.IMAGE, AttachKind.PDF}
    ]
    extra_blocks: list[str] = []
    mentions = leftover
    for item in chip_items:
        if item.kind != AttachKind.TEXT:
            continue
        try:
            rel = item.path.relative_to(cwd.resolve()).as_posix()
        except ValueError:
            extra_blocks.append(_inline_file_block(item))
            continue
        tag = f"@{rel}"
        if tag not in mentions:
            mentions = f"{mentions} {tag}".strip()
    leftover = mentions
    leftover = _maybe_expand_skills(leftover, load_skill)
    expanded = expand_attachments(leftover, cwd, read_file) if leftover else ""
    if extra_blocks:
        expanded = "\n".join(
            part for part in [expanded, *extra_blocks] if part
        ).rstrip()
    if not binaries:
        return expanded
    if expanded:
        return [expanded, *binaries]
    return binaries
