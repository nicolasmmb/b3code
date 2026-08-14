"""Controller do scroll de chat. Sem bindings de teclado."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from b3code.services.chat import ChatEvent
from b3code.services.session import DisplayTurn
from b3code.ui.widgets.messages import (
    AssistantMessage,
    DiffBlock,
    ErrorBlock,
    PlanDoc,
    RoleLabel,
    SystemNote,
    ToolRow,
    UserMessage,
)
from b3code.ui.widgets.spinner import Spinner
from b3code.utils.diffview import FileChange


def visible_turns(
    turns: list[DisplayTurn], window: int = 100
) -> tuple[int, list[DisplayTurn]]:
    if len(turns) <= window:
        return 0, list(turns)
    return len(turns) - window, list(turns[-window:])


class Welcome(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("b3code  0.1.0", id="welcome-title")
        yield Static("minimal coding TUI", id="welcome-hint")
        yield Static(
            "New session      ctrl+n\nResume session   ctrl+s\nQuit             ctrl+d",
            id="welcome-menu",
        )


class ChatView:
    def __init__(self, plan_active: Callable[[], bool]) -> None:
        self._scroll: VerticalScroll | None = None
        self._assistant: AssistantMessage | None = None
        self._buffer = ""
        self._tools: dict[str, ToolRow] = {}
        self._thinking: Spinner | None = None
        self._plan_doc: PlanDoc | None = None
        self._plan_active = plan_active
        self._plan_ready_hook: Callable[[ChatEvent], None] | None = None
        self._permission_hook: Callable[[ChatEvent], None] | None = None

    @property
    def thinking(self) -> Spinner | None:
        return self._thinking

    @property
    def scroll(self) -> VerticalScroll:
        assert self._scroll is not None
        return self._scroll

    def bind(self, scroll: VerticalScroll) -> None:
        self._scroll = scroll

    def show_welcome(self) -> None:
        for welcome in self.scroll.query(Welcome):
            welcome.display = True

    def hide_welcome(self) -> None:
        for welcome in self.scroll.query(Welcome):
            welcome.display = False

    def clear(self) -> None:
        self.scroll.remove_children()
        self.scroll.mount(Welcome())
        self.show_welcome()
        self._assistant = None
        self._buffer = ""
        self._tools = {}
        self._plan_doc = None
        self._thinking = None

    def rebuild(self, turns: Iterable[DisplayTurn], *, window: int = 100) -> None:
        self.scroll.remove_children()
        turns = list(turns)
        if not turns:
            self.scroll.mount(Welcome())
            self.show_welcome()
            return
        self.hide_welcome()
        hidden, shown = visible_turns(turns, window)
        if hidden:
            self.scroll.mount(SystemNote(f"… {hidden} earlier turns"))
        for turn in shown:
            self.mount_turn(turn)
        self.scroll_end()

    def mount_turn(self, turn: DisplayTurn) -> None:
        if turn.role == "user":
            self.mount_user(turn.text)
            return
        if turn.role == "assistant":
            self.scroll.mount(RoleLabel("assistant"))
            self.scroll.mount(AssistantMessage(turn.text))
            return
        if turn.role == "tool":
            self.scroll.mount(
                ToolRow(turn.tool, turn.detail, status="done", output=turn.output)
            )

    def mount_user(self, text: str) -> None:
        self.hide_welcome()
        self.scroll.mount(RoleLabel("you"))
        self.scroll.mount(UserMessage(text))

    def start_assistant(self) -> None:
        self._tools = {}
        self._buffer = ""
        self._assistant = AssistantMessage("")
        self.scroll.mount(RoleLabel("assistant"))
        self.scroll.mount(self._assistant)

    def append_assistant(self, text: str) -> None:
        self._buffer += text
        if self._assistant is not None:
            self._assistant.update(self._buffer)

    def finish_assistant(self, text: str) -> None:
        if self._assistant is not None and text and not self._buffer:
            self._assistant.update(text)

    def fail_assistant(self) -> None:
        if self._assistant is not None and not self._buffer:
            self._assistant.update("_(cancelled or failed)_")

    def mount_system(self, text: str) -> None:
        self.hide_welcome()
        self.scroll.mount(SystemNote(text))
        self.scroll_end()

    def mount_error(self, summary: str, detail: str = "") -> None:
        self.hide_welcome()
        self.discard_empty_assistant()
        self.scroll.mount(ErrorBlock(summary, detail))
        self.scroll_end()

    def discard_empty_assistant(self) -> None:
        if self._assistant is None or self._buffer:
            return
        kids = list(self.scroll.children)
        idx = kids.index(self._assistant) if self._assistant in kids else -1
        self._assistant.remove()
        self._assistant = None
        if idx > 0 and isinstance(kids[idx - 1], RoleLabel):
            kids[idx - 1].remove()

    def upsert_tool(self, event: ChatEvent, status: str) -> None:
        key = event.call_id or event.tool
        row = self._tools.get(key)
        if row is not None:
            row.set_status(
                status,
                detail=event.detail or None,
                output=event.output if event.output or status != "running" else None,
            )
            return
        row = ToolRow(event.tool, event.detail, status=status, output=event.output)
        self._tools[key] = row
        if self._assistant is None:
            self.scroll.mount(row)
            return
        self.scroll.mount(row, before=self._assistant)

    def mount_diff(self, change: FileChange) -> None:
        block = DiffBlock(change)
        if self._assistant is None:
            self.scroll.mount(block)
            return
        self.scroll.mount(block, before=self._assistant)

    def show_plan_doc(self, markdown: str) -> None:
        self.hide_welcome()
        if self._plan_doc is not None:
            self._plan_doc.update(markdown)
            self.scroll_end()
            return
        self.scroll.mount(RoleLabel("plan"))
        self._plan_doc = PlanDoc(markdown)
        self.scroll.mount(self._plan_doc)
        self.scroll_end()

    def ensure_thinking(self, label: str | None = None) -> None:
        name = label or ("planning" if self._plan_active() else "thinking")
        kids = list(self.scroll.children)
        at_end = bool(
            self._thinking is not None and kids and kids[-1] is self._thinking
        )
        if self._thinking is not None and at_end:
            if self._thinking._label != name:
                self._thinking.set_label(name)
            return
        self.stop_thinking()
        self._thinking = Spinner(name)
        self.scroll.mount(self._thinking)

    def stop_thinking(self) -> None:
        if self._thinking is None:
            return
        self._thinking.remove()
        self._thinking = None

    def scroll_end(self) -> None:
        self.scroll.scroll_end(animate=False)

    def apply_event(
        self,
        event: ChatEvent,
        *,
        on_plan_ready: Callable[[ChatEvent], None] | None = None,
        on_permission: Callable[[ChatEvent], None] | None = None,
    ) -> None:
        self._plan_ready_hook = on_plan_ready
        self._permission_hook = on_permission
        handlers = {
            "tool_start": self._event_tool_start,
            "tool_end": self._event_tool_end,
            "diff": self._event_diff,
            "plan_draft": self._event_plan_draft,
            "plan_ready": self._event_plan_ready,
            "permission": self._event_permission,
            "error": self._event_error,
            "done": self._event_done,
        }
        handler = handlers.get(event.kind)
        if handler is None:
            self.scroll_end()
            return
        handler(event)

    def _event_tool_start(self, event: ChatEvent) -> None:
        self.ensure_thinking()
        self.upsert_tool(event, "running")
        self.scroll_end()

    def _event_tool_end(self, event: ChatEvent) -> None:
        self.ensure_thinking()
        self.upsert_tool(event, "done")
        self.scroll_end()

    def _event_diff(self, event: ChatEvent) -> None:
        if event.change is not None:
            self.mount_diff(event.change)
        self.scroll_end()

    def _event_plan_draft(self, event: ChatEvent) -> None:
        self.ensure_thinking("planning")
        self.show_plan_doc(event.text)

    def _event_plan_ready(self, event: ChatEvent) -> None:
        self.stop_thinking()
        if event.text.strip():
            self.show_plan_doc(event.text)
        if self._plan_ready_hook is not None:
            self._plan_ready_hook(event)
        self.scroll_end()

    def _event_permission(self, event: ChatEvent) -> None:
        if self._permission_hook is not None:
            self._permission_hook(event)
        self.scroll_end()

    def _event_error(self, event: ChatEvent) -> None:
        self.stop_thinking()
        if event.text == "cancelled" and not event.detail:
            self.fail_assistant()
            self.mount_system(event.text)
        else:
            self.mount_error(event.text, event.detail)
        self.scroll_end()

    def _event_done(self, event: ChatEvent) -> None:
        self.stop_thinking()
        self.finish_assistant(event.text)
        self.scroll_end()
