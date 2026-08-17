"""Recorder parcial de um turno.

Observa o event stream e reconstrói as mensagens do PydanticAI que já foram
produzidas (thinking/texto/tool calls/tool returns) *antes* de uma falha dura
(rede, crash de capability, etc.). No sucesso o `result.all_messages()` é usado
normalmente; o recorder só é chamado quando o run morre no meio.

O objetivo: quando o próximo turno roda, ele retoma do ponto em que parou — o
raciocínio já emitido não é perdido e não é reprocessado do zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)

_MAX_PARTS = 200

TextDelta = TextPartDelta | ThinkingPartDelta


class PartialTurnRecorder:
    """Acumula as mensagens parciais de um turno a partir do event stream."""

    def __init__(self) -> None:
        self._messages: list[ModelMessage] = []
        self._current: list[Any] = []  # partes do ModelResponse em montagem
        self._returns: list[Any] = []  # ToolReturnPart do ModelRequest corrente
        self._pending: set[str] = set()

    def record(self, event: Any) -> None:
        if isinstance(event, PartStartEvent):
            self._on_part_start(event.part)
        elif isinstance(event, PartDeltaEvent):
            self._on_part_delta(event.delta)
        elif isinstance(event, FunctionToolCallEvent):
            self._on_tool_call(event.part)
        elif isinstance(event, FunctionToolResultEvent) and isinstance(
            event.part, ToolReturnPart
        ):
            self._on_tool_return(event.part)

    # --- handlers ----------------------------------------------------------

    def _on_part_start(self, part: Any) -> None:
        if isinstance(part, (TextPart, ThinkingPart)) and part.content:
            self._start_response()
            self._current.append(part)

    def _on_part_delta(self, delta: Any) -> None:
        if isinstance(delta, (TextPartDelta, ThinkingPartDelta)) and delta.content_delta:
            self._start_response()
            if self._current:
                last = self._current[-1]
                if isinstance(last, TextPart) and isinstance(delta, TextPartDelta):
                    self._current[-1] = TextPart(content=last.content + delta.content_delta)
                    return
                if isinstance(last, ThinkingPart) and isinstance(delta, ThinkingPartDelta):
                    self._current[-1] = ThinkingPart(content=last.content + delta.content_delta)
                    return
            # Fallback: delta sem PartStart (raro) — cria a parte base.
            if isinstance(delta, TextPartDelta):
                self._current.append(TextPart(content=delta.content_delta))
            elif isinstance(delta, ThinkingPartDelta):
                self._current.append(ThinkingPart(content=delta.content_delta))

    def _on_tool_call(self, part: ToolCallPart) -> None:
        self._start_response()
        self._current.append(part)
        self._pending.add(part.tool_call_id)

    def _on_tool_return(self, part: ToolReturnPart) -> None:
        # O ModelResponse com a tool call terminou: fecha e empurra para _messages.
        self._flush_response()
        self._returns.append(part)
        self._pending.discard(part.tool_call_id)

    # --- helpers -----------------------------------------------------------

    def _start_response(self) -> None:
        # Uma nova resposta (texto/thinking/tool call) inicia: fecha o request de
        # returns anterior se houver, na ordem correta.
        if self._returns:
            self._flush_returns()

    def _flush_response(self) -> None:
        if not self._current:
            return
        self._messages.append(ModelResponse(parts=list(self._current)))
        self._current = []

    def _flush_returns(self) -> None:
        if not self._returns:
            return
        self._messages.append(ModelRequest(parts=list(self._returns)))
        self._returns = []

    def _append_part(self, part: Any) -> None:
        if len(self._current) >= _MAX_PARTS:
            return
        self._current.append(part)

    # --- saída -------------------------------------------------------------

    def messages(
        self, prior: list[ModelMessage], prompt: str | Sequence[UserContent]
    ) -> list[ModelMessage]:
        result = list(prior)
        content: str | list[UserContent] = (
            prompt if isinstance(prompt, str) else list(prompt)
        )
        result.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        # Request de returns corrente vai antes do ModelResponse corrente.
        self._flush_returns()
        result.extend(self._messages)
        # ModelResponse corrente entra só se estiver completo (sem tool call pendente).
        if self._current and not self._pending:
            result.append(ModelResponse(parts=list(self._current)))
        return result
