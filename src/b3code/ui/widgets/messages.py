"""Blocos do chat: user, assistant (markdown), tool, nota de sistema, diff."""

from rich.text import Text
from textual.widgets import Markdown, Static

from b3code.utils.diffview import DiffLine, FileChange

# Grok-like: fundo na linha inteira, sem prefixo +/- no código.
_ADD = "#b7d5b4 on #1c2b1e"
_DEL = "#e0a3a3 on #2e1a1a"
_NUM = "#6e6e6e"
_CTX = "#d4d4d4"
_HEAD = "#9a9a9a"
_FILE = "#c9a227"


class UserMessage(Markdown):
    """Prompt do user. Markdown para `**bold**` / code, igual o assistant."""


class AssistantMessage(Markdown):
    """Resposta da LLM. `update()` a cada delta do stream."""


class DiffBlock(Static):
    """Edit no estilo Grok: números + faixa vermelha/verde."""

    def __init__(self, change: FileChange) -> None:
        self.change = change
        super().__init__("")

    def render(self) -> Text:
        width = self.size.width if self.size.width > 0 else 80
        return render_diff(self.change, width)


def render_diff(change: FileChange, width: int = 80) -> Text:
    out = Text()
    out.append("◆ ", style=_HEAD)
    out.append("Edit  ", style=_HEAD)
    out.append(change.path, style=_FILE)
    out.append("\n")
    for line in change.lines:
        out.append_text(_paint_line(line, width))
    if change.truncated:
        out.append("  …\n", style=_NUM)
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
