"""Gate de path do Shell. Único writer de `shell_allowed_paths`."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.utils.paths import escaped_paths


@dataclass
class PermissionRequest:
    command: str
    paths: list[str]


class PermissionDenied(Exception):
    pass


class PermissionGate:
    def __init__(self, store: ConfigStore, config: AppConfig, cwd: Path) -> None:
        self.store = store
        self.config = config
        self.cwd = cwd
        self.pending: asyncio.Future[str] | None = None
        self.on_ask: Callable[[PermissionRequest], None] | None = None

    def is_allowed(self, path: Path) -> bool:
        path = path.resolve()
        for raw in self.config.shell_allowed_paths:
            allowed = Path(raw).expanduser().resolve()
            if path == allowed or path.is_relative_to(allowed):
                return True
        return False

    async def ensure(self, command: str) -> None:
        outside = [p for p in escaped_paths(command, self.cwd) if not self.is_allowed(p)]
        if not outside:
            return
        answer = await self.ask(command, outside)
        if answer == "deny":
            raise PermissionDenied(f"denied: {', '.join(map(str, outside))}")
        if answer == "always":
            for path in outside:
                self.persist(path)

    def answer(self, choice: str) -> None:
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(choice)

    async def ask(self, command: str, paths: list[Path]) -> str:
        loop = asyncio.get_running_loop()
        self.pending = loop.create_future()
        if self.on_ask is not None:
            self.on_ask(PermissionRequest(command, [str(p) for p in paths]))
        try:
            return await self.pending
        finally:
            self.pending = None

    def persist(self, path: Path) -> None:
        text = str(path.resolve())
        if text not in self.config.shell_allowed_paths:
            self.config.shell_allowed_paths.append(text)
            self.store.save(self.config)
