"""Tela única: welcome (vazio) + scroll de chat + prompt + autocomplete."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Input, Static

from b3code.commands.registry import Suggestion
from b3code.container import AppContainer
from b3code.services.chat import ChatEvent
from b3code.services.session import DisplayTurn
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.messages import (
    AssistantMessage,
    RoleLabel,
    SystemNote,
    ToolRow,
    UserMessage,
)
from b3code.utils.prompt import apply_suggestion, current_token, expand_attachments


class ChatScreen(Screen):
    BINDINGS = [
        Binding("ctrl+n", "new_session", "New", show=False),
        Binding("ctrl+s", "resume", "Resume", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("escape", "escape", "Esc", show=False),
    ]

    def __init__(self, container: AppContainer) -> None:
        super().__init__()
        self.c = container
        self._assistant: AssistantMessage | None = None
        self._buffer = ""
        self._tools: dict[str, ToolRow] = {}
        self.awaiting_permission = False

    def compose(self) -> ComposeResult:
        cwd = _short_cwd(self.c.cwd)
        yield Static(cwd, id="cwd")
        with VerticalScroll(id="chat"):
            yield Welcome()
        yield Autocomplete()
        with Horizontal(id="prompt-row"):
            yield Input(placeholder="send a message  (@ file  / command)", id="prompt")
            yield Static(self.c.config.selected_model, id="model-label")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        turns = self.c.session_store.display_turns()
        if turns:
            self._show_welcome(False)
            for turn in turns:
                self._mount_turn(turn)

    @on(Input.Changed, "#prompt")
    def on_prompt_changed(self, event: Input.Changed) -> None:
        self._refresh_autocomplete(event.value, event.input.cursor_position)

    @on(Input.Submitted, "#prompt")
    def on_prompt_submitted(self, event: Input.Submitted) -> None:
        ac = self.query_one(Autocomplete)
        if ac.display and ac.current() is not None:
            self._apply(ac.current())
            return
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        ac.set_suggestions([])
        if text.startswith("/"):
            self._run_command(text)
            return
        self._send_chat(text)

    def on_key(self, event: Key) -> None:
        if self.awaiting_permission and event.key in {"y", "a", "n"}:
            choice = {"y": "once", "a": "always", "n": "deny"}[event.key]
            self.awaiting_permission = False
            self.c.chat.answer_permission(choice)
            event.stop()
            event.prevent_default()
            return
        ac = self.query_one(Autocomplete)
        if not ac.display:
            return
        if event.key == "down":
            ac.action_cursor_down()
            event.stop()
        elif event.key == "up":
            ac.action_cursor_up()
            event.stop()
        elif event.key == "tab":
            if ac.current() is not None:
                self._apply(ac.current())
                event.stop()
                event.prevent_default()

    def action_escape(self) -> None:
        if self.awaiting_permission:
            self.awaiting_permission = False
            self.c.chat.answer_permission("deny")
            return
        ac = self.query_one(Autocomplete)
        if ac.display:
            ac.set_suggestions([])
            return
        if self.c.chat.busy:
            self.c.chat.cancel_current()

    def action_new_session(self) -> None:
        self._run_command("/new")

    def action_resume(self) -> None:
        self._run_command("/resume")

    def action_quit(self) -> None:
        self.app.exit()

    def _run_command(self, line: str) -> None:
        result = self.c.commands.execute(line)
        if result.action == "quit":
            self.app.exit()
            return
        if result.action == "new":
            self._reset_chat()
        if result.action == "refresh":
            self._rebuild()
            self.query_one("#model-label", Static).update(self.c.config.selected_model)
        if result.message:
            self._show_welcome(False)
            self.query_one("#chat").mount(SystemNote(result.message))
            self._scroll_end()

    def _send_chat(self, typed: str) -> None:
        self._show_welcome(False)
        chat = self.query_one("#chat")
        chat.mount(RoleLabel("you"))
        chat.mount(UserMessage(typed))
        self._tools = {}
        self._buffer = ""
        self._assistant = AssistantMessage("")
        chat.mount(RoleLabel("assistant"))
        chat.mount(self._assistant)
        self._scroll_end()
        prompt = expand_attachments(typed, self.c.cwd, self.c.file_index.read)
        self._run_agent(prompt)

    @work(exclusive=False)
    async def _run_agent(self, prompt: str) -> None:
        # enqueue serializa: se já houver um run, esta msg espera na fila
        await self.c.chat.enqueue(prompt, self._on_event)

    def _on_event(self, event: ChatEvent) -> None:
        # O handler do agent pode disparar fora de um callback Textual.
        self.call_later(self._apply_event, event)

    def _apply_event(self, event: ChatEvent) -> None:
        chat = self.query_one("#chat")
        if event.kind == "text_delta":
            self._buffer += event.text
            if self._assistant is not None:
                self._assistant.update(self._buffer)
        elif event.kind == "tool_start":
            row = self._tools.get(event.tool)
            if row is None:
                row = ToolRow(event.tool, event.detail, status="running")
                self._tools[event.tool] = row
                if self._assistant is not None:
                    chat.mount(row, before=self._assistant)
                else:
                    chat.mount(row)
            else:
                row.set_status("running", event.detail)
        elif event.kind == "tool_end":
            row = self._tools.get(event.tool)
            if row is None:
                row = ToolRow(event.tool, event.detail, status="done")
                self._tools[event.tool] = row
                if self._assistant is not None:
                    chat.mount(row, before=self._assistant)
                else:
                    chat.mount(row)
            else:
                row.set_status("done", event.detail)
        elif event.kind == "permission":
            self.awaiting_permission = True
            chat.mount(
                SystemNote(
                    f"? run_command\n  {event.text}\n  outside: {event.detail}\n"
                    "[y] once   [a] always   [n] deny"
                )
            )
        elif event.kind == "error":
            chat.mount(SystemNote(event.text))
            if self._assistant is not None and not self._buffer:
                self._assistant.update("_(cancelled or failed)_")
        elif event.kind == "done":
            if self._assistant is not None and event.text and not self._buffer:
                self._assistant.update(event.text)
        self._scroll_end()

    def _refresh_autocomplete(self, value: str, cursor: int) -> None:
        _, _, token = current_token(value, cursor)
        ac = self.query_one(Autocomplete)
        # `/` vale para a linha inteira (subcomandos depois do espaço).
        if value.startswith("/"):
            ac.set_suggestions(self.c.commands.complete(value[:cursor] or "/"))
            return
        if token.startswith("@"):
            query = token[1:]
            hits = self.c.file_index.search(query)
            ac.set_suggestions(
                [
                    Suggestion(value=str(p), label=str(p), hint="file", kind="file")
                    for p in hits
                ]
            )
            return
        ac.set_suggestions([])

    def _apply(self, item: Suggestion) -> None:
        inp = self.query_one("#prompt", Input)
        new, cursor = apply_suggestion(inp.value, inp.cursor_position, item.value, item.kind)
        inp.value = new
        inp.cursor_position = cursor
        self.query_one(Autocomplete).set_suggestions([])
        self._refresh_autocomplete(new, cursor)

    def _mount_turn(self, turn: DisplayTurn) -> None:
        chat = self.query_one("#chat")
        if turn.role == "user":
            chat.mount(RoleLabel("you"))
            chat.mount(UserMessage(turn.text))
        elif turn.role == "assistant":
            chat.mount(RoleLabel("assistant"))
            chat.mount(AssistantMessage(turn.text))
        elif turn.role == "tool":
            chat.mount(ToolRow(turn.tool, turn.detail, status="done"))

    def _reset_chat(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        chat.mount(Welcome())
        self._show_welcome(True)
        self._assistant = None
        self._buffer = ""
        self._tools = {}
        self.awaiting_permission = False

    def _rebuild(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        turns = self.c.session_store.display_turns()
        if not turns:
            chat.mount(Welcome())
            self._show_welcome(True)
            return
        self._show_welcome(False)
        for turn in turns:
            self._mount_turn(turn)
        self._scroll_end()

    def _show_welcome(self, show: bool) -> None:
        for welcome in self.query(Welcome):
            welcome.display = show

    def _scroll_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)


class Welcome(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("b3code  0.1.0", id="welcome-title")
        yield Static("minimal coding TUI", id="welcome-hint")
        yield Static(
            "New session      ctrl+n\n"
            "Resume session   ctrl+s\n"
            "Quit             ctrl+d",
            id="welcome-menu",
        )


def _short_cwd(cwd: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(cwd.relative_to(home))
    except ValueError:
        return str(cwd)
