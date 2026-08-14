"""Blocos do chat: user, assistant (markdown), tool, nota de sistema, diff."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, Key
from textual.widget import Widget
from textual.widgets import Label, Markdown, Static
from textual.widgets.markdown import MarkdownFence

from b3code.config.schema import ThemeColors
from b3code.ui.palette import RichPalette, rich_palette, theme_of
from b3code.utils.diffview import (
    DiffLine,
    FileChange,
    fold_label,
    hidden_count,
    visible,
)
from b3code.utils.errors import split_error_summary
from b3code.utils.prompt import split_display_chips


class FileChip(Static):
    """Pill `[TIPO - arquivo]` no prompt enviado."""

    def __init__(self, label: str, name: str) -> None:
        super().__init__(
            Text.assemble((label, "dim"), (" - ", "dim"), (name, "")),
            classes="file-chip",
        )


def _owning_fence(widget: Widget) -> CopyableFence | None:
    node = widget.parent
    while node is not None:
        if isinstance(node, CopyableFence):
            return node
        node = node.parent
    return None


def fence_lang(lexer: str) -> str:
    word = lexer.split()[0] if lexer else ""
    return word or "code"


class FenceCopy(Static, can_focus=True):
    """Botão ⧉ copy no canto do fence."""

    def __init__(self) -> None:
        super().__init__("⧉ copy", classes="fence-copy")

    def on_click(self, event: Click) -> None:
        fence = _owning_fence(self)
        if fence is not None:
            fence.copy()
        event.stop()

    def on_key(self, event: Key) -> None:
        if event.key not in {"enter", "space", "c", "y"}:
            return
        fence = _owning_fence(self)
        if fence is not None:
            fence.copy()
        event.stop()
        event.prevent_default()


class CopyableFence(MarkdownFence):
    """Fence com linguagem à esquerda e ⧉ copy à direita."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="fence-bar"):
            yield Static(
                Text.assemble(("◆ ", _HEAD), (fence_lang(self.lexer), _HEAD)),
                classes="fence-lang",
            )
            yield FenceCopy()
        yield Label(self._highlighted_code, id="code-content", expand=True)

    def copy(self) -> None:
        payload = self.code if self.code.endswith("\n") else f"{self.code}\n"
        self.app.copy_to_clipboard(payload)
        self.app.notify("copied")


class ChatMarkdown(Markdown):
    """Markdown do chat: fences com botão de copiar."""

    BLOCKS = {
        **Markdown.BLOCKS,
        "fence": CopyableFence,
        "code_block": CopyableFence,
    }


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
            yield ChatMarkdown(body, classes="user-body")
        elif not chips:
            yield ChatMarkdown(self._text, classes="user-body")


class AssistantMessage(ChatMarkdown):
    """Resposta da LLM. `update()` a cada delta do stream."""


class PlanDoc(ChatMarkdown):
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
        colors = rich_palette(theme_of(self))
        width = self.size.width if self.size.width > 0 else 80
        lines = visible(self.change, expanded=self.expanded)
        self._header.update(render_header(self.change, colors))
        self._body.update(render_lines(lines, width, colors))
        if self._fold is not None:
            label = fold_label(self.change, expanded=self.expanded)
            self._fold.update(label)
            self._fold.display = bool(label)
        self.refresh(layout=True)


def render_header(change: FileChange, colors: RichPalette | None = None) -> Text:
    colors = colors or rich_palette()
    out = Text()
    out.append("◆ ", style=colors.head)
    out.append("Edit  ", style=colors.head)
    out.append(change.path, style=colors.file)
    out.append(f"  +{change.added} −{change.removed}", style=colors.number)
    return out


def render_lines(
    lines: tuple[DiffLine, ...],
    width: int = 80,
    colors: RichPalette | None = None,
) -> Text:
    colors = colors or rich_palette()
    out = Text()
    for line in lines:
        out.append_text(_paint_line(line, width, colors))
    return out


def render_diff(
    change: FileChange,
    width: int = 80,
    *,
    expanded: bool = False,
    theme: ThemeColors | None = None,
) -> Text:
    colors = rich_palette(theme)
    out = render_header(change, colors)
    out.append("\n")
    out.append_text(render_lines(visible(change, expanded=expanded), width, colors))
    label = fold_label(change, expanded=expanded)
    if label:
        out.append(label + "\n", style=colors.fold)
    return out


def _paint_line(line: DiffLine, width: int, colors: RichPalette) -> Text:
    gutter = f"{line.number:>4} "
    room = max(8, width - len(gutter))
    body = line.text.replace("\t", "    ")[:room].ljust(room)
    row = gutter + body + "\n"
    if line.kind == "+":
        return Text(row, style=colors.add)
    if line.kind == "-":
        return Text(row, style=colors.delete)
    painted = Text()
    painted.append(gutter, style=colors.number)
    painted.append(body + "\n", style=colors.context)
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
        colors = rich_palette()
        self._header = Static(render_error_header(self.kind, colors), classes="error-header")
        self._message = Static(
            Text(self.message, style=colors.error_msg), classes="error-message"
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
        colors = rich_palette(theme_of(self))
        self._header.update(render_error_header(self.kind, colors))
        self._message.update(Text(self.message, style=colors.error_msg))
        can_open = self.expandable
        self._body.display = self.expanded and can_open
        self._fold.display = can_open
        if can_open:
            self._fold.update(error_fold_label(self.detail, expanded=self.expanded))
        self.refresh(layout=True)


def render_error_header(kind: str, colors: RichPalette | None = None) -> Text:
    colors = colors or rich_palette()
    out = Text()
    out.append("◆ ", style=colors.head)
    out.append("Error  ", style=colors.head)
    if kind:
        out.append(kind, style=colors.error)
    return out


def error_fold_label(detail: str, *, expanded: bool) -> str:
    if expanded:
        return "▲  See Less · -> Press C to copy"
    lines = detail.count("\n") or 1
    return f"▶  See More {lines} Lines ·"


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
