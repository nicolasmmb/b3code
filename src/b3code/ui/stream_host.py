"""Cola de stream na tela — porta `_apply_event` dos testes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from b3code.services.chat import ChatEvent
from b3code.ui.chat_view import ChatView
from b3code.ui.permission_controller import PermissionController
from b3code.ui.plan_controller import PlanController
from b3code.ui.question_controller import QuestionController
from b3code.ui.stream import FlushScheduler, TextBuffer
from b3code.ui.widgets.autocomplete import Autocomplete


class ChatStreamMixin:
    call_later: Callable[..., Any]
    query_one: Callable[..., Any]
    text_buffer: TextBuffer
    chat_view: ChatView
    _flush: FlushScheduler | None
    plan_controller: PlanController | None
    permission_controller: PermissionController | None
    question_controller: QuestionController | None
    _pending_task: dict[str, ChatEvent]

    def _on_event(self, event: ChatEvent) -> None:
        if event.kind == "text_delta":
            self._queue_text(event.text)
            return
        if event.kind == "task" and not event.output:
            self._pending_task[event.call_id] = event
            self._arm_flush()
            return
        self.call_later(self._apply_event, event)

    def _queue_text(self, text: str) -> None:
        if not self.text_buffer.push(text):
            return
        self._arm_flush()

    def _arm_flush(self) -> None:
        self.call_later(self._schedule_text_flush)

    def _schedule_text_flush(self) -> None:
        if self._flush is not None:
            self._flush.arm()

    def _flush_text(self) -> None:
        text = self.text_buffer.drain()
        if text:
            self.chat_view.append_assistant(text)
            self.chat_view.scroll_end()
        ticks = list(self._pending_task.values())
        self._pending_task.clear()
        for event in ticks:
            self.chat_view.apply_event(event)

    def _apply_event(self, event: ChatEvent) -> None:
        if event.kind == "text_delta":
            self._queue_text(event.text)
            return
        self._flush_text()
        self.chat_view.apply_event(
            event,
            on_plan_ready=self._on_plan_ready,
            on_permission=self._on_permission,
            on_question=self._on_question,
        )

    def _on_plan_ready(self, event: ChatEvent) -> None:
        self.query_one(Autocomplete).set_suggestions([])
        if self.plan_controller is not None:
            self.plan_controller.on_plan_ready(event.text)

    def _on_permission(self, event: ChatEvent) -> None:
        self.query_one(Autocomplete).set_suggestions([])
        if self.permission_controller is not None:
            self.permission_controller.show(event.text, event.detail)

    def _on_question(self, event: ChatEvent) -> None:
        self.query_one(Autocomplete).set_suggestions([])
        if self.question_controller is not None:
            self.question_controller.show(event.text)
