"""Orquestra o agent: uma request por vez, histórico nativo, stream de eventos.

A UI só conhece `ChatEvent`. Nada de pydantic_ai atravessa essa fronteira.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import (
    Agent,
    CancellationToken,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRetry,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import TextPart, TextPartDelta, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai_harness import CodeMode, Shell
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_monty import MountDir

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.permission import (
    PermissionDenied,
    PermissionGate,
    PermissionRequest,
)
from b3code.services.plan import PlanMode
from b3code.services.planner import build_planner, slim_plan_note
from b3code.services.session import SessionStore
from b3code.tools.workspace import workspace_toolset
from b3code.utils.diffview import FileChange, summary as diff_summary

# Estático de propósito: mudar instructions a cada turno invalida o cache Azure.
INSTRUCTIONS = (
    "You are b3code, a concise coding assistant. "
    "Use run_code to batch file tools (paths under /work). "
    "Use run_command for git/tests/lint. Last expression is the run_code return."
)

SHELL_TOOLS = frozenset(
    {"run_command", "start_command", "check_command", "stop_command"}
)


@dataclass
class ChatEvent:
    kind: str  # text_delta | tool_start | tool_end | done | error | diff | plan_ready
    text: str = ""
    tool: str = ""
    detail: str = ""
    change: FileChange | None = None


OnEvent = Callable[[ChatEvent], None]


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        session: SessionStore,
        cwd: Path,
        model: Model | None = None,
        gate: PermissionGate | None = None,
    ) -> None:
        self.config = config
        self.session = session
        self.cwd = cwd
        self.gate = gate
        self.plan = PlanMode(cwd)
        # Testes injetam TestModel e pulam o Azure.
        self._injected_model = model
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
        self._coder = None
        self._planner = None
        if self.gate is not None:
            self.gate.config = config

    def enter_plan(self) -> None:
        self.plan.enter()
        self._planner = None

    def exit_plan(self) -> None:
        self.plan.exit()
        self._plan_history = []
        self._planner = None

    def approve_plan(self) -> str:
        self.exit_plan()
        return "Implement the approved plan in .b3code/plan.md."

    def answer_permission(self, choice: str) -> None:
        if self.gate is not None:
            self.gate.answer(choice)

    def cancel_current(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()

    async def enqueue(self, prompt: str, on_event: OnEvent) -> None:
        """Única porta de entrada. O lock garante 1 `agent.run` por vez."""
        async with self._lock:
            self.busy = True
            try:
                await self._run_one(prompt, on_event)
            finally:
                self.busy = False

    async def _run_one(self, prompt: str, on_event: OnEvent) -> None:
        if (
            self._injected_model is None
            and self.config.use_provider_gateway
            and (not self.config.api_key or not self.config.api_endpoint)
        ):
            on_event(
                ChatEvent(
                    kind="error",
                    text="missing api_key or api_endpoint in .b3code/config.json",
                )
            )
            return

        token = CancellationToken()
        self._cancel = token
        self._on_event = on_event
        if self.gate is not None:
            self.gate.on_ask = lambda req: on_event(_permission_event(req))

        async def handler(_ctx: Any, events: Any) -> None:
            async for event in events:
                for mapped in _map_event(event):
                    on_event(mapped)

        try:
            if self.plan.active:
                await self._run_planner(prompt, handler, token, on_event)
            else:
                await self._run_coder(prompt, handler, token, on_event)
        except Exception as exc:
            on_event(ChatEvent(kind="error", text=str(exc)))
        finally:
            self._cancel = None
            self._on_event = None
            if self.gate is not None:
                self.gate.on_ask = None

    async def _run_coder(
        self, prompt: str, handler: Any, token: CancellationToken, on_event: OnEvent
    ) -> None:
        result = await self._get_coder().run(
            prompt,
            message_history=self.session.messages,
            event_stream_handler=handler,
            cancellation_token=token,
        )
        await self.session.areplace(result.all_messages())
        on_event(ChatEvent(kind="done", text=result.output or ""))

    async def _run_planner(
        self, prompt: str, handler: Any, token: CancellationToken, on_event: OnEvent
    ) -> None:
        result = await self._get_planner().run(
            prompt,
            message_history=self._plan_history,
            event_stream_handler=handler,
            cancellation_token=token,
        )
        self._plan_history = list(result.all_messages())
        await self._persist_plan_turn(prompt)
        on_event(ChatEvent(kind="done", text=result.output or ""))
        if self.plan.read():
            on_event(ChatEvent(kind="plan_ready", text=self.plan.read()))

    async def _persist_plan_turn(self, prompt: str) -> None:
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        msgs = list(self.session.messages) + [
            ModelRequest(parts=[UserPromptPart(content=prompt)]),
            ModelResponse(parts=[TextPart(content=slim_plan_note(self.plan))]),
        ]
        await self.session.areplace(msgs)

    def _get_coder(self) -> Agent[None, str]:
        if self._coder is None:
            self._coder = self._make_coder()
        return self._coder

    def _get_planner(self) -> Agent[None, str]:
        if self._planner is None:
            self._planner = self._make_planner()
        return self._planner

    def _make_planner(self) -> Agent[None, str]:
        model = self._injected_model or build_model(self.config)
        if self._injected_model is not None:
            return Agent(model, instructions="You are b3code's planner. Do not implement.")
        return build_planner(model, self.cwd, self.plan, on_exit=self._emit_plan_ready)

    def _emit_plan_ready(self) -> None:
        if self._on_event is not None:
            self._on_event(ChatEvent(kind="plan_ready", text=self.plan.read()))

    def _make_coder(self) -> Agent[None, str]:
        model = self._injected_model or build_model(self.config)
        if self._injected_model is not None:
            return Agent(model, instructions=INSTRUCTIONS)
        hooks = Hooks()

        @hooks.on.before_tool_execute(tools=["run_command", "start_command"])
        async def gate_shell(ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
            if self.gate is None:
                return args
            command = (
                args["command"]
                if isinstance(args, dict)
                else getattr(args, "command", "")
            )
            try:
                await self.gate.ensure(command)
            except PermissionDenied as exc:
                raise ModelRetry(str(exc)) from exc
            return args

        from pydantic_ai_harness.planning import Planning

        return Agent(
            model,
            instructions=INSTRUCTIONS,
            toolsets=[
                workspace_toolset(self.cwd, on_change=self._emit_change),
            ],
            capabilities=[
                Shell(
                    cwd=self.cwd,
                    persist_cwd=True,
                    default_timeout=120,
                    denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
                ),
                CodeMode(
                    tools=lambda ctx, td: td.name not in SHELL_TOOLS,
                    mount=MountDir(
                        virtual_path="/work",
                        host_path=str(self.cwd),
                        mode="read-write",
                    ),
                    max_retries=3,
                ),
                hooks,
                Planning(),
            ],
        )

    def _emit_change(self, change: FileChange) -> None:
        if self._on_event is not None:
            self._on_event(_diff_event(change))


def _diff_event(change: FileChange) -> ChatEvent:
    return ChatEvent(
        kind="diff",
        tool="write_file",
        detail=diff_summary(change),
        change=change,
    )


def _permission_event(req: PermissionRequest) -> ChatEvent:
    return ChatEvent(kind="permission", text=req.command, detail=", ".join(req.paths))


def _map_event(event: Any) -> list[ChatEvent]:
    if isinstance(event, PartStartEvent):
        content = event.part.content if isinstance(event.part, TextPart) else ""
        return [ChatEvent(kind="text_delta", text=content)] if content else []
    if isinstance(event, PartDeltaEvent):
        content = (
            event.delta.content_delta if isinstance(event.delta, TextPartDelta) else ""
        )
        return [ChatEvent(kind="text_delta", text=content)] if content else []
    if isinstance(event, FunctionToolCallEvent):
        args = str(event.part.args)
        return [
            ChatEvent(
                kind="tool_start",
                tool=event.part.tool_name,
                detail=_short(args),
            )
        ]
    if not isinstance(event, FunctionToolResultEvent) or not isinstance(
        event.part, ToolReturnPart
    ):
        return []
    events = [
        ChatEvent(
            kind="tool_end",
            tool=event.part.tool_name,
            detail=_short(str(event.part.content)),
        )
    ]
    # CodeMode empacota tools filhas em metadata do run_code.
    meta = event.part.metadata or {}
    nested = meta.get("tool_calls") or {}
    returns = meta.get("tool_returns") or {}
    for call_id, call in nested.items():
        name = getattr(call, "tool_name", "tool")
        ret = returns.get(call_id)
        detail = _short(str(getattr(ret, "content", ""))) if ret else ""
        events.append(ChatEvent(kind="tool_end", tool=name, detail=detail))
    return events


def _short(value: str, n: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= n else value[: n - 1] + "…"
