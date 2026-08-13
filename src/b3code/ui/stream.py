"""Buffer de stream de texto. Puro — sem Textual."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class TextBuffer:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._lock = threading.Lock()
        self.scheduled = False

    @property
    def pending(self) -> list[str]:
        with self._lock:
            return list(self._chunks)

    def push(self, text: str) -> bool:
        """Acrescenta texto. True se o caller deve agendar o flush."""
        with self._lock:
            self._chunks.append(text)
            if self.scheduled:
                return False
            self.scheduled = True
            return True

    def drain(self) -> str:
        with self._lock:
            text = "".join(self._chunks)
            self._chunks.clear()
            self.scheduled = False
            return text

    def reset(self) -> None:
        with self._lock:
            self._chunks.clear()
            self.scheduled = False


class FlushScheduler:
    def __init__(
        self,
        schedule: Callable[..., Any],
        set_timer: Callable[..., Any],
        interval: float,
        on_flush: Callable[[], None],
    ) -> None:
        self._schedule = schedule
        self._set_timer = set_timer
        self._interval = interval
        self._on_flush = on_flush
        self._timer = None

    def request(self) -> None:
        self._schedule(self.arm)

    def arm(self) -> None:
        if self._timer is None:
            self._timer = self._set_timer(self._interval, self._fire)

    def _fire(self) -> None:
        self._timer = None
        self._on_flush()

    def cancel(self) -> None:
        if self._timer is None:
            return
        self._timer.stop()
        self._timer = None
