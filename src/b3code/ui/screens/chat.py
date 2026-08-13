"""Tela única: welcome (vazio) + scroll de chat + prompt + autocomplete."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Input, Static

from b3code.commands.apply import Decision, decide_submit
from b3code.commands.types import Suggestion
from b3code.container import AppContainer
from b3code.services.chat import ChatEvent
from b3code.services.session import DisplayTurn
from b3code.ui.coalesce import FLUSH_INTERVAL
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.messages import (
    AssistantMessage,
    DiffBlock,
    RoleLabel,
    SystemNote,
    ToolRow,
    UserMessage,
)
from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.planbar import PlanBar
from b3code.ui.widgets.spinner import Spinner
from b3code.utils.prompt import current_token, expand_attachments


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
        self.awaiting_plan = False
        self._thinking: Spinner | None = None
        self._flush_timer: Timer | None = None
        self._pending_text: list[str] = []
        self._pending_text_lock = threading.Lock()
        self._text_flush_scheduled = False
        self._ac_query: str | None = None

    def compose(self) -> ComposeResult:
        cwd = _short_cwd(self.c.cwd)
        with Horizontal(id="top-bar"):
            yield Static("▸", id="cwd-icon")
            yield Static(cwd, id="cwd")
            yield Static("◆", id="model-icon")
            yield Static(self.c.config.selected_model, id="model-label")
            yield Static("", id="mode-flag")
        with VerticalScroll(id="chat"):
            yield Welcome()
        yield Autocomplete()
        yield PermissionPicker(id="permission")
        yield PlanBar(id="plan-bar")
        with Horizontal(id="prompt-row"):
            yield Input(placeholder="send a message  (@ file  / command)", id="prompt")

    def on_mount(self) -> None:
        self.query_one(PermissionPicker).display = False
        self.query_one(PlanBar).display = False
        self._set_plan_badge()
        self.query_one("#prompt", Input).focus()
        turns = self.c.session_store.display_turns()
        if turns:
            self._show_welcome(False)
            for turn in turns:
                self._mount_turn(turn)
        self._scan_files()

    @on(Input.Changed, "#prompt")
    def on_prompt_changed(self, event: Input.Changed) -> None:
        self._refresh_autocomplete(event.value, event.input.cursor_position)

    @on(Input.Submitted, "#prompt")
    def on_prompt_submitted(self, event: Input.Submitted) -> None:
        if self.awaiting_permission:
            self.confirm_permission()
            return
        if self.awaiting_plan:
            self.confirm_plan()
            return
        ac = self.query_one(Autocomplete)
        suggestion = ac.current() if ac.display else None
        decision = decide_submit(event.value, event.input.cursor_position, suggestion)
        self._fulfill(decision, event.input, ac, execute=True)

    def on_key(self, event: Key) -> None:
        if self.awaiting_plan:
            bar = self.query_one(PlanBar)
            if event.key in {"a", "s", "q"}:
                self.confirm_plan({"a": "approve", "s": "revise", "q": "quit"}[event.key])
                event.stop()
                event.prevent_default()
                return
            delta = {"down": 1, "up": -1}.get(event.key)
            if delta is not None:
                bar.move(delta)
                event.stop()
                event.prevent_default()
                return
            if event.key == "enter":
                self.confirm_plan()
                event.stop()
                event.prevent_default()
                return
            return
        if self.awaiting_permission:
            picker = self.query_one(PermissionPicker)
            delta = {"down": 1, "up": -1}.get(event.key)
            if delta is not None:
                picker.move(delta)
                event.stop()
                event.prevent_default()
                return
            if event.key == "enter":
                self.confirm_permission()
                event.stop()
                event.prevent_default()
                return
            return
        ac = self.query_one(Autocomplete)
        if not ac.display:
            return
        if event.key == "down":
            ac.action_cursor_down()
            event.stop()
            return
        if event.key == "up":
            ac.action_cursor_up()
            event.stop()
            return
        if event.key != "tab":
            return
        item = ac.current()
        if item is None:
            return
        inp = self.query_one("#prompt", Input)
        decision = decide_submit(inp.value, inp.cursor_position, item)
        self._fulfill(decision, inp, ac, execute=False)
        event.stop()
        event.prevent_default()

    def _stop_thinking(self) -> None:
        if self._thinking is not None:
            self._thinking.remove()
            self._thinking = None

    def confirm_permission(self) -> None:
        picker = self.query_one(PermissionPicker)
        choice = picker.current()
        self.awaiting_permission = False
        picker.hide()
        self.c.chat.answer_permission(choice)

    def confirm_plan(self, choice: str | None = None) -> None:
        bar = self.query_one(PlanBar)
        pick = choice or bar.current()
        self.awaiting_plan = False
        bar.hide()
        if pick == "approve":
            prompt = self.c.chat.approve_plan()
            self._set_plan_badge()
            self._send_chat(prompt)
            return
        if pick == "quit":
            self.c.chat.exit_plan()
            self._set_plan_badge()
            self._show_welcome(False)
            self.query_one("#chat").mount(SystemNote("plan mode off"))
            self._scroll_end()
            return
        self.query_one("#prompt", Input).focus()

    def _set_plan_badge(self) -> None:
        flag = self.query_one("#mode-flag", Static)
        if self.c.chat.plan.active:
            flag.update("plan")
            flag.display = True
        else:
            flag.update("")
            flag.display = False

    def action_escape(self) -> None:
        if self.awaiting_plan:
            self.confirm_plan("quit")
            return
        if self.awaiting_permission:
            self.awaiting_permission = False
            self.query_one(PermissionPicker).hide()
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
        name = (line[1:].split() or [""])[0]
        if name in {"new", "resume", "plan"} and self.c.chat.busy:
            self._show_welcome(False)
            self.query_one("#chat").mount(
                SystemNote("busy — press esc to cancel first")
            )
            self._scroll_end()
            return
        result = self.c.commands.execute(line)
        if result.action == "quit":
            self.app.exit()
            return
        if result.action == "new":
            self._reset_chat()
        if result.action == "refresh":
            self._rebuild()
            self.query_one("#model-label", Static).update(self.c.config.selected_model)
        if result.action == "plan":
            self._set_plan_badge()
            if result.payload:
                self._send_chat(result.payload)
                return
        if result.action == "plan_off":
            self._set_plan_badge()
            self.awaiting_plan = False
            self.query_one(PlanBar).hide()
        if result.action == "view_plan":
            self._show_welcome(False)
            chat = self.query_one("#chat")
            chat.mount(RoleLabel("plan"))
            chat.mount(AssistantMessage(result.message))
            self._scroll_end()
            return
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
        self._stop_thinking()
        self._thinking = Spinner("thinking")
        chat.mount(self._thinking)
        self._scroll_end()
        self._run_agent(typed)

    @work(exclusive=True, group="files-scan")
    async def _scan_files(self) -> None:
        await self.c.file_index.ensure_scanned()
        self._after_scan()

    def _after_scan(self) -> None:
        inp = self.query_one("#prompt", Input)
        self._refresh_autocomplete(inp.value, inp.cursor_position)

    @work(exclusive=False)
    async def _run_agent(self, typed: str) -> None:
        # anexos e enqueue no worker: o submit da UI não lê disco
        prompt = await asyncio.to_thread(
            expand_attachments, typed, self.c.cwd, self.c.file_index.read
        )
        await self.c.chat.enqueue(prompt, self._on_event)

    def _on_event(self, event: ChatEvent) -> None:
        # O handler do agent pode disparar fora de um callback Textual.
        if event.kind == "text_delta":
            self._queue_text(event.text)
            return
        self.call_later(self._apply_event, event)

    def _queue_text(self, text: str) -> None:
        with self._pending_text_lock:
            self._pending_text.append(text)
            if self._text_flush_scheduled:
                return
            self._text_flush_scheduled = True
        self.call_later(self._schedule_text_flush)

    def _schedule_text_flush(self) -> None:
        if self._flush_timer is None:
            self._flush_timer = self.set_timer(FLUSH_INTERVAL, self._flush_text)

    def _flush_text(self) -> None:
        self._flush_timer = None
        with self._pending_text_lock:
            text = "".join(self._pending_text)
            self._pending_text.clear()
            self._text_flush_scheduled = False
        if not text:
            return
        self._buffer += text
        if self._assistant is not None:
            self._assistant.update(self._buffer)
        self._stop_thinking()
        self._scroll_end()

    def _apply_event(self, event: ChatEvent) -> None:
        if event.kind == "text_delta":
            self._queue_text(event.text)
            return
        self._flush_text()
        chat = self.query_one("#chat")
        if event.kind == "tool_start":
            self._upsert_tool(chat, event, "running")
            self._scroll_end()
            return
        if event.kind == "tool_end":
            self._upsert_tool(chat, event, "done")
            self._scroll_end()
            return
        if event.kind == "diff":
            if event.change is not None:
                block = DiffBlock(event.change)
                if self._assistant is None:
                    chat.mount(block)
                else:
                    chat.mount(block, before=self._assistant)
            self._scroll_end()
            return
        if event.kind == "plan_ready":
            self.awaiting_plan = True
            self.query_one(Autocomplete).set_suggestions([])
            self.query_one(PlanBar).show(event.text, self.c.config.accent)
            self._scroll_end()
            return
        if event.kind == "permission":
            self.awaiting_permission = True
            self.query_one(Autocomplete).set_suggestions([])
            self.query_one(PermissionPicker).show(
                event.text, event.detail, self.c.config.accent
            )
            self._scroll_end()
            return
        if event.kind == "error":
            self._stop_thinking()
            chat.mount(SystemNote(event.text))
            if self._assistant is not None and not self._buffer:
                self._assistant.update("_(cancelled or failed)_")
            self._scroll_end()
            return
        if event.kind == "done":
            self._stop_thinking()
            if self._assistant is not None and event.text and not self._buffer:
                self._assistant.update(event.text)
        self._scroll_end()

    def _upsert_tool(self, chat, event: ChatEvent, status: str) -> None:
        row = self._tools.get(event.tool)
        if row is not None:
            row.set_status(status, event.detail)
            return
        row = ToolRow(event.tool, event.detail, status=status)
        self._tools[event.tool] = row
        if self._assistant is None:
            chat.mount(row)
            return
        chat.mount(row, before=self._assistant)

    def _refresh_autocomplete(self, value: str, cursor: int) -> None:
        _, _, token = current_token(value, cursor)
        ac = self.query_one(Autocomplete)
        # `/` vale para a linha inteira (subcomandos depois do espaço).
        if value.startswith("/"):
            self._ac_query = None
            ac.set_suggestions(self.c.commands.complete(value[:cursor] or "/"))
            return
        if token.startswith("@"):
            query = token[1:]
            self._ac_query = query
            self._search_files(query)
            return
        self._ac_query = None
        ac.set_suggestions([])

    @work(exclusive=True, group="files-search")
    async def _search_files(self, query: str) -> None:
        await asyncio.sleep(0.05)
        if query != self._ac_query:
            return
        hits = await asyncio.to_thread(self.c.file_index.search, query)
        if query != self._ac_query:
            return
        self.call_later(self._show_file_hits, query, hits)

    def _show_file_hits(self, query: str, hits: list[Path]) -> None:
        if query != self._ac_query:
            return
        self.query_one(Autocomplete).set_suggestions(
            [
                Suggestion(value=str(p), label=str(p), hint="file", kind="file")
                for p in hits
            ]
        )

    def _fulfill(
        self,
        decision: Decision,
        inp: Input,
        ac: Autocomplete,
        *,
        execute: bool,
    ) -> None:
        if decision.kind == "apply":
            inp.value = decision.line
            inp.cursor_position = decision.cursor
            consume = bool(decision.suggestion and decision.suggestion.consume)
            if execute and consume:
                ac.set_suggestions([])
                inp.clear()
                self._run_command(decision.line.strip())
                return
            self._refresh_autocomplete(decision.line, decision.cursor)
            return
        if not execute or decision.kind == "empty":
            return
        inp.clear()
        ac.set_suggestions([])
        if decision.kind == "execute":
            self._run_command(decision.line)
            return
        if decision.kind == "chat":
            self._send_chat(decision.line)

    def _mount_turn(self, turn: DisplayTurn) -> None:
        chat = self.query_one("#chat")
        if turn.role == "user":
            chat.mount(RoleLabel("you"))
            chat.mount(UserMessage(turn.text))
            return
        if turn.role == "assistant":
            chat.mount(RoleLabel("assistant"))
            chat.mount(AssistantMessage(turn.text))
            return
        if turn.role == "tool":
            chat.mount(ToolRow(turn.tool, turn.detail, status="done"))

    def _reset_chat(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        chat.mount(Welcome())
        self._show_welcome(True)
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None
        with self._pending_text_lock:
            self._pending_text.clear()
            self._text_flush_scheduled = False
        self._assistant = None
        self._buffer = ""
        self._tools = {}
        self.awaiting_permission = False
        self.awaiting_plan = False
        self._thinking = None
        self.query_one(PermissionPicker).hide()
        self.query_one(PlanBar).hide()

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
            "New session      ctrl+n\nResume session   ctrl+s\nQuit             ctrl+d",
            id="welcome-menu",
        )


def _short_cwd(cwd: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(cwd.relative_to(home))
    except ValueError:
        return str(cwd)
