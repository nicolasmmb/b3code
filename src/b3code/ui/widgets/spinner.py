"""Spinner animado (braille) para estados de processamento."""

from __future__ import annotations

from textual.widgets import Static

FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class Spinner(Static):
    """Static animado: cicla frames braille via `set_interval`."""

    def __init__(self, label: str = "thinking", **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._frame = 0
        self._timer = None

    def on_mount(self) -> None:
        self.update(f"{FRAMES[0]} {self._label}")
        self._timer = self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(FRAMES)
        self.update(f"{FRAMES[self._frame]} {self._label}")

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
