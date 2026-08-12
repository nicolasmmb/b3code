"""Blocos do chat: user, assistant (markdown), tool, nota de sistema."""

from textual.widgets import Markdown, Static


class UserMessage(Markdown):
    """Prompt do user. Markdown para `**bold**` / code, igual o assistant."""


class AssistantMessage(Markdown):
    """Resposta da LLM. `update()` a cada delta do stream."""


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
