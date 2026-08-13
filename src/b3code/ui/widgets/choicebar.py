"""Barra de escolha (setas + Enter). Base de PlanBar e PermissionPicker."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from b3code.config.schema import DEFAULT_ACCENT


class QuietOptions(OptionList, can_focus=False):
    pass


class ChoiceBar(Vertical):
    CHOICES: tuple[tuple[str, str, str], ...] = ()
    SUMMARY_ID = ""
    OPTIONS_ID = ""
    FALLBACK = ""

    def __init__(self, accent: str = DEFAULT_ACCENT, **kwargs) -> None:
        super().__init__(**kwargs)
        self.accent = accent

    def compose(self) -> ComposeResult:
        yield Static("", id=self.SUMMARY_ID)
        yield QuietOptions(id=self.OPTIONS_ID)

    def hide(self) -> None:
        self.display = False

    def move(self, delta: int) -> None:
        options = self.query_one(f"#{self.OPTIONS_ID}", QuietOptions)
        idx = options.highlighted or 0
        idx = max(0, min(len(self.CHOICES) - 1, idx + delta))
        self.paint(idx)

    def current(self) -> str:
        idx = self.query_one(f"#{self.OPTIONS_ID}", OptionList).highlighted
        if idx is None:
            return self.FALLBACK
        return self.CHOICES[idx][0]

    def paint(self, idx: int) -> None:
        options = self.query_one(f"#{self.OPTIONS_ID}", QuietOptions)
        options.clear_options()
        rows: list[Option] = []
        for i, (_value, label, hint) in enumerate(self.CHOICES):
            mark = "›" if i == idx else " "
            body = f"{mark}  {label:<8} {hint}".rstrip()
            style = self.accent if i == idx else "#6e6e6e"
            rows.append(Option(Text(body, style=style)))
        options.add_options(rows)
        options.highlighted = idx

    def set_summary(self, text: str, accent: str | None = None) -> None:
        if accent:
            self.accent = accent
        self.query_one(f"#{self.SUMMARY_ID}", Static).update(text)
        self.display = True
        self.paint(0)
