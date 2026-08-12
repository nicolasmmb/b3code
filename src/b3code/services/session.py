"""Sessões em `.b3code/sessions.json`.

Gravamos `result.all_messages()` (objetos nativos do Pydantic AI), não
`{"role":"user"}` reconstruído — isso quebra pairing de tools e o
prefixo idêntico que o cache Azure exige.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
from b3code.utils.prompt import strip_file_blocks


class Session(BaseModel):
    id: str
    created_at: str
    # dump JSON-friendly do adapter — validado na leitura, não aqui
    messages: list[Any] = Field(default_factory=list)


class SessionFile(BaseModel):
    active_id: str | None = None
    sessions: list[Session] = Field(default_factory=list)


@dataclass
class DisplayTurn:
    """O que a UI precisa pintar. Sem tipos do pydantic_ai."""

    role: str  # user | assistant | tool
    text: str
    tool: str = ""
    detail: str = ""


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file, self._current = self._load()
        self._messages: list[ModelMessage] | None = None

    @classmethod
    def for_cwd(cls, cwd: Path) -> "SessionStore":
        return cls(cwd / ".b3code" / "sessions.json")

    @property
    def current_id(self) -> str:
        return self._current.id

    @property
    def messages(self) -> list[ModelMessage]:
        if self._messages is None:
            if not self._current.messages:
                self._messages = []
            else:
                self._messages = ModelMessagesTypeAdapter.validate_python(
                    self._current.messages
                )
        return self._messages

    def replace(self, messages: list[ModelMessage]) -> None:
        # all_messages() = histórico completo acumulado. new_messages()
        # só tem o turno atual e quebraria o próximo request.
        self._install(messages)
        self._save()

    async def areplace(self, messages: list[ModelMessage]) -> None:
        self._install(messages)
        payload = self._file.model_dump_json(indent=2) + "\n"
        await asyncio.to_thread(atomic_write_text, self.path, payload)

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
                self._save()
                return session
        raise ValueError(f"unknown session {session_id!r}")

    def display_turns(self) -> list[DisplayTurn]:
        return turns_from_messages(self.messages)

    def _install(self, messages: list[ModelMessage]) -> None:
        self._current.messages = ModelMessagesTypeAdapter.dump_python(messages)
        self._messages = list(messages)

    def _load(self) -> tuple[SessionFile, Session]:
        if not self.path.exists():
            session = _blank_session()
            data = SessionFile(active_id=session.id, sessions=[session])
            return data, session
        data = SessionFile.model_validate_json(self.path.read_text(encoding="utf-8"))
        current = next((s for s in data.sessions if s.id == data.active_id), None)
        if current is None:
            current = _blank_session()
            data.sessions.append(current)
            data.active_id = current.id
        return data, current

    def _save(self) -> None:
        atomic_write_text(self.path, self._file.model_dump_json(indent=2) + "\n")


def _blank_session() -> Session:
    return Session(
        id=uuid4().hex[:8],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def turns_from_messages(messages: list[ModelMessage]) -> list[DisplayTurn]:
    turns: list[DisplayTurn] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    text = (
                        part.content
                        if isinstance(part.content, str)
                        else str(part.content)
                    )
                    cleaned = strip_file_blocks(text)
                    if cleaned:
                        turns.append(DisplayTurn(role="user", text=cleaned))
        elif isinstance(msg, ModelResponse):
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
                            text=args,
                            tool=part.tool_name,
                            detail=_short(args),
                        )
                    )
                elif isinstance(part, TextPart) and part.content:
                    turns.append(DisplayTurn(role="assistant", text=part.content))
    return turns


def _short(value: str, n: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= n else value[: n - 1] + "…"
