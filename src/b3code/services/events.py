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
from b3code.services.questions import Question
from b3code.services.tasks import TaskRecord
from b3code.utils.diffview import FileChange
from b3code.utils.diffview import summary as diff_summary
from b3code.utils.toolview import preview_output, tool_title

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
    "question",
    "task",
]


@dataclass
class ChatEvent:
    kind: ChatEventKind
    text: str = ""
    tool: str = ""
    detail: str = ""
    output: str = ""
    call_id: str = ""
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


def question_event(questions: tuple[Question, ...]) -> ChatEvent:
    blocks = [_question_block(item) for item in questions]
    return ChatEvent(kind="question", text="\n\n".join(blocks))


def task_event(record: TaskRecord, *, terminal: bool) -> ChatEvent:
    return ChatEvent(
        kind="task",
        text=record.status if terminal else "running",
        tool="subagent",
        detail=_task_title(record, terminal, record.elapsed),
        output=_task_output(record) if terminal else "",
        call_id=record.id,
    )


def _question_block(item: Question) -> str:
    lines = [item.question]
    lines.extend(f"{opt.label} — {opt.description}" for opt in item.options)
    return "\n".join(lines)


def _task_title(record: TaskRecord, terminal: bool, elapsed: int) -> str:
    parts = [record.kind, record.description]
    if not terminal and record.activity:
        parts.append(record.activity)
    if terminal and record.status in {"failed", "cancelled"}:
        parts.append(record.status)
    parts.append(f"{elapsed}s")
    return " · ".join(part for part in parts if part)


def _task_output(record: TaskRecord) -> str:
    chunks = list(record.steps)
    body = record.output.strip()
    if body:
        if chunks:
            chunks.append("—")
        chunks.append(body)
    elif record.status != "done":
        chunks.append(record.status)
    return preview_output("\n".join(chunks)) if chunks else record.status


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
        return [_start_event(event)]
    if not isinstance(event, FunctionToolResultEvent) or not isinstance(
        event.part, ToolReturnPart
    ):
        return []
    return _end_events(event.part)


def _call_id(part: Any) -> str:
    return str(getattr(part, "tool_call_id", "") or "")


def _start_event(event: FunctionToolCallEvent) -> ChatEvent:
    part = event.part
    return ChatEvent(
        kind="tool_start",
        tool=part.tool_name,
        detail=tool_title(part.tool_name, part.args),
        call_id=_call_id(part) or _call_id(event),
    )


def _end_events(part: ToolReturnPart) -> list[ChatEvent]:
    events = [
        ChatEvent(
            kind="tool_end",
            tool=part.tool_name,
            output=preview_output(str(part.content)),
            call_id=_call_id(part),
        )
    ]
    meta = part.metadata or {}
    nested = meta.get("tool_calls") or {}
    returns = meta.get("tool_returns") or {}
    for call_id, call in nested.items():
        name = getattr(call, "tool_name", "tool")
        args = getattr(call, "args", {})
        ret = returns.get(call_id)
        content = getattr(ret, "content", "") if ret else ""
        events.append(
            ChatEvent(
                kind="tool_end",
                tool=name,
                detail=tool_title(name, args),
                output=preview_output(str(content) if content else ""),
                call_id=str(call_id),
            )
        )
    return events
