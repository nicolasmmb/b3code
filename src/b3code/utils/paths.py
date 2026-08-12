"""Resolução de paths do workspace.

A LLM (via CodeMode) pode passar `src/a.py` ou `/work/src/a.py`
porque o sandbox monta o cwd em `/work`.
"""

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
