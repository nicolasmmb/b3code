"""Dropdown acima do prompt. Sem focus próprio — o Input dirige as setas."""

from textual.widgets import OptionList
from textual.widgets.option_list import Option

from b3code.commands.types import Suggestion


class Autocomplete(OptionList, can_focus=False):
    def __init__(self) -> None:
        super().__init__(id="autocomplete")
        self._items: list[Suggestion] = []

    def set_suggestions(self, items: list[Suggestion]) -> None:
        self._items = items
        self.clear_options()
        if not items:
            self.display = False
            return
        self.display = True
        self.add_options([Option(f"{item.label}  {item.hint}") for item in items])
        self.highlighted = 0

    def current(self) -> Suggestion | None:
        idx = self.highlighted
        if idx is None or idx >= len(self._items):
            return None
        return self._items[idx]
