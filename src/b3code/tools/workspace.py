"""Tools do workspace. FunctionToolset (não @agent.tool) para o agent ser recriável."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from b3code.utils.diffview import FileChange, diff_texts
from b3code.utils.paths import SKIP_DIRS, iter_workspace_files, safe_workspace_path

_MAX_HITS = 50
_MAX_FILE_CHARS = 200_000


def workspace_toolset(
    cwd: Path,
    on_change: Callable[[FileChange], None] | None = None,
    can_write: Callable[[Path], bool] | None = None,
    *,
    include_write: bool = True,
    max_file_chars: int = _MAX_FILE_CHARS,
    max_hits: int = _MAX_HITS,
) -> FunctionToolset:
    def _rel(target: Path) -> str:
        return str(target.relative_to(cwd.resolve()))

    def _guard(target: Path) -> None:
        if can_write is not None and not can_write(target):
            raise ModelRetry(
                "plan mode: only .b3code/plan.md is writable — use write_plan_file"
            )

    def _commit(target: Path, old: str, new: str) -> FileChange:
        change = diff_texts(_rel(target), old, new)
        if new == "":
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding="utf-8")
        if on_change is not None:
            on_change(change)
        return change

    def _read_text(target: Path) -> str:
        return target.read_text(encoding="utf-8")

    def read_file(
        path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        """Read a UTF-8 text file. Optional 1-indexed inclusive line range (N|line)."""
        target = safe_workspace_path(path, cwd)
        text = _read_text(target)
        if start_line is None and end_line is None:
            return _truncate(text, max_file_chars)
        return _truncate(_line_range(text, start_line, end_line, path), max_file_chars)

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
                if not rx.search(line):
                    continue
                hits.append(f"{rel}:{i}:{line}")
                if len(hits) >= max_hits:
                    return "\n".join(hits)
        return "\n".join(hits) or "(no matches)"

    def write_file(path: str, content: str) -> str:
        """Create or overwrite a workspace file. Prefer replace_in_file for edits."""
        target = safe_workspace_path(path, cwd)
        _guard(target)
        old = ""
        if target.exists() and target.is_file():
            try:
                old = _read_text(target)
            except OSError:
                old = ""
        change = _commit(target, old, content)
        return f"wrote {_rel(target)} (+{change.added} -{change.removed})"

    def replace_in_file(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> str:
        """Replace a literal substring. Fails if old is missing or not unique (unless replace_all)."""
        if old == "":
            raise ModelRetry("old must be a non-empty literal substring")
        target = safe_workspace_path(path, cwd)
        _guard(target)
        if not target.is_file():
            raise ModelRetry(f"not a file: {path}")
        text = _read_text(target)
        n = _require_unique_span(text, old, path, replace_all)
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        change = _commit(target, text, updated)
        return f"replaced {n} in {_rel(target)} (+{change.added} -{change.removed})"

    def delete_file(path: str) -> str:
        """Delete a workspace file (not a directory)."""
        target = safe_workspace_path(path, cwd)
        _guard(target)
        if not target.exists():
            raise ModelRetry(f"missing: {path}")
        if target.is_dir():
            raise ModelRetry(f"refusing to delete directory: {path}")
        old = _read_text(target)
        _commit(target, old, "")
        return f"deleted {_rel(target)}"

    def move_file(src: str, dest: str, overwrite: bool = False) -> str:
        """Rename or move a file inside the workspace."""
        source = safe_workspace_path(src, cwd)
        target = safe_workspace_path(dest, cwd)
        _guard(source)
        _guard(target)
        if not source.is_file():
            raise ModelRetry(f"not a file: {src}")
        if target.exists() and not overwrite:
            raise ModelRetry(f"dest exists: {dest} — pass overwrite=True")
        if target.is_dir():
            raise ModelRetry(f"dest is a directory: {dest}")
        body = _read_text(source)
        dest_old = ""
        if target.exists() and target.is_file():
            dest_old = _read_text(target)
        if source.resolve() != target.resolve():
            source.unlink()
        change = _commit(target, dest_old, body)
        return f"moved {_rel(source) if source.exists() else src} → {_rel(target)} (+{change.added} -{change.removed})"

    tools = [read_file, list_dir, grep]
    if include_write:
        tools.extend([write_file, replace_in_file, delete_file, move_file])
    return FunctionToolset(tools=tools)  # type: ignore[arg-type]


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _line_range(
    text: str, start_line: int | None, end_line: int | None, path: str
) -> str:
    lines = text.splitlines()
    start = max(1, start_line or 1)
    end = min(len(lines), end_line or len(lines))
    if start > end or start > len(lines):
        raise ModelRetry(f"empty range {start}-{end} in {path} ({len(lines)} lines)")
    return "\n".join(f"{i}|{lines[i - 1]}" for i in range(start, end + 1))


def _require_unique_span(text: str, old: str, path: str, replace_all: bool) -> int:
    count = text.count(old)
    if count == 0:
        raise ModelRetry(f"old not found in {path}")
    if count > 1 and not replace_all:
        raise ModelRetry(
            f"old matches {count} times in {path} — pass replace_all=True or more context"
        )
    return count


def _iter_text_files(root: Path):
    yield from iter_workspace_files(root, max_size=1_000_000)
