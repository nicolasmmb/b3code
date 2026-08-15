"""Índice de arquivos para o autocomplete `@`."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pathspec

from b3code.utils.fuzzy import rank_paths
from b3code.utils.paths import SKIP_DIRS, iter_workspace_files, safe_workspace_path
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
        spec = self._load_gitignore()
        self._install(spec, self._collect(spec))

    async def refresh(self) -> None:
        await asyncio.to_thread(self.scan)

    async def ensure_scanned(self) -> None:
        if self._ready:
            return
        await self.refresh()

    def search(self, query: str, limit: int = 20) -> list[Path]:
        return rank_paths(query, self._listed(), limit=limit)

    async def search_async(self, query: str, limit: int = 20) -> list[Path]:
        return await asyncio.to_thread(self.search, query, limit)

    def read(self, rel: str, *, limit: int | None = ATTACH_CHAR_LIMIT) -> str:
        path = safe_workspace_path(rel, self.cwd)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"not a text file: {rel}") from exc
        if limit is None:
            return text
        body, _truncated = truncate_chars(text, limit)
        return body

    def add_path(self, rel: str) -> None:
        if not self._ready:
            return
        posix = _posix(rel)
        if not _indexable(posix):
            return
        files = self._listed()
        if posix in files or len(files) >= INDEX_FILE_CAP:
            return
        files.append(posix)
        files.sort(key=str.lower)
        self._install(self._spec, files)

    def remove_path(self, rel: str) -> None:
        if not self._ready:
            return
        files = self._listed()
        try:
            files.remove(_posix(rel))
        except ValueError:
            return
        self._install(self._spec, files)

    def _listed(self) -> list[str]:
        with self._lock:
            return list(self._files)

    def _install(self, spec: pathspec.PathSpec | None, files: list[str]) -> None:
        with self._lock:
            self._spec = spec
            self._files = files
            self._ready = True

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        gi = self.cwd / ".gitignore"
        if not gi.exists():
            return None
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())

    def _collect(self, spec: pathspec.PathSpec | None) -> list[str]:
        found: list[str] = []
        for path in iter_workspace_files(
            self.cwd, skip_rel=lambda rel: _skip_rel(spec, rel)
        ):
            posix = path.relative_to(self.cwd).as_posix()
            if spec and spec.match_file(posix):
                continue
            found.append(posix)
            if len(found) >= INDEX_FILE_CAP:
                break
        return sorted(found, key=str.lower)


def _posix(rel: str) -> str:
    return rel.replace("\\", "/")


def _indexable(posix: str) -> bool:
    return not any(part in SKIP_DIRS for part in posix.split("/"))


def _skip_rel(spec: pathspec.PathSpec | None, rel: Path) -> bool:
    if spec is None:
        return False
    posix = rel.as_posix()
    return spec.match_file(posix) or spec.match_file(posix + "/")
