"""Aprovação do plano: a / s / q. Resumo estruturado (título + seções)."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from b3code.config.schema import DEFAULT_ACCENT
from b3code.services.planner import plan_meta
from b3code.ui.widgets.permission import QuietOptions

CHOICES = (
    ("approve", "approve", "implement"),
    ("revise", "revise", "keep planning"),
    ("quit", "quit", "leave plan mode"),
)


class PlanBar(Vertical):
    def __init__(self, accent: str = DEFAULT_ACCENT, **kwargs) -> None:
        super().__init__(**kwargs)
        self.accent = accent

    def compose(self) -> ComposeResult:
        yield Static("", id="plan-summary")
        yield QuietOptions(id="plan-options")

    def show(self, preview: str, accent: str | None = None) -> None:
        if accent:
            self.accent = accent
        if not preview.strip():
            summary = "▸  plan  (no plan written yet)\n   a approve   s revise   q quit"
        else:
            title, heads, nlines = plan_meta(preview)
            bits = " · ".join(heads) if heads else "no sections"
            if len(bits) > 64:
                bits = bits[:63] + "…"
            summary = (
                f"▸  {title}\n"
                f"   {len(heads)} sections · {nlines} lines\n"
                f"   {bits}"
            )
        self.query_one("#plan-summary", Static).update(summary)
        self.display = True
        self.paint(0)

    def hide(self) -> None:
        self.display = False

    def move(self, delta: int) -> None:
        options = self.query_one("#plan-options", QuietOptions)
        idx = options.highlighted or 0
        idx = max(0, min(len(CHOICES) - 1, idx + delta))
        self.paint(idx)

    def current(self) -> str:
        idx = self.query_one("#plan-options", OptionList).highlighted
        if idx is None:
            return "quit"
        return CHOICES[idx][0]

    def paint(self, idx: int) -> None:
        options = self.query_one("#plan-options", QuietOptions)
        options.clear_options()
        rows: list[Option] = []
        for i, (_value, label, hint) in enumerate(CHOICES):
            mark = "›" if i == idx else " "
            body = f"{mark}  {label:<8} {hint}".rstrip()
            style = self.accent if i == idx else "#6e6e6e"
            rows.append(Option(Text(body, style=style)))
        options.add_options(rows)
        options.highlighted = idx
