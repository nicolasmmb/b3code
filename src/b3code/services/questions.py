"""Pergunta bloqueante no meio do turno. Future + callback, como PermissionGate."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic_ai.exceptions import ModelRetry

MAX_QUESTIONS = 4
MAX_OPTIONS = 6
OTHER_LABEL = "Other"
OTHER_HINT = "type your own answer"


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str = ""


@dataclass(frozen=True)
class Question:
    question: str
    options: tuple[QuestionOption, ...]


OnAsk = Callable[[tuple[Question, ...]], None]


class QuestionGate:
    def __init__(self) -> None:
        self.pending: asyncio.Future[str] | None = None
        self.on_ask: OnAsk | None = None

    async def ask(self, raw: Sequence[object]) -> str:
        questions = normalize_questions(raw)
        loop = asyncio.get_running_loop()
        self.pending = loop.create_future()
        if self.on_ask is not None:
            self.on_ask(questions)
        try:
            return await self.pending
        finally:
            self.pending = None

    def answer(self, text: str) -> None:
        self._resolve(text)

    def dismiss(self) -> None:
        self._resolve("skipped")

    def cancel_pending(self) -> None:
        future = self.pending
        if future is None or future.done():
            return
        future.cancel()

    def _resolve(self, text: str) -> None:
        future = self.pending
        if future is not None and not future.done():
            future.set_result(text)


def normalize_questions(raw: Sequence[object]) -> tuple[Question, ...]:
    if not raw:
        raise ModelRetry("ask_user_question needs at least one question")
    if len(raw) > MAX_QUESTIONS:
        raise ModelRetry(f"ask_user_question accepts at most {MAX_QUESTIONS} questions")
    return tuple(_one_question(item) for item in raw)


def _one_question(raw: object) -> Question:
    data = _as_map(raw)
    if bool(data.get("multi_select")):
        raise ModelRetry("multi_select is not supported")
    title = str(data.get("question") or "").strip()
    if not title:
        raise ModelRetry("question text is required")
    options = _options(data.get("options"))
    return Question(question=title, options=options)


def _options(raw: object) -> tuple[QuestionOption, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ModelRetry("each question needs options")
    if not raw:
        raise ModelRetry("each question needs options")
    if len(raw) > MAX_OPTIONS:
        raise ModelRetry(f"at most {MAX_OPTIONS} options per question")
    parsed = tuple(_one_option(item) for item in raw)
    if any(opt.label.lower() == OTHER_LABEL.lower() for opt in parsed):
        return parsed
    return parsed + (QuestionOption(label=OTHER_LABEL, description=OTHER_HINT),)


def _one_option(raw: object) -> QuestionOption:
    data = _as_map(raw)
    label = str(data.get("label") or "").strip()
    if not label:
        raise ModelRetry("option label is required")
    return QuestionOption(label=label, description=str(data.get("description") or ""))


def _as_map(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    data: dict[str, object] = {}
    for key in ("question", "options", "multi_select", "label", "description"):
        if hasattr(raw, key):
            data[key] = getattr(raw, key)
    if data:
        return data
    raise ModelRetry("invalid question payload")
