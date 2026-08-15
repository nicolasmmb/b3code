"""Sincroniza o FileIndex injetado com eventos de workspace. Sem widget."""

from __future__ import annotations

from collections.abc import Callable

from b3code.services.chat import ChatEvent
from b3code.services.files import FileIndex
from b3code.utils.diffview import FileChange


class IndexController:
    def __init__(
        self,
        files: FileIndex,
        on_listed: Callable[[], None],
        on_refresh: Callable[[], None],
    ) -> None:
        self._files = files
        self._on_listed = on_listed
        self._on_refresh = on_refresh

    def on_event(self, event: ChatEvent) -> None:
        if event.kind == "diff":
            self._index_diff(event.change)
            return
        if event.kind in {"done", "error"}:
            self._index_refresh()

    def _index_diff(self, change: FileChange | None) -> None:
        if change is None:
            return
        if change.deleted:
            self._files.remove_path(change.path)
        else:
            self._files.add_path(change.path)
        self._on_listed()

    def _index_refresh(self) -> None:
        self._on_refresh()
