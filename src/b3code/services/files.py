"""Índice de arquivos para o autocomplete `@`."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pathspec

from b3code.utils.fuzzy import rank_paths
from b3code.utils.paths import iter_workspace_files, safe_workspace_path
from b3code.utils.prompt import ATTACH_CHAR_LIMIT
from b3code.utils.text import truncate_chars

INDEX_FILE_CAP = 20_000


class FileIndex:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._spec: pathspec.PathSpec | None = None
        self._files: list[str] = []
        self._ready = False
        self._lock = threading.Lock()

    def scan(self) -> None:
        with self._lock:
            self._spec = self._load_gitignore()
            self._files = self._collect()
            self._ready = True

    async def ensure_scanned(self) -> None:
        if self._ready:
            return
        await asyncio.to_thread(self.scan)

    def search(self, query: str, limit: int = 20) -> list[Path]:
        return rank_paths(query, self._files, limit=limit)

    def read(self, rel: str, *, limit: int | None = ATTACH_CHAR_LIMIT) -> str:
        text = safe_workspace_path(rel, self.cwd).read_text(encoding="utf-8")
        if limit is None:
            return text
        body, _truncated = truncate_chars(text, limit)
        return body

    def refresh(self) -> None:
        self.scan()

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        gi = self.cwd / ".gitignore"
        if not gi.exists():
            return None
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())

    def _skip_dir(self, rel: Path) -> bool:
        if self._spec is None:
            return False
        posix = rel.as_posix()
        return self._spec.match_file(posix) or self._spec.match_file(posix + "/")

    def _collect(self) -> list[str]:
        found: list[str] = []
        for path in iter_workspace_files(self.cwd, skip_rel=self._skip_dir):
            rel = path.relative_to(self.cwd)
            posix = rel.as_posix()
            if self._spec and self._spec.match_file(posix):
                continue
            found.append(posix)
            if len(found) >= INDEX_FILE_CAP:
                break
        return sorted(found, key=str.lower)
