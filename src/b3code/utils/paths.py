"""Resolução de paths do workspace.

A LLM (via CodeMode) pode passar `src/a.py` ou `/work/src/a.py`
porque o sandbox monta o cwd em `/work`.
"""

from __future__ import annotations

import shlex
from pathlib import Path


def safe_workspace_path(path: str, cwd: Path) -> Path:
    """Resolve `path` dentro de `cwd`. Recusa escape do workspace."""
    raw = path
    if raw.startswith("/work"):
        raw = raw[len("/work") :].lstrip("/") or "."
    resolved = (cwd / raw).resolve()
    cwd_resolved = cwd.resolve()
    if not resolved.is_relative_to(cwd_resolved):
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


def escaped_paths(command: str, cwd: Path) -> list[Path]:
    """Tokens `/` `~` `..` que resolvem fora do cwd. Não é parser de shell."""
    cwd = cwd.resolve()
    found: list[Path] = []
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for raw in tokens:
        if not (raw.startswith(("/", "~")) or raw.startswith("..") or "/.." in raw):
            continue
        resolved = Path(raw).expanduser()
        if not resolved.is_absolute():
            resolved = cwd / resolved
        resolved = resolved.resolve()
        if not resolved.is_relative_to(cwd) and resolved not in found:
            found.append(resolved)
    return found
