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
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.messages import TextPart, TextPartDelta, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai_harness import CodeMode
from pydantic_monty import MountDir

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.session import SessionStore
from b3code.tools.workspace import workspace_toolset

# Estático de propósito: mudar instructions a cada turno invalida o cache Azure.
INSTRUCTIONS = (
    "You are b3code, a concise coding assistant in the current workspace. "
    "Prefer CodeMode: write Python that calls tools instead of many round-trips."
)


@dataclass
class ChatEvent:
    kind: str  # text_delta | tool_start | tool_end | done | error
    text: str = ""
    tool: str = ""
    detail: str = ""


OnEvent = Callable[[ChatEvent], None]


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        session: SessionStore,
        cwd: Path,
        model: Model | None = None,
    ) -> None:
        self.config = config
        self.session = session
        self.cwd = cwd
        # Testes injetam TestModel e pulam o Azure.
        self._injected_model = model
        self._agent: Agent[None, str] | None = None
        # Lock = fila FIFO. Dois enqueue() ao mesmo tempo: o segundo espera.
        self._lock = asyncio.Lock()
        self._cancel: CancellationToken | None = None
        self.busy = False

    def reload(self, config: AppConfig) -> None:
        """Recria o agent no próximo run (ex.: /model). Histórico fica no store."""
        self.config = config
        self._agent = None

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

        async def handler(_ctx: Any, events: Any) -> None:
            async for event in events:
                for mapped in _map_event(event):
                    on_event(mapped)

        try:
            result = await self._get_agent().run(
                prompt,
                message_history=self.session.messages,
                event_stream_handler=handler,
                cancellation_token=token,
            )
            # Persistir o acumulado (user + llm + tools) para o próximo turno
            # reusar o mesmo prefixo e acertar o cache.
            self.session.replace(result.all_messages())
            on_event(ChatEvent(kind="done", text=result.output or ""))
        except Exception as exc:
            on_event(ChatEvent(kind="error", text=str(exc)))
        finally:
            self._cancel = None

    def _get_agent(self) -> Agent[None, str]:
        if self._agent is None:
            self._agent = self._make_agent()
        return self._agent

    def _make_agent(self) -> Agent[None, str]:
        model = self._injected_model or build_model(self.config)
        # TestModel/FunctionModel não precisam de CodeMode — ele só gera retries.
        if self._injected_model is not None:
            return Agent(model, instructions=INSTRUCTIONS)
        return Agent(
            model,
            instructions=INSTRUCTIONS,
            toolsets=[workspace_toolset(self.cwd)],
            capabilities=[
                CodeMode(
                    tools="all",
                    max_retries=3,
                    mount=MountDir(
                        virtual_path="/work",
                        host_path=str(self.cwd),
                        mode="read-write",
                    ),
                )
            ],
        )


def _map_event(event: Any) -> list[ChatEvent]:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        if event.part.content:
            return [ChatEvent(kind="text_delta", text=event.part.content)]
        return []
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        if event.delta.content_delta:
            return [ChatEvent(kind="text_delta", text=event.delta.content_delta)]
        return []
    if isinstance(event, FunctionToolCallEvent):
        args = str(event.part.args)
        return [
            ChatEvent(
                kind="tool_start",
                tool=event.part.tool_name,
                detail=_short(args),
            )
        ]
    if isinstance(event, FunctionToolResultEvent) and isinstance(event.part, ToolReturnPart):
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
    return []


def _short(value: str, n: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= n else value[: n - 1] + "…"
