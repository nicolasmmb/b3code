"""ask_user_question — card bloqueante, fora do run_code."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel
from pydantic_ai.toolsets import FunctionToolset

from b3code.services.questions import QuestionGate
from b3code.utils.retry import model_retry


class OptionSpec(BaseModel):
    label: str
    description: str = ""


class QuestionSpec(BaseModel):
    question: str
    options: list[OptionSpec]
    multi_select: bool = False


def ask_toolset(gate: QuestionGate) -> FunctionToolset:
    @model_retry
    async def ask_user_question(questions: Sequence[QuestionSpec]) -> str:
        """Ask the user a multiple-choice question. Use when a choice is cheaper than an assumption."""
        return await gate.ask(questions)

    return FunctionToolset(tools=[ask_user_question])
