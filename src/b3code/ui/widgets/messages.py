"""Blocos do chat: user, assistant (markdown), tool, nota de sistema, diff."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Click, Key
from textual.widgets import Markdown, Static

from b3code.utils.diffview import (
    DiffLine,
    FileChange,
    fold_label,
    hidden_count,
    visible,
)

# Grok-like: fundo na linha inteira, sem prefixo +/- no código.
_ADD = "#b7d5b4 on #1c2b1e"
_DEL = "#e0a3a3 on #2e1a1a"
_NUM = "#6e6e6e"
_CTX = "#d4d4d4"
_HEAD = "#9a9a9a"
_FILE = "#c9a227"
_FOLD = "#9a9a9a"


class UserMessage(Markdown):
    """Prompt do user. Markdown para `**bold**` / code, igual o assistant."""


class AssistantMessage(Markdown):
    """Resposta da LLM. `update()` a cada delta do stream."""


class PlanDoc(Markdown):
    """Preview do plan.md (Grok: o plano inteiro, não uma linha)."""


class DiffFold(Static, can_focus=True):
    """Seta para revelar o que o preview omitiu."""

    def __init__(self, label: str) -> None:
        super().__init__(label, classes="diff-fold")

    def on_click(self, event: Click) -> None:
        block = self.parent
        if isinstance(block, DiffBlock):
            block.toggle()
        event.stop()

    def on_key(self, event: Key) -> None:
        if event.key not in {"enter", "space"}:
            return
        block = self.parent
        if isinstance(block, DiffBlock):
            block.toggle()
        event.stop()
        event.prevent_default()


class DiffBlock(Vertical, can_focus=False):
    """Edit no estilo Grok: números, faixa vermelha/verde, fold."""

    def __init__(self, change: FileChange) -> None:
        super().__init__()
        self.change = change
        self.expanded = False
        self._header = Static(render_header(change))
        self._body = Static("")
        self._fold: DiffFold | None = None

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        if hidden_count(self.change, expanded=False) > 0:
            self._fold = DiffFold(fold_label(self.change, expanded=False))
            yield self._fold

    def on_mount(self) -> None:
        self._paint()

    def toggle(self) -> None:
        if hidden_count(self.change, expanded=False) == 0:
            return
        self.expanded = not self.expanded
        self._paint()

    def _paint(self) -> None:
        width = self.size.width if self.size.width > 0 else 80
        lines = visible(self.change, expanded=self.expanded)
        self._body.update(render_lines(lines, width))
        if self._fold is not None:
            label = fold_label(self.change, expanded=self.expanded)
            self._fold.update(label)
            self._fold.display = bool(label)
        self.refresh(layout=True)


def render_header(change: FileChange) -> Text:
    out = Text()
    out.append("◆ ", style=_HEAD)
    out.append("Edit  ", style=_HEAD)
    out.append(change.path, style=_FILE)
    out.append(f"  +{change.added} −{change.removed}", style=_NUM)
    return out


def render_lines(lines: tuple[DiffLine, ...], width: int = 80) -> Text:
    out = Text()
    for line in lines:
        out.append_text(_paint_line(line, width))
    return out


def render_diff(change: FileChange, width: int = 80, *, expanded: bool = False) -> Text:
    out = render_header(change)
    out.append("\n")
    out.append_text(render_lines(visible(change, expanded=expanded), width))
    label = fold_label(change, expanded=expanded)
    if label:
        out.append(label + "\n", style=_FOLD)
    return out


def _paint_line(line: DiffLine, width: int) -> Text:
    gutter = f"{line.number:>4} "
    room = max(8, width - len(gutter))
    body = line.text.replace("\t", "    ")[:room].ljust(room)
    row = gutter + body + "\n"
    if line.kind == "+":
        return Text(row, style=_ADD)
    if line.kind == "-":
        return Text(row, style=_DEL)
    painted = Text()
    painted.append(gutter, style=_NUM)
    painted.append(body + "\n", style=_CTX)
    return painted


class ToolRow(Static):
    def __init__(self, tool: str, detail: str = "", status: str = "running") -> None:
        self.tool = tool
        self.detail = detail
        super().__init__(_fmt(status, tool, detail), classes=status)

    def set_status(self, status: str, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        self.set_classes(status)
        self.update(_fmt(status, self.tool, self.detail))


class SystemNote(Static):
    """Saída de comando `/` e erros — não é mensagem da LLM."""


class RoleLabel(Static):
    def __init__(self, name: str) -> None:
        super().__init__(name, classes="role")


def _fmt(status: str, tool: str, detail: str) -> str:
    mark = {"running": "…", "done": "✓", "error": "✗"}.get(status, "·")
    extra = f"  {detail}" if detail else ""
    return f"{mark} {tool}{extra}"
