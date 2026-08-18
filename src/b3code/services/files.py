"""Índice de arquivos para o autocomplete `@`.

O disco é a fonte. A UI chama só `search_async`, que nunca re-scana:
ela garante um scan inicial (single-flight) e ranqueia da memória.
O frescor do disco é mantido por `refresh_if_stale`, rodado em loop
pelo `PromptBar.refresh_index`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pathspec

from b3code.utils.fuzzy import rank_paths
from b3code.utils.paths import iter_workspace_files, safe_workspace_path
from b3code.utils.prompt import ATTACH_CHAR_LIMIT
from b3code.utils.text import truncate_chars

INDEX_FILE_CAP = 20_000
REFRESH_STALE_S = 5.0


class FileIndex:
    def __init__(
        self,
        cwd: Path,
        *,
        skip_dirs: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
        skip_exts: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
        cap: int = INDEX_FILE_CAP,
        refresh_seconds: float = REFRESH_STALE_S,
    ) -> None:
        self.cwd = cwd.resolve()
        self._skip_dirs = frozenset(skip_dirs)
        self._skip_exts = frozenset(ext.lower() for ext in skip_exts)
        self._cap = max(1, cap)
        self._refresh_seconds = max(0.1, refresh_seconds)
        self._spec: pathspec.PathSpec | None = None
        self._files: list[str] = []
        self._ready = False
        self._scanned_at = 0.0
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._scan_gate = asyncio.Lock()

    def scan(self) -> None:
        with self._scan_lock:
            spec = self._load_gitignore()
            self._install(spec, self._collect(spec))
            with self._lock:
                self._scanned_at = time.monotonic()

    async def refresh(self) -> None:
        async with self._scan_gate:
            await asyncio.to_thread(self.scan)

    async def ensure_scanned(self) -> None:
        """Garante um scan inicial com single-flight (nunca dois walks juntos)."""
        if self._ready:
            return
        async with self._scan_gate:
            if self._ready:
                return
            await asyncio.to_thread(self.scan)

    async def ensure_fresh(self, *, max_age: float = 0.3) -> None:
        if self._ready and (time.monotonic() - self._scanned_at) < max_age:
            return
        await self.refresh()

    async def refresh_if_stale(self, *, min_age: float | None = None) -> None:
        """Re-scana só se o índice está velho e nenhum scan está em andamento."""
        threshold = self._refresh_seconds if min_age is None else min_age
        if self._ready and (time.monotonic() - self._scanned_at) < threshold:
            return
        if self._scan_gate.locked():
            return
        await self.refresh()

    def search(self, query: str, limit: int = 20) -> list[Path]:
        return rank_paths(query, self._listed(), limit=limit)

    async def search_async(
        self, query: str, limit: int = 20, *, max_age: float | None = None
    ) -> list[Path]:
        """Porta da UI: garante um scan inicial e ranqueia da memória.

        Por default nunca re-scana — digitar não espera o walk.
        `max_age` explícito (testes) ainda força `ensure_fresh`.
        """
        await self.ensure_scanned()
        if max_age is not None:
            await self.ensure_fresh(max_age=max_age)
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
        if not self._indexable(posix):
            return
        files = self._listed()
        if posix in files or len(files) >= self._cap:
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

    def _indexable(self, posix: str) -> bool:
        if any(part in self._skip_dirs for part in posix.split("/")):
            return False
        ext = Path(posix).suffix.lower()
        return not (ext and ext in self._skip_exts)

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        gi = self.cwd / ".gitignore"
        if not gi.exists():
            return None
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())

    def _collect(self, spec: pathspec.PathSpec | None) -> list[str]:
        found: list[str] = []
        for path in iter_workspace_files(
            self.cwd,
            skip_dirs=self._skip_dirs,
            skip_exts=self._skip_exts,
            skip_rel=lambda rel: _skip_rel(spec, rel),
        ):
            posix = path.relative_to(self.cwd).as_posix()
            if spec and spec.match_file(posix):
                continue
            found.append(posix)
            if len(found) >= self._cap:
                break
        return sorted(found, key=str.lower)


def _posix(rel: str) -> str:
    return rel.replace("\\", "/")


def _skip_rel(spec: pathspec.PathSpec | None, rel: Path) -> bool:
    if spec is None:
        return False
    posix = rel.as_posix()
    return spec.match_file(posix) or spec.match_file(posix + "/")
