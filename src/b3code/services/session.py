"""Sessões: índice em `sessions.json`, mensagens em `sessions/{id}.json`.

Gravamos `result.all_messages()` (objetos nativos do Pydantic AI), não
`{"role":"user"}` reconstruído — isso quebra pairing de tools e o
prefixo idêntico que o cache Azure exige.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from b3code.utils.paths import atomic_write_text
from b3code.utils.prompt import display_user_content
from b3code.utils.toolview import preview_output, tool_title


class Session(BaseModel):
    id: str
    created_at: str
    # dump JSON-friendly do adapter — só carregado na sessão ativa
    messages: list[Any] = Field(default_factory=list)
    message_count: int = 0


class SessionFile(BaseModel):
    active_id: str | None = None
    sessions: list[Session] = Field(default_factory=list)


@dataclass
class DisplayTurn:
    """O que a UI precisa pintar. Sem tipos do pydantic_ai."""

    role: Literal["user", "assistant", "thinking", "tool"]
    text: str
    tool: str = ""
    detail: str = ""
    output: str = ""
    call_id: str = ""


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._dir = path.parent / "sessions"
        self._file, self._current = self._load()
        self._messages: list[ModelMessage] | None = None

    @classmethod
    def for_cwd(cls, cwd: Path) -> SessionStore:
        return cls(cwd / ".b3code" / "sessions.json")

    def _blob_path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    @property
    def current_id(self) -> str:
        return self._current.id

    @property
    def messages(self) -> list[ModelMessage]:
        if self._messages is not None:
            return self._messages
        self._messages = (
            ModelMessagesTypeAdapter.validate_python(self._current.messages)
            if self._current.messages
            else []
        )
        return self._messages

    def replace(self, messages: list[ModelMessage]) -> None:
        # all_messages() = histórico completo acumulado. new_messages()
        # só tem o turno atual e quebraria o próximo request.
        self._install(messages)
        self._save()

    async def replace_async(self, messages: list[ModelMessage]) -> None:
        self._install(messages)
        await asyncio.to_thread(self._save)

    def new(self) -> Session:
        session = _blank_session()
        self._file.sessions.append(session)
        self._file.active_id = session.id
        self._current = session
        self._messages = []
        self._save()
        return session

    def list_sessions(self) -> list[Session]:
        return list(self._file.sessions)

    def activate(self, session_id: str) -> Session:
        for session in self._file.sessions:
            if session.id == session_id:
                self._file.active_id = session.id
                self._current = session
                self._messages = None
                self._current.messages = self._read_blob(session.id)
                self._save_index()
                return session
        raise ValueError(f"unknown session {session_id!r}")

    def display_turns(self) -> list[DisplayTurn]:
        return turns_from_messages(self.messages)

    def _install(self, messages: list[ModelMessage]) -> None:
        dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
        self._current.messages = dumped
        self._current.message_count = len(messages)
        self._messages = list(messages)

    def _load(self) -> tuple[SessionFile, Session]:
        if not self.path.exists():
            session = _blank_session()
            data = SessionFile(active_id=session.id, sessions=[session])
            return data, session
        payload = SessionFile.model_validate_json(self.path.read_text(encoding="utf-8"))
        current = next((s for s in payload.sessions if s.id == payload.active_id), None)
        if current is None:
            current = _blank_session()
            payload.sessions.append(current)
            payload.active_id = current.id
        current.messages = self._read_blob(current.id)
        return payload, current

    def _read_blob(self, session_id: str) -> list[Any]:
        blob = self._blob_path(session_id)
        if not blob.exists():
            return []
        data = Session.model_validate_json(blob.read_text(encoding="utf-8"))
        return data.messages

    def _write_blob(self, session: Session) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._blob_path(session.id),
            Session(
                id=session.id,
                created_at=session.created_at,
                messages=session.messages,
                message_count=session.message_count,
            ).model_dump_json(indent=2)
            + "\n",
        )

    def _save_index(self) -> None:
        slim = {
            "active_id": self._file.active_id,
            "sessions": [
                {
                    "id": item.id,
                    "created_at": item.created_at,
                    "message_count": item.message_count,
                }
                for item in self._file.sessions
            ],
        }
        atomic_write_text(self.path, json.dumps(slim, indent=2) + "\n")

    def _save(self) -> None:
        self._write_blob(self._current)
        self._save_index()


def _blank_session() -> Session:
    return Session(
        id=uuid4().hex[:8],
        created_at=datetime.now(UTC).isoformat(),
    )


def turns_from_messages(messages: list[ModelMessage]) -> list[DisplayTurn]:
    returns = _collect_returns(messages)
    turns: list[DisplayTurn] = []
    for msg in messages:
        turns.extend(_turns_from_message(msg, returns))
    return _collapse_subagent_turns(turns)


def _collapse_subagent_turns(turns: list[DisplayTurn]) -> list[DisplayTurn]:
    cards: dict[str, DisplayTurn] = {}
    pending: dict[str, str] = {}
    out: list[DisplayTurn] = []
    for turn in turns:
        if turn.tool == "spawn_subagent":
            out.append(_card_from_spawn(turn, cards, pending))
        elif turn.tool == "get_command_or_subagent_output":
            _apply_snapshots(turn.output, cards, pending)
        elif turn.tool != "kill_command_or_subagent":
            out.append(turn)
    return out


def _card_from_spawn(
    turn: DisplayTurn,
    cards: dict[str, DisplayTurn],
    pending: dict[str, str],
) -> DisplayTurn:
    content = (turn.output or "").strip()
    card = DisplayTurn(
        role="tool",
        text="",
        tool="subagent",
        detail=turn.detail,
        output="" if content.startswith("started ") else content,
        call_id=turn.call_id,
    )
    task_id = _sa_id(content)
    if not task_id:
        return card
    card.call_id = task_id
    cards[task_id] = card
    if task_id in pending:
        card.output = pending.pop(task_id)
    return card


def _apply_snapshots(
    text: str, cards: dict[str, DisplayTurn], pending: dict[str, str]
) -> None:
    for task_id, body in _snapshot_bodies(text):
        if task_id in cards:
            cards[task_id].output = body
        else:
            pending[task_id] = body


def _sa_id(text: str) -> str:
    for token in (text or "").replace("(", " ").replace(")", " ").split():
        if token.startswith("sa-") and len(token) == 11:
            return token
    return ""


def _snapshot_bodies(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    current = ""
    steps: list[str] = []
    summary: list[str] = []
    in_summary = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("sa-") and " (" in line:
            _flush_snapshot(found, current, steps, summary)
            current = line.split()[0]
            steps, summary, in_summary = [], [], False
            continue
        step, summary_line, in_summary = _snapshot_line(line, current, in_summary)
        if step is not None:
            steps.append(step)
        elif summary_line is not None:
            summary.append(summary_line)
    _flush_snapshot(found, current, steps, summary)
    return found


def _snapshot_line(
    line: str, current: str, in_summary: bool
) -> tuple[str | None, str | None, bool]:
    if not current:
        return None, None, in_summary
    content = line[2:] if line.startswith("  ") else line
    if content == "—":
        return None, None, True
    if content.startswith("· "):
        content = content[2:]
    if in_summary:
        return None, content, True
    return content, None, False


def _flush_snapshot(
    found: list[tuple[str, str]],
    current: str,
    steps: list[str],
    summary: list[str],
) -> None:
    if not current:
        return
    chunks = [f"· {step}" for step in steps]
    body = "\n".join(summary).strip()
    if body:
        if chunks:
            chunks.append("—")
        chunks.append(body)
    if chunks:
        found.append((current, "\n".join(chunks)))


def _collect_returns(messages: list[ModelMessage]) -> dict[str, ToolReturnPart]:
    found: dict[str, ToolReturnPart] = {}
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id:
                found[part.tool_call_id] = part
    return found


def _turns_from_message(
    msg: ModelMessage, returns: dict[str, ToolReturnPart]
) -> list[DisplayTurn]:
    if isinstance(msg, ModelRequest):
        return _turns_from_request(msg)
    if isinstance(msg, ModelResponse):
        return _turns_from_response(msg, returns)
    return []


def _turns_from_request(msg: ModelRequest) -> list[DisplayTurn]:
    turns: list[DisplayTurn] = []
    for part in msg.parts:
        if not isinstance(part, UserPromptPart):
            continue
        cleaned = display_user_content(part.content)
        if cleaned:
            turns.append(DisplayTurn(role="user", text=cleaned))
    return turns


def _turns_from_response(
    msg: ModelResponse, returns: dict[str, ToolReturnPart]
) -> list[DisplayTurn]:
    turns: list[DisplayTurn] = []
    for part in msg.parts:
        if isinstance(part, ToolCallPart):
            turns.extend(_turns_from_tool_call(part, returns.get(part.tool_call_id)))
            continue
        if isinstance(part, ThinkingPart) and part.content:
            turns.append(DisplayTurn(role="thinking", text=part.content))
            continue
        if isinstance(part, TextPart) and part.content:
            turns.append(DisplayTurn(role="assistant", text=part.content))
    return turns


def _turns_from_tool_call(
    part: ToolCallPart, ret: ToolReturnPart | None
) -> list[DisplayTurn]:
    turns = [_turn_from_call(part.tool_name, part.args, part.tool_call_id, ret)]
    if ret is None:
        return turns
    meta = ret.metadata or {}
    nested = meta.get("tool_calls") or {}
    replies = meta.get("tool_returns") or {}
    for call_id, call in nested.items():
        name = getattr(call, "tool_name", "tool")
        args = getattr(call, "args", {})
        child = replies.get(call_id)
        turns.append(_turn_from_call(name, args, str(call_id), child))
    return turns


def _turn_from_call(name: str, args: Any, call_id: str, ret: Any | None) -> DisplayTurn:
    content = getattr(ret, "content", "") if ret is not None else ""
    return DisplayTurn(
        role="tool",
        text="",
        tool=name,
        detail=tool_title(name, args),
        output=preview_output(str(content) if content else ""),
        call_id=call_id or "",
    )
