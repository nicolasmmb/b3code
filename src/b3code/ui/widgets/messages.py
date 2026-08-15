"""Blocos do chat: user, assistant (markdown), tool, nota de sistema, diff."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
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


def fence_highlight_lang(lexer: str) -> str:
    # Unlabeled: don't guess. guess_lexer treats │├└ as Token.Error (red bar).
    word = lexer.split()[0] if lexer else ""
    return word or "text"


class FenceCopy(Static, can_focus=True):
    """Ícone ⧉ + rótulo [COPY] no canto do fence."""

    def __init__(self) -> None:
        super().__init__(Text("⧉ [COPY]"), classes="fence-copy")
        self.tooltip = "copy"

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
    """Fence com linguagem à esquerda e ⧉ [COPY] à direita."""

    @classmethod
    def highlight(
        cls, code: str, language: str, ansi: bool = False, dark: bool = False
    ) -> Content:
        return super().highlight(
            code, fence_highlight_lang(language), ansi=ansi, dark=dark
        )

    @property
    def allow_horizontal_scroll(self) -> bool:
        return False

    def compose(self) -> ComposeResult:
        colors = rich_palette(theme_of(self))
        with Horizontal(classes="fence-bar"):
            yield Static(
                Text.assemble(
                    ("◆ ", colors.head), (fence_lang(self.lexer), colors.head)
                ),
                classes="fence-lang",
            )
            yield FenceCopy()
        yield Label(self._highlighted_code, id="code-content")

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
        self._width = 0

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        if hidden_count(self.change, expanded=False) > 0:
            self._fold = DiffFold(fold_label(self.change, expanded=False))
            yield self._fold

    def on_mount(self) -> None:
        self._paint()

    def on_resize(self) -> None:
        if self._line_width() != self._width:
            self._paint()

    def toggle(self) -> None:
        if hidden_count(self.change, expanded=False) == 0:
            return
        self.expanded = not self.expanded
        self._paint()

    def _line_width(self) -> int:
        return self._body.size.width or self.content_size.width or 80

    def _paint(self) -> None:
        colors = rich_palette(theme_of(self))
        width = self._line_width()
        self._width = width
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
    text = line.text.replace("\t", "    ")
    chunks = [text[i : i + room] for i in range(0, len(text), room)] or [""]
    blank = " " * len(gutter)
    painted = Text()
    for i, chunk in enumerate(chunks):
        prefix = gutter if i == 0 else blank
        body = chunk.ljust(room)
        if line.kind == "+":
            painted.append(prefix + body + "\n", style=colors.add)
        elif line.kind == "-":
            painted.append(prefix + body + "\n", style=colors.delete)
        else:
            painted.append(prefix, style=colors.number if i == 0 else colors.context)
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
        self._header = Static(
            render_error_header(self.kind, colors), classes="error-header"
        )
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


def _handle_tool_keys(row: ToolRow, event: Key) -> bool:
    if event.key in {"enter", "space"}:
        if row.expandable:
            row.toggle()
        else:
            row.copy()
        return True
    if event.key in {"c", "y"}:
        row.copy()
        return True
    if event.key == "escape" and row.expanded:
        row.toggle()
        return True
    return False


class ToolFold(Static, can_focus=True):
    """Seta no mesmo idioma do ErrorFold / DiffFold."""

    def on_click(self, event: Click) -> None:
        block = self.parent
        if isinstance(block, ToolRow):
            block.toggle()
        event.stop()

    def on_key(self, event: Key) -> None:
        block = self.parent
        if not isinstance(block, ToolRow):
            return
        if not _handle_tool_keys(block, event):
            return
        event.stop()
        event.prevent_default()


class ToolRow(Vertical, can_focus=False):
    """Tool call no recorte do Grok: header humano, output atrás do fold."""

    def __init__(
        self,
        tool: str,
        detail: str = "",
        status: str = "running",
        output: str = "",
    ) -> None:
        super().__init__(classes=status)
        self.tool = tool
        self.detail = detail
        self.output = output
        self.status = status
        self.expanded = False
        if tool == "subagent":
            self.add_class("subagent")
        self._header = Static("", classes="tool-header")
        self._body = Static("", markup=False, classes="tool-body")
        self._fold = ToolFold("")

    @property
    def expandable(self) -> bool:
        return bool(self.output.strip())

    def compose(self) -> ComposeResult:
        yield self._header
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

    def set_status(
        self,
        status: str,
        detail: str | None = None,
        output: str | None = None,
    ) -> None:
        self.status = status
        if detail:
            self.detail = detail
        if output is not None:
            self.output = output
        self.set_classes(status)
        if self.tool == "subagent":
            self.add_class("subagent")
        self._paint()

    def toggle(self) -> None:
        if not self.expandable:
            return
        self.expanded = not self.expanded
        self._paint()

    def copy(self) -> None:
        payload = self.output or self.detail or self.tool
        if not payload.endswith("\n"):
            payload += "\n"
        self.app.copy_to_clipboard(payload)
        self.app.notify("copied")

    def _paint(self) -> None:
        colors = rich_palette(theme_of(self))
        header = render_tool_header(self.status, self.detail, self.tool, colors)
        self._header.update(header)
        if self.tool == "subagent":
            self._body.update(render_subagent_body(self.output, colors))
        else:
            self._body.update(Text(self.output, style=colors.muted))
        can_open = self.expandable
        self._body.display = self.expanded and can_open
        self._fold.display = can_open
        if can_open:
            self._fold.update(
                tool_fold_label(self.output, expanded=self.expanded, tool=self.tool)
            )
        self.refresh(layout=True)


def render_tool_header(
    status: str, title: str, tool: str, colors: RichPalette | None = None
) -> Text:
    colors = colors or rich_palette()
    if tool == "subagent":
        return _subagent_header(status, title, colors)
    label = title or f"Ran {tool}"
    out = Text()
    if status == "running":
        out.append("… ", style=colors.muted)
        out.append(_running_subject(label), style=colors.muted)
        return out
    if status == "error":
        out.append("✗ ", style=colors.error)
        out.append(label, style=colors.error_msg)
        return out
    out.append(label, style=colors.muted)
    return out


def _subagent_header(status: str, title: str, colors: RichPalette) -> Text:
    kind, desc, activity, elapsed = _split_subagent_title(title)
    mark = "…" if status == "running" else ("✗" if status == "error" else "✓")
    mark_style = colors.error if status == "error" else colors.muted
    label_style = colors.error_msg if status == "error" else colors.muted
    out = Text()
    out.append(f"{mark} ", style=mark_style)
    out.append(kind or "subagent", style=label_style)
    if desc:
        out.append(" · ", style=label_style)
        out.append(desc, style=label_style)
    if activity and status == "running":
        out.append(" · ", style=label_style)
        out.append(activity, style=colors.file)
    elif activity:
        out.append(" · ", style=label_style)
        out.append(activity, style=label_style)
    if elapsed:
        out.append(" · ", style=label_style)
        out.append(elapsed, style=label_style)
    return out


def _split_subagent_title(title: str) -> tuple[str, str, str, str]:
    parts = [part.strip() for part in (title or "").split(" · ") if part.strip()]
    elapsed = ""
    if parts and _looks_like_elapsed(parts[-1]):
        elapsed = parts.pop()
    kind = parts[0] if parts else ""
    desc = parts[1] if len(parts) > 1 else ""
    activity = " · ".join(parts[2:]) if len(parts) > 2 else ""
    return kind, desc, activity, elapsed


def _looks_like_elapsed(part: str) -> bool:
    return (
        bool(part) and part[-1] in {"s", "m", "h"} and any(ch.isdigit() for ch in part)
    )


def _running_subject(title: str) -> str:
    if title.startswith("$ "):
        return title[2:]
    verb, _, rest = title.partition(" ")
    return rest or title


def tool_fold_label(output: str, *, expanded: bool, tool: str = "") -> str:
    if expanded:
        return "▲  See Less · -> Press C to copy"
    if tool == "subagent":
        steps = subagent_step_count(output)
        if steps:
            noun = "step" if steps == 1 else "steps"
            return f"▶  {steps} {noun} ·"
        return "▶  See output ·"
    lines = output.count("\n") + (0 if output.endswith("\n") else 1)
    return f"▶  See More {max(lines, 1)} Lines ·"


def subagent_step_count(output: str) -> int:
    return sum(1 for line in output.splitlines() if line.startswith("· "))


def render_subagent_body(output: str, colors: RichPalette | None = None) -> Text:
    colors = colors or rich_palette()
    text = output.rstrip("\n")
    if "\n—\n" in text:
        diary, _, summary = text.partition("\n—\n")
    elif text.startswith("—\n"):
        diary, summary = "", text[2:]
    else:
        diary, summary = text, ""
        if diary and not any(line.startswith("· ") for line in diary.splitlines()):
            diary, summary = "", text
    out = Text()
    for line in diary.splitlines():
        step = line[2:] if line.startswith("· ") else line
        if not step.strip():
            continue
        out.append("  · ", style=colors.muted)
        out.append(step + "\n", style=colors.muted)
    if summary.strip():
        if out:
            out.append("\n")
        out.append(summary.strip() + "\n", style=colors.muted)
    return out


class SystemNote(Static):
    """Saída de comando `/` e cancel — não é mensagem da LLM."""


class RoleLabel(Static):
    def __init__(self, name: str) -> None:
        super().__init__(name, classes="role")
