"""Tokens `@arquivo` no prompt e blocos `<file>` enviados ao modelo.

Anexos entram no *user turn* (não no system prompt) para o prefixo
estático do cache Azure continuar válido.
"""

from __future__ import annotations

import re
from pathlib import Path

AT_TOKEN = re.compile(r"(?<!\S)@([^\s]+)")
FILE_BLOCK = re.compile(r'<file path="[^"]+">.*?</file>\s*', re.DOTALL)


def current_token(text: str, cursor: int) -> tuple[int, int, str]:
    """Token sob o cursor (do último espaço até o cursor)."""
    start = text.rfind(" ", 0, cursor) + 1
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
        except (OSError, ValueError):
            chunks.append(f"(could not read @{rel})")
            continue
        chunks.append(f'<file path="{rel}">\n{body}\n</file>')
    return "\n".join(chunks).rstrip()


def strip_file_blocks(text: str) -> str:
    """Tira blocos `<file>` na hora de *mostrar* o user turn."""
    return FILE_BLOCK.sub("", text).strip()


