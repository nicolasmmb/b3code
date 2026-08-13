"""Eventos de chat. Nada de pydantic_ai atravessa esta fronteira para a UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.messages import TextPart, TextPartDelta, ToolReturnPart

from b3code.services.permission import PermissionRequest
from b3code.utils.diffview import FileChange
from b3code.utils.diffview import summary as diff_summary
from b3code.utils.text import ellipsize

ChatEventKind = Literal[
    "text_delta",
    "tool_start",
    "tool_end",
    "done",
    "error",
    "diff",
    "plan_ready",
    "plan_draft",
    "permission",
]


@dataclass
class ChatEvent:
    kind: ChatEventKind
    text: str = ""
    tool: str = ""
    detail: str = ""
    change: FileChange | None = None


OnEvent = Callable[[ChatEvent], None]


def diff_event(change: FileChange) -> ChatEvent:
    return ChatEvent(
        kind="diff",
        tool="write_file",
        detail=diff_summary(change),
        change=change,
    )


def permission_event(req: PermissionRequest) -> ChatEvent:
    return ChatEvent(kind="permission", text=req.command, detail=", ".join(req.paths))


def map_agent_event(event: Any) -> list[ChatEvent]:
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
                detail=ellipsize(args),
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
            detail=ellipsize(str(event.part.content)),
        )
    ]
    # CodeMode empacota tools filhas em metadata do run_code.
    meta = event.part.metadata or {}
    nested = meta.get("tool_calls") or {}
    returns = meta.get("tool_returns") or {}
    for call_id, call in nested.items():
        name = getattr(call, "tool_name", "tool")
        ret = returns.get(call_id)
        detail = ellipsize(str(getattr(ret, "content", ""))) if ret else ""
        events.append(ChatEvent(kind="tool_end", tool=name, detail=detail))
    return events
