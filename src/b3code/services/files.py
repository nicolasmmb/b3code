"""Índice de arquivos para o autocomplete `@`."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pathspec

from b3code.utils.fuzzy import rank_paths
from b3code.utils.paths import iter_workspace_files, safe_workspace_path


class FileIndex:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._spec: pathspec.PathSpec | None = None
        self._files: list[Path] = []
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

    def read(self, rel: str) -> str:
        return safe_workspace_path(rel, self.cwd).read_text(encoding="utf-8")

    def refresh(self) -> None:
        self.scan()

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        gi = self.cwd / ".gitignore"
        if not gi.exists():
            return None
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())

    def _collect(self) -> list[Path]:
        found: list[Path] = []
        for path in iter_workspace_files(self.cwd):
            rel = path.relative_to(self.cwd)
            if self._spec and self._spec.match_file(str(rel)):
                continue
            found.append(rel)
        return sorted(found, key=lambda p: str(p).lower())
