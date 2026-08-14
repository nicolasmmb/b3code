"""Estado da barra de aprovação do plano."""

from __future__ import annotations

from collections.abc import Callable

from textual.containers import VerticalScroll
from textual.events import Key

from b3code.services.chat import ChatService
from b3code.ui.widgets.planbar import PlanBar


class PlanController:
    def __init__(
        self,
        chat: ChatService,
        bar: PlanBar,
        scroll: VerticalScroll,
        accent: str,
        on_send: Callable[[str], None],
        on_note: Callable[[str], None],
        on_badge: Callable[[], None],
        on_lock: Callable[[], None],
        on_unlock: Callable[[], None],
    ) -> None:
        self.awaiting = False
        self._chat = chat
        self._bar = bar
        self._scroll = scroll
        self._accent = accent
        self._on_send = on_send
        self._on_note = on_note
        self._on_badge = on_badge
        self._on_lock = on_lock
        self._on_unlock = on_unlock

    def set_accent(self, accent: str) -> None:
        self._accent = accent

    def consume_key(self, event: Key) -> bool:
        if not self.awaiting:
            return False
        if event.key in {"down"}:
            self._bar.move(1)
        elif event.key in {"up"}:
            self._bar.move(-1)
        elif event.key in {"j", "pagedown"}:
            self._scroll.scroll_down()
        elif event.key in {"k", "pageup"}:
            self._scroll.scroll_up()
        elif event.key == "enter":
            self.confirm()
        else:
            return True
        event.stop()
        event.prevent_default()
        return True

    def on_plan_ready(self, text: str) -> None:
        self.awaiting = True
        self._bar.show(text, self._accent)
        self._on_lock()

    def confirm(self, choice: str | None = None) -> None:
        pick = choice or self._bar.current()
        self.awaiting = False
        self._bar.hide()
        self._on_unlock()
        match pick:
            case "approve":
                prompt = self._chat.approve_plan()
                self._on_badge()
                self._on_send(prompt)
            case "quit":
                self._chat.exit_plan()
                self._on_badge()
                self._on_note("plan mode off")
            case _:
                pass

    def quit(self) -> None:
        self.confirm("quit")

    def reset(self) -> None:
        self.awaiting = False
        self._bar.hide()
        self._on_unlock()
