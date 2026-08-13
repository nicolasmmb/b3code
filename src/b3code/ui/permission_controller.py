"""Estado do picker de permissão do Shell."""

from __future__ import annotations

from textual.events import Key

from b3code.services.chat import ChatService
from b3code.ui.widgets.permission import PermissionPicker


class PermissionController:
    def __init__(
        self,
        chat: ChatService,
        picker: PermissionPicker,
        accent: str,
    ) -> None:
        self.awaiting = False
        self._chat = chat
        self._picker = picker
        self._accent = accent

    def consume_key(self, event: Key) -> bool:
        if not self.awaiting:
            return False
        delta = {"down": 1, "up": -1}.get(event.key)
        if delta is not None:
            self._picker.move(delta)
            event.stop()
            event.prevent_default()
            return True
        if event.key == "enter":
            self.confirm()
            event.stop()
            event.prevent_default()
            return True
        return True

    def show(self, command: str, paths: str) -> None:
        self.awaiting = True
        self._picker.show(command, paths, self._accent)

    def confirm(self, choice: str | None = None) -> None:
        pick = choice or self._picker.current()
        self.awaiting = False
        self._picker.hide()
        self._chat.answer_permission(pick)

    def deny(self) -> None:
        self.confirm("deny")

    def reset(self) -> None:
        self.awaiting = False
        self._picker.hide()
