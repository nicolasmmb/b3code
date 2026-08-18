"""Resolução de paths do workspace.

A LLM (via CodeMode) pode passar `src/a.py` ou `/work/src/a.py`
porque o sandbox monta o cwd em `/work`.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path


def resolve_agent_path(path: str, cwd: Path) -> Path:
    """`/work/...` é o mount do CodeMode — mesmo disco que o cwd."""
    raw = path
    if raw == "/work" or raw.startswith("/work/"):
        raw = raw[len("/work") :].lstrip("/") or "."
    resolved = Path(raw).expanduser()
    if not resolved.is_absolute():
        resolved = cwd / resolved
    return resolved.resolve()


def safe_workspace_path(path: str, cwd: Path, *, allowed: Iterable[Path] = ()) -> Path:
    """Resolve `path` dentro de `cwd` (ou de um base em `allowed`).

    `allowed` libera leituras pontuais fora do workspace (ex.: o plano
    central em plan mode). Default vazio = comportamento atual.
    """
    resolved = resolve_agent_path(path, cwd)
    cwd_resolved = cwd.resolve()
    if resolved.is_relative_to(cwd_resolved):
        return resolved
    for base in allowed:
        try:
            if resolved.is_relative_to(base.resolve()):
                return resolved
        except OSError:
            continue
    raise ValueError(f"path escapes workspace: {path}")


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
        resolved = resolve_agent_path(raw, cwd)
        if not resolved.is_relative_to(cwd) and resolved not in found:
            found.append(resolved)
    return found


def iter_workspace_files(
    root: Path,
    *,
    skip_dirs: Iterable[str] = (),
    skip_exts: Iterable[str] = (),
    max_size: int | None = None,
    skip_rel: Callable[[Path], bool] | None = None,
) -> Iterator[Path]:
    """Walk files under `root`, pruning skip_dirs at each level (no post-filter rglob)."""
    root = root.resolve()
    skip_dirs = frozenset(skip_dirs)
    skip_exts = frozenset(ext.lower() for ext in skip_exts)
    if root.is_file():
        yield root
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.name in skip_dirs:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            rel = Path(entry.path).relative_to(root)
                            if skip_rel is not None and skip_rel(rel):
                                continue
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if skip_exts and Path(entry.path).suffix.lower() in skip_exts:
                            continue
                        if (
                            max_size is not None
                            and entry.stat(follow_symlinks=False).st_size > max_size
                        ):
                            continue
                        yield Path(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` via temp + os.replace so a crash never leaves a half JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _ = tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: object, *, indent: int = 2) -> None:
    """Write `data` as pretty JSON via atomic_write_text."""
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")
