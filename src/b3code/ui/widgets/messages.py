"""Blocos do chat: user, assistant (markdown), tool, nota de sistema, diff."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, Key
from textual.widgets import Markdown, Static

from b3code.utils.diffview import (
    DiffLine,
    FileChange,
    fold_label,
    hidden_count,
    visible,
)
from b3code.utils.errors import split_error_summary
from b3code.utils.prompt import split_display_chips

# Grok-like: fundo na linha inteira, sem prefixo +/- no código.
_ADD = "#b7d5b4 on #1c2b1e"
_DEL = "#e0a3a3 on #2e1a1a"
_NUM = "#6e6e6e"
_CTX = "#d4d4d4"
_HEAD = "#9a9a9a"
_FILE = "#c9a227"
_FOLD = "#9a9a9a"
_ERR = "#c45c5c"
_ERR_MSG = "#e0a3a3"


class FileChip(Static):
    """Pill `[TIPO - arquivo]` no prompt enviado."""

    def __init__(self, label: str, name: str) -> None:
        super().__init__(
            Text.assemble((label, "dim"), (" - ", "dim"), (name, "")),
            classes="file-chip",
        )


class UserMessage(Vertical):
    """Prompt do user: chips de anexo + markdown do texto."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        chips, body = split_display_chips(self._text)
        if chips:
            with Horizontal(classes="user-chips"):
                for label, name in chips:
                    yield FileChip(label, name)
        if body:
            yield Markdown(body, classes="user-body")
        elif not chips:
            yield Markdown(self._text, classes="user-body")


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


def _handle_error_keys(block: ErrorBlock, event: Key) -> bool:
    if event.key in {"enter", "space"}:
        if block.expandable:
            block.toggle()
        else:
            block.copy()
        return True
    if event.key in {"c", "y"}:
        block.copy()
        return True
    if event.key == "escape" and block.expanded:
        block.toggle()
        return True
    return False


class ErrorFold(Static, can_focus=True):
    """Seta no mesmo idioma do DiffFold."""

    def on_click(self, event: Click) -> None:
        block = self.parent
        if isinstance(block, ErrorBlock):
            block.toggle()
        event.stop()

    def on_key(self, event: Key) -> None:
        block = self.parent
        if not isinstance(block, ErrorBlock):
            return
        if not _handle_error_keys(block, event):
            return
        event.stop()
        event.prevent_default()


class ErrorBlock(Vertical, can_focus=False):
    """Erro no chat, no mesmo recorte do Diff: header ◆, fold ▸, `c` copia."""

    def __init__(self, summary: str, detail: str = "") -> None:
        super().__init__()
        self.summary = summary
        self.detail = detail.rstrip() + "\n" if detail else ""
        self.kind, self.message = split_error_summary(summary)
        self.expanded = False
        self._header = Static(render_error_header(self.kind), classes="error-header")
        self._message = Static(
            Text(self.message, style=_ERR_MSG), classes="error-message"
        )
        self._body = Static(Text(self.detail), markup=False, classes="error-body")
        self._fold = ErrorFold("")

    @property
    def expandable(self) -> bool:
        return bool(self.detail) and self.detail.strip() != self.summary.strip()

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._message
        yield self._body
        yield self._fold

    def on_mount(self) -> None:
        self._paint()

    def on_click(self, event: Click) -> None:
        if self.expandable:
            self.toggle()
        else:
            self.copy()
        event.stop()

    def toggle(self) -> None:
        if not self.expandable:
            return
        self.expanded = not self.expanded
        self._paint()

    def copy(self) -> None:
        payload = self.detail or (self.summary + "\n")
        self.app.copy_to_clipboard(payload)
        self.app.notify("error copied")

    def _paint(self) -> None:
        can_open = self.expandable
        self._body.display = self.expanded and can_open
        self._fold.display = can_open
        if can_open:
            self._fold.update(error_fold_label(self.detail, expanded=self.expanded))
        self.refresh(layout=True)


def render_error_header(kind: str) -> Text:
    out = Text()
    out.append("◆ ", style=_HEAD)
    out.append("Error  ", style=_HEAD)
    if kind:
        out.append(kind, style=_ERR)
    return out


def error_fold_label(detail: str, *, expanded: bool) -> str:
    if expanded:
        return "▾  recolher  ·  [c]opy"
    lines = detail.count("\n") or 1
    return f"▸  {lines} linhas  ·  c"


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
    """Saída de comando `/` e cancel — não é mensagem da LLM."""


class RoleLabel(Static):
    def __init__(self, name: str) -> None:
        super().__init__(name, classes="role")


def _fmt(status: str, tool: str, detail: str) -> str:
    mark = {"running": "…", "done": "✓", "error": "✗"}.get(status, "·")
    extra = f"  {detail}" if detail else ""
    return f"{mark} {tool}{extra}"
