"""Tools do workspace. FunctionToolset (não @agent.tool) para o agent ser recriável."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from b3code.utils.paths import SKIP_DIRS, iter_workspace_files, safe_workspace_path

_MAX_HITS = 50
_MAX_FILE_CHARS = 200_000


def workspace_toolset(cwd: Path) -> FunctionToolset:
    def read_file(path: str) -> str:
        """Read a UTF-8 text file relative to the workspace (or /work/...)."""
        target = safe_workspace_path(path, cwd)
        text = target.read_text(encoding="utf-8")
        if len(text) > _MAX_FILE_CHARS:
            return text[:_MAX_FILE_CHARS] + "\n...[truncated]"
        return text

    def list_dir(path: str = ".") -> list[str]:
        """List files in a directory. Directories end with /."""
        target = safe_workspace_path(path, cwd)
        names: list[str] = []
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if child.name in SKIP_DIRS:
                continue
            names.append(child.name + ("/" if child.is_dir() else ""))
        return names

    def grep(pattern: str, path: str = ".") -> str:
        """Search workspace files for a regex. Returns path:line:text (max 50)."""
        rx = re.compile(pattern)
        root = safe_workspace_path(path, cwd)
        hits: list[str] = []
        for file in _iter_text_files(root):
            try:
                lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            rel = file.relative_to(cwd.resolve())
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}:{line}")
                    if len(hits) >= _MAX_HITS:
                        return "\n".join(hits)
        return "\n".join(hits) or "(no matches)"

    def write_file(path: str, content: str) -> str:
        """Write UTF-8 content to a workspace file, creating parents."""
        target = safe_workspace_path(path, cwd)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {target.relative_to(cwd.resolve())}"

    return FunctionToolset(tools=[read_file, list_dir, grep, write_file])


def _iter_text_files(root: Path):
    yield from iter_workspace_files(root, max_size=1_000_000)
