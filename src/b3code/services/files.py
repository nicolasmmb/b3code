"""Índice de arquivos para o autocomplete `@`."""

from __future__ import annotations

from pathlib import Path

import pathspec

from b3code.utils.fuzzy import rank_paths
from b3code.utils.paths import safe_workspace_path

_SKIP_DIRS = {".git", ".venv", ".b3code", "node_modules", "__pycache__", "dist"}


class FileIndex:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self._spec = self._load_gitignore()
        self._files = self._scan()

    def search(self, query: str, limit: int = 20) -> list[Path]:
        return rank_paths(query, self._files, limit=limit)

    def read(self, rel: str) -> str:
        return safe_workspace_path(rel, self.cwd).read_text(encoding="utf-8")

    def refresh(self) -> None:
        self._files = self._scan()

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        gi = self.cwd / ".gitignore"
        if not gi.exists():
            return None
        return pathspec.PathSpec.from_lines("gitignore", gi.read_text().splitlines())

    def _scan(self) -> list[Path]:
        found: list[Path] = []
        for path in self.cwd.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.cwd)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if self._spec and self._spec.match_file(str(rel)):
                continue
            found.append(rel)
        return sorted(found, key=lambda p: str(p).lower())
