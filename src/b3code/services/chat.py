"""Orquestra o agent: uma request por vez, histórico nativo, stream de eventos.

A UI só conhece `ChatEvent`. Nada de pydantic_ai atravessa essa fronteira.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CancellationToken
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.messages import UserContent
from pydantic_ai.models import Model

from b3code.config.credentials import missing_gateway_credentials
from b3code.config.schema import AppConfig
from b3code.services.agents import (
    CODER_INSTRUCTIONS,
    NO_USAGE_LIMITS,
    build_coder,
    build_planner_agent,
)
from b3code.services.events import (
    ChatEvent,
    ChatEventKind,
    OnEvent,
    diff_event,
    map_agent_event,
    permission_event,
    question_event,
    task_event,
)
from b3code.services.mcp import McpHub
from b3code.services.partial import PartialTurnRecorder
from b3code.services.permission import PermissionGate
from b3code.services.plan import PlanMode
from b3code.services.planner import slim_plan_note
from b3code.services.questions import QuestionGate
from b3code.services.session import SessionStore
from b3code.services.skills import SkillIndex
from b3code.services.subagents import child_runner
from b3code.services.tasks import TaskHub, TaskRecord
from b3code.utils.diffview import FileChange
from b3code.utils.errors import format_error

__all__ = [
    "ChatEvent",
    "ChatEventKind",
    "ChatService",
    "CODER_INSTRUCTIONS",
    "OnEvent",
]


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        session: SessionStore,
        cwd: Path,
        model: Model | None = None,
        gate: PermissionGate | None = None,
        questions: QuestionGate | None = None,
        skills: SkillIndex | None = None,
        tasks: TaskHub | None = None,
    ) -> None:
        self.config = config
        self.session = session
        self.cwd = cwd
        self.gate = gate
        self.skills = skills or SkillIndex(cwd)
        self.plan = PlanMode(cwd)
        self.questions = questions or QuestionGate()
        self.tasks = tasks or TaskHub(
            runner=child_runner(
                config=config,
                cwd=cwd,
                gate=gate,
                on_change=self._emit_change,
                model=model,
            )
        )
        self.tasks.on_event = self._emit_task
        # Testes injetam TestModel e pulam o Azure.
        self._injected_model = model
        self.mcp = McpHub(config, cwd=cwd)
        self._coder: Agent[None, str] | None = None
        self._planner: Agent[None, str] | None = None
        self._plan_history: list[Any] = []
        # Lock = fila FIFO. Dois enqueue() ao mesmo tempo: o segundo espera.
        self._lock = asyncio.Lock()
        self._cancel: CancellationToken | None = None
        self.busy = False
        self._on_event: OnEvent | None = None

    def reload(self, config: AppConfig) -> None:
        """Recria o agent no próximo run (ex.: /model). Histórico fica no store."""
        self.config = config
        self.mcp.reload(config)
        self._coder = None
        self._planner = None

    def enter_plan(self) -> None:
        self.plan.enter()
        self._planner = None

    def exit_plan(self) -> None:
        self.plan.exit()
        self._plan_history = []
        self._planner = None

    def approve_plan(self) -> str:
        self.exit_plan()
        return (
            "Read .b3code/plan.md inside run_code via read_file first. "
            "Implement every step with run_code file tools. "
            "Do not write project files via the shell. "
            "Do not skip Files, Reuse, or Verify."
        )

    def answer_permission(self, choice: str) -> None:
        if self.gate is not None:
            self.gate.answer(choice)

    def answer_question(self, text: str) -> None:
        self.questions.answer(text)

    def dismiss_question(self) -> None:
        self.questions.dismiss()

    def cancel_current(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
        self.questions.cancel_pending()
        self.tasks.cancel_all()

    def reset_side_state(self) -> None:
        self.questions.cancel_pending()
        self.tasks.cancel_all()

    async def enqueue(
        self, prompt: str | Sequence[UserContent], on_event: OnEvent
    ) -> None:
        """Única porta de entrada. O lock garante 1 `agent.run` por vez."""
        async with self._lock:
            self.busy = True
            try:
                await self._run_turn(prompt, on_event)
            finally:
                self.busy = False

    async def _run_turn(
        self, prompt: str | Sequence[UserContent], on_event: OnEvent
    ) -> None:
        problem = missing_gateway_credentials(self.config)
        if self._injected_model is None and problem:
            on_event(ChatEvent(kind="error", text=problem))
            return
        token = CancellationToken()
        self._cancel = token
        self._on_event = on_event
        self._bind_permission(on_event)
        try:
            await self._dispatch_turn(prompt, token, on_event)
        except RunCancelled:
            on_event(ChatEvent(kind="error", text="cancelled"))
        except Exception as exc:
            summary, detail = format_error(exc)
            on_event(ChatEvent(kind="error", text=summary, detail=detail))
        finally:
            self._unbind_turn()

    def _bind_permission(self, on_event: OnEvent) -> None:
        if self.gate is not None:
            self.gate.on_ask = lambda req: on_event(permission_event(req))
        self.questions.on_ask = lambda qs: on_event(question_event(qs))

    def _unbind_turn(self) -> None:
        self._cancel = None
        self._on_event = None
        if self.gate is not None:
            self.gate.on_ask = None
        self.questions.on_ask = None
        self.questions.cancel_pending()

    async def _dispatch_turn(
        self,
        prompt: str | Sequence[UserContent],
        token: CancellationToken,
        on_event: OnEvent,
    ) -> None:
        recorder = PartialTurnRecorder()

        async def handler(_ctx: Any, events: Any) -> None:
            async for event in events:
                recorder.record(event)
                for mapped in map_agent_event(event):
                    on_event(mapped)

        if self.plan.active:
            await self._run_planner(prompt, handler, token, on_event, recorder)
            return
        await self._run_coder(prompt, handler, token, on_event, recorder)

    async def _run_coder(
        self,
        prompt: str | Sequence[UserContent],
        handler: Any,
        token: CancellationToken,
        on_event: OnEvent,
        recorder: PartialTurnRecorder,
    ) -> None:
        try:
            result = await self._get_coder().run(
                prompt,
                message_history=self.session.messages,
                event_stream_handler=handler,
                cancellation_token=token,
                usage_limits=NO_USAGE_LIMITS,
            )
        except RunCancelled:
            raise
        except Exception:
            await self._persist_partial(
                recorder, prompt, self.session.messages, into_session=True
            )
            raise
        await self.session.replace_async(result.all_messages())
        on_event(ChatEvent(kind="done", text=result.output or ""))

    async def _run_planner(
        self,
        prompt: str | Sequence[UserContent],
        handler: Any,
        token: CancellationToken,
        on_event: OnEvent,
        recorder: PartialTurnRecorder,
    ) -> None:
        try:
            result = await self._get_planner().run(
                prompt,
                message_history=self._plan_history,
                event_stream_handler=handler,
                cancellation_token=token,
                usage_limits=NO_USAGE_LIMITS,
            )
        except RunCancelled:
            raise
        except Exception:
            await self._persist_partial(
                recorder, prompt, self._plan_history, into_session=False
            )
            raise
        self._plan_history = list(result.all_messages())
        await self._persist_plan_turn(prompt)
        on_event(ChatEvent(kind="done", text=result.output or ""))
        if self.plan.read():
            on_event(ChatEvent(kind="plan_ready", text=self.plan.read()))

    async def _persist_partial(
        self,
        recorder: PartialTurnRecorder,
        prompt: str | Sequence[UserContent],
        prior: list[Any],
        *,
        into_session: bool,
    ) -> None:
        """Persiste o que o turno já produziu antes de falhar (retomada no próximo run)."""
        merged = recorder.messages(prior, prompt)
        if into_session:
            await self.session.replace_async(merged)
        else:
            self._plan_history = merged

    async def _persist_plan_turn(self, prompt: str | Sequence[UserContent]) -> None:
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        content: str | list[UserContent] = (
            prompt if isinstance(prompt, str) else list(prompt)
        )
        msgs = list(self.session.messages) + [
            ModelRequest(parts=[UserPromptPart(content=content)]),
            ModelResponse(parts=[TextPart(content=slim_plan_note(self.plan))]),
        ]
        await self.session.replace_async(msgs)

    def _get_coder(self) -> Agent[None, str]:
        if self._coder is None:
            self._coder = build_coder(
                config=self.config,
                cwd=self.cwd,
                gate=self.gate,
                on_change=self._emit_change,
                injected_model=self._injected_model,
                mcp=self.mcp,
                questions=self.questions,
                skills=self.skills,
                tasks=self.tasks,
            )
        return self._coder

    def _get_planner(self) -> Agent[None, str]:
        if self._planner is None:
            self._planner = build_planner_agent(
                config=self.config,
                cwd=self.cwd,
                plan=self.plan,
                on_exit=self._emit_plan_ready,
                on_write=self._emit_plan_draft,
                injected_model=self._injected_model,
                mcp=self.mcp,
            )
        return self._planner

    def _emit_plan_draft(self, content: str) -> None:
        if self._on_event is not None:
            self._on_event(ChatEvent(kind="plan_draft", text=content))

    def _emit_plan_ready(self) -> None:
        if self._on_event is not None:
            self._on_event(ChatEvent(kind="plan_ready", text=self.plan.read()))

    def _emit_change(self, change: FileChange) -> None:
        if self._on_event is not None:
            self._on_event(diff_event(change))

    def _emit_task(self, record: TaskRecord, terminal: bool) -> None:
        if self._on_event is not None:
            self._on_event(task_event(record, terminal=terminal))
