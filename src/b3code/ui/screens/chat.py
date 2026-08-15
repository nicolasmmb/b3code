"""Tela única: wiring de chat, prompt, plano e permissão."""

from __future__ import annotations

import asyncio

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Key, Paste
from textual.screen import Screen
from textual.widgets import Input, OptionList

from b3code.ui.chat_view import ChatView, Welcome
from b3code.ui.coalesce import FLUSH_INTERVAL
from b3code.ui.deps import ScreenDeps
from b3code.ui.effects import CommandHooks, dispatch_command
from b3code.ui.index_controller import IndexController
from b3code.ui.permission_controller import PermissionController
from b3code.ui.plan_controller import PlanController
from b3code.ui.prompt_bar import PromptBar, PromptInput
from b3code.ui.question_controller import QuestionController
from b3code.ui.stream import FlushScheduler, TextBuffer
from b3code.ui.stream_host import ChatStreamMixin
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.planbar import PlanBar
from b3code.ui.widgets.question import QuestionBar
from b3code.ui.widgets.topbar import TopBar
from b3code.utils.attachments import Attachment
from b3code.utils.prompt import build_user_content


class ChatScreen(ChatStreamMixin, Screen):
    BINDINGS = [
        Binding("ctrl+n", "new_session", "New", show=False),
        Binding("ctrl+s", "resume", "Resume", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("escape", "escape", "Esc", show=False, priority=True),
        Binding("a", "plan_approve", "Approve", show=False, priority=True),
        Binding("s", "plan_revise", "Revise", show=False, priority=True),
        Binding("q", "plan_quit", "Quit plan", show=False, priority=True),
    ]

    def __init__(self, deps: ScreenDeps) -> None:
        super().__init__()
        self.deps = deps
        self.chat_view = ChatView(lambda: self.deps.chat.plan.active)
        self.text_buffer = TextBuffer()
        self._flush: FlushScheduler | None = None
        self.plan_controller: PlanController | None = None
        self.permission_controller: PermissionController | None = None
        self.question_controller: QuestionController | None = None
        self.index_controller: IndexController | None = None
        self._pending_task: dict = {}

    @property
    def awaiting_plan(self) -> bool:
        return bool(self.plan_controller and self.plan_controller.awaiting)

    @awaiting_plan.setter
    def awaiting_plan(self, value: bool) -> None:
        if self.plan_controller is not None:
            self.plan_controller.awaiting = value

    @property
    def awaiting_permission(self) -> bool:
        return bool(self.permission_controller and self.permission_controller.awaiting)

    @awaiting_permission.setter
    def awaiting_permission(self, value: bool) -> None:
        if self.permission_controller is not None:
            self.permission_controller.awaiting = value

    def compose(self) -> ComposeResult:
        yield TopBar(self.deps.cwd, self.deps.config.selected_model)
        with VerticalScroll(id="chat"):
            yield Welcome()
        yield PermissionPicker(id="permission")
        yield QuestionBar(id="question")
        yield PlanBar(id="plan-bar")
        yield PromptBar(
            self.deps.commands,
            self.deps.files,
            self.deps.config,
            on_command=self._run_command,
            on_chat=self._send_chat,
            id="prompt-bar",
        )

    def on_mount(self) -> None:
        scroll = self.query_one("#chat", VerticalScroll)
        self.chat_view.bind(scroll)
        picker = self.query_one(PermissionPicker)
        bar = self.query_one(PlanBar)
        picker.display = False
        bar.display = False
        self.query_one(QuestionBar).display = False
        prompt_bar = self.query_one(PromptBar)
        self.plan_controller = PlanController(
            self.deps.chat,
            bar,
            scroll,
            self.deps.config.accent,
            on_send=self._send_chat,
            on_note=self.chat_view.mount_system,
            on_badge=self._set_plan_badge,
            on_lock=prompt_bar.disable_input,
            on_unlock=prompt_bar.enable_input,
        )
        self.permission_controller = PermissionController(
            self.deps.chat, picker, self.deps.config.accent
        )
        self.question_controller = QuestionController(
            self.deps.chat, self.query_one(QuestionBar), self.deps.config.accent
        )
        self.index_controller = IndexController(
            self.deps.files,
            on_listed=prompt_bar.refresh_suggestions,
            on_refresh=prompt_bar.refresh_index,
        )
        self._flush = FlushScheduler(
            self.call_later, self.set_timer, FLUSH_INTERVAL, self._flush_text
        )
        self._set_plan_badge()
        prompt_bar.focus_input()
        turns = self.deps.sessions.display_turns()
        if turns:
            self.chat_view.rebuild(turns)
        prompt_bar.refresh_index()

    def _set_plan_badge(self) -> None:
        self.query_one(TopBar).set_plan_badge(self.deps.chat.plan.active)

    @on(PromptInput.Submitted, "#prompt")
    def on_prompt_submitted(self, event: PromptInput.Submitted) -> None:
        if self.awaiting_permission:
            self.confirm_permission()
            event.stop()
            return
        if self.awaiting_plan:
            self.confirm_plan()
            event.stop()

    @on(Input.Submitted, "#question-other")
    def on_other_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.question_controller:
            self.question_controller.submit_other()

    def on_paste(self, event: Paste) -> None:
        """Drop do Finder cai no widget sob o cursor, quase sempre o chat."""
        if self.query_one(QuestionBar).other_visible():
            return
        text = event.text.replace("\r\n", "\n").replace("\r", "\n")
        bar = self.query_one(PromptBar)
        if not bar.handle_paste(text, allow_clipboard=False):
            return
        event.stop()
        event.prevent_default()
        bar.focus_input()

    def on_key(self, event: Key) -> None:
        if self.plan_controller and self.plan_controller.consume_key(event):
            return
        if self.permission_controller and self.permission_controller.consume_key(event):
            return
        if self.question_controller and self.question_controller.consume_key(event):
            return
        self.query_one(PromptBar).consume_key(event)

    @on(OptionList.OptionSelected, "#plan-options")
    def on_plan_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.awaiting_plan:
            return
        event.stop()
        self.confirm_plan()

    def confirm_permission(self) -> None:
        if self.permission_controller:
            self.permission_controller.confirm()

    def confirm_plan(self, choice: str | None = None) -> None:
        if self.plan_controller:
            self.plan_controller.confirm(choice)

    def action_plan_approve(self) -> None:
        if self.awaiting_plan:
            self.confirm_plan("approve")
            return
        self._other_insert("a")

    def action_plan_revise(self) -> None:
        if self.awaiting_plan:
            self.confirm_plan("revise")
            return
        self._other_insert("s")

    def action_plan_quit(self) -> None:
        if self.awaiting_plan:
            self.confirm_plan("quit")
            return
        if self._other_insert("q"):
            return
        if self.deps.chat.busy and self.deps.chat.plan.active:
            self.deps.chat.cancel_current()
            return
        if self.deps.chat.plan.active:
            self._run_command("/plan off")

    def action_escape(self) -> None:
        if self.query_one(QuestionBar).other_visible() and self.question_controller:
            self.question_controller.leave_other()
            return
        if self.awaiting_plan:
            self.confirm_plan("quit")
            return
        if self.awaiting_permission and self.permission_controller:
            self.permission_controller.deny()
            return
        autocomplete = self.query_one(Autocomplete)
        if autocomplete.display:
            autocomplete.set_suggestions([])
            return
        if self.deps.chat.busy:
            self.deps.chat.cancel_current()
            return
        if self.deps.chat.plan.active:
            self._run_command("/plan off")

    def _other_insert(self, text: str) -> bool:
        bar = self.query_one(QuestionBar)
        if not bar.other_visible():
            return False
        bar.insert(text)
        return True

    def action_new_session(self) -> None:
        self._run_command("/new")

    def action_resume(self) -> None:
        self._run_command("/resume")

    def action_quit(self) -> None:
        self.app.exit()

    def _run_command(self, line: str) -> None:
        name = (line[1:].split() or [""])[0]
        if name in {"new", "resume", "plan"} and self.deps.chat.busy:
            self.chat_view.mount_system("busy — press esc to cancel first")
            return
        result = self.deps.commands.execute(line)
        self._set_plan_badge()
        dispatch_command(result, self._command_hooks())

    def _command_hooks(self) -> CommandHooks:
        return CommandHooks(
            on_quit=self.app.exit,
            on_reset=self._reset_chat,
            on_rebuild=self._rebuild_after_command,
            on_send=self._send_chat,
            on_plan_off=self._after_plan_off,
            on_show_plan=self.chat_view.show_plan_doc,
            on_note=self.chat_view.mount_system,
            on_doctor=self._start_doctor,
        )

    def _rebuild_after_command(self) -> None:
        app = self.app
        apply = getattr(app, "apply_theme", None)
        if callable(apply):
            apply()
        if self.plan_controller is not None:
            self.plan_controller.set_accent(self.deps.config.accent)
        if self.permission_controller is not None:
            self.permission_controller.set_accent(self.deps.config.accent)
        if self.question_controller is not None:
            self.question_controller.set_accent(self.deps.config.accent)
        self.chat_view.rebuild(self.deps.sessions.display_turns())
        self.query_one(TopBar).set_model(self.deps.config.selected_model)

    def _after_plan_off(self) -> None:
        self._set_plan_badge()
        if self.plan_controller is not None:
            self.plan_controller.reset()

    def _send_chat(
        self,
        user_text: str,
        attachments: dict[str, Attachment] | None = None,
    ) -> None:
        self.chat_view.mount_user(user_text)
        self.chat_view.start_assistant()
        self.chat_view.stop_thinking()
        self.chat_view.ensure_thinking()
        self.chat_view.scroll_end()
        self.query_one(PromptBar).disable_input()
        if attachments is None:
            attachments = self.query_one(PromptBar).pop_attachments(user_text)
        self._enqueue_prompt(user_text, attachments)

    def _apply_event(self, event) -> None:
        super()._apply_event(event)
        if self.index_controller is not None:
            self.index_controller.on_event(event)
        if event.kind not in {"done", "error"}:
            return
        if self.awaiting_plan or self.awaiting_permission:
            return
        if self.question_controller and self.question_controller.awaiting:
            return
        self.query_one(PromptBar).enable_input()

    def _start_doctor(self, names: tuple[str, ...]) -> None:
        self.chat_view.mount_system("mcp doctor…")
        self._doctor_servers(names)

    @work(exclusive=True, group="mcp-doctor")
    async def _doctor_servers(self, names: tuple[str, ...]) -> None:
        parts: list[str] = []
        for name in names:
            parts.append(await self.deps.chat.mcp.doctor(name))
        self.call_later(self.chat_view.mount_system, "\n".join(parts))

    @work(exclusive=False)
    async def _enqueue_prompt(
        self, user_text: str, attachments: dict[str, Attachment]
    ) -> None:
        prompt = await asyncio.to_thread(
            build_user_content,
            user_text,
            self.deps.cwd,
            self.deps.files.read,
            attachments,
        )
        await self.deps.chat.enqueue(prompt, self._on_event)

    def _reset_chat(self) -> None:
        if self._flush is not None:
            self._flush.cancel()
        self.text_buffer.reset()
        self._pending_task = {}
        self.deps.chat.reset_side_state()
        self.chat_view.clear()
        if self.permission_controller is not None:
            self.permission_controller.reset()
        if self.plan_controller is not None:
            self.plan_controller.reset()
        if self.question_controller is not None:
            self.question_controller.reset()
