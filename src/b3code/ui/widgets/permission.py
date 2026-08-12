"""Lista de permissão do Shell: setas + Enter. Highlight usa accent do JSON."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from b3code.config.schema import DEFAULT_ACCENT


class QuietOptions(OptionList, can_focus=False):
    pass

CHOICES = (
    ("once", "once", "this time"),
    ("always", "always", "remember"),
    ("deny", "deny", ""),
)


class PermissionPicker(Vertical):
    def __init__(self, accent: str = DEFAULT_ACCENT, **kwargs) -> None:
        super().__init__(**kwargs)
        self.accent = accent

    def compose(self) -> ComposeResult:
        yield Static("", id="permission-summary")
        yield QuietOptions(id="permission-options")

    def show(self, command: str, outside: str, accent: str | None = None) -> None:
        if accent:
            self.accent = accent
        line = command.replace("\n", " ")
        if len(line) > 72:
            line = line[:71] + "…"
        extra = f"\n   {outside}" if outside else ""
        self.query_one("#permission-summary", Static).update(f"▸  {line}{extra}")
        self.display = True
        self.paint(0)

    def hide(self) -> None:
        self.display = False

    def move(self, delta: int) -> None:
        options = self.query_one("#permission-options", QuietOptions)
        idx = options.highlighted or 0
        idx = max(0, min(len(CHOICES) - 1, idx + delta))
        self.paint(idx)

    def current(self) -> str:
        idx = self.query_one("#permission-options", OptionList).highlighted
        if idx is None:
            return "deny"
        return CHOICES[idx][0]

    def paint(self, idx: int) -> None:
        options = self.query_one("#permission-options", QuietOptions)
        options.clear_options()
        rows: list[Option] = []
        for i, (_value, label, hint) in enumerate(CHOICES):
            mark = "›" if i == idx else " "
            body = f"{mark}  {label:<8} {hint}".rstrip()
            style = self.accent if i == idx else "#6e6e6e"
            rows.append(Option(Text(body, style=style)))
        options.add_options(rows)
        options.highlighted = idx
