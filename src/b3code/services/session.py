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
    ToolCallPart,
    UserPromptPart,
)

from b3code.utils.paths import atomic_write_text
from b3code.utils.prompt import display_user_content
from b3code.utils.text import ellipsize


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

    role: Literal["user", "assistant", "tool"]
    text: str
    tool: str = ""
    detail: str = ""


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
    turns: list[DisplayTurn] = []
    for msg in messages:
        turns.extend(_turns_from_message(msg))
    return turns


def _turns_from_message(msg: ModelMessage) -> list[DisplayTurn]:
    if isinstance(msg, ModelRequest):
        return _turns_from_request(msg)
    if isinstance(msg, ModelResponse):
        return _turns_from_response(msg)
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


def _turns_from_response(msg: ModelResponse) -> list[DisplayTurn]:
    turns: list[DisplayTurn] = []
    for part in msg.parts:
        if isinstance(part, ToolCallPart):
            args = (
                part.args_as_json_str()
                if hasattr(part, "args_as_json_str")
                else str(part.args)
            )
            turns.append(
                DisplayTurn(
                    role="tool",
                    text="",
                    tool=part.tool_name,
                    detail=ellipsize(args),
                )
            )
            continue
        if isinstance(part, TextPart) and part.content:
            turns.append(DisplayTurn(role="assistant", text=part.content))
    return turns
