"""Coder usa CodeMode; planner continua nativo. Sem Planning() do harness."""

from pathlib import Path

from pydantic_ai.models.test import TestModel

from b3code.config.schema import AppConfig
from b3code.services.agents import INSTRUCTIONS, build_coder
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore


def _coder(tmp_path: Path):
    return build_coder(
        config=AppConfig(use_provider_gateway=False, selected_model="openai:gpt-4o"),
        cwd=tmp_path,
    )


def _capability_names(agent) -> set[str]:
    return {type(cap).__name__ for cap in agent.root_capability.capabilities}


def test_instructions_teach_run_code():
    assert "run_code" in INSTRUCTIONS
    assert "not in the schema" in INSTRUCTIONS
    assert "search_tool" in INSTRUCTIONS
    assert "use_tool" in INSTRUCTIONS


def test_coder_has_codemode_and_shell_not_planning(tmp_path: Path):
    caps = _capability_names(_coder(tmp_path))
    assert "CodeMode" in caps
    assert "Shell" in caps
    assert "Planning" not in caps


def test_approve_plan_sends_implementer_through_run_code(tmp_path: Path):
    chat = ChatService(
        AppConfig(api_models=["test"]),
        SessionStore(tmp_path / "sessions.json"),
        tmp_path,
        model=TestModel(),
    )
    chat.enter_plan()
    prompt = chat.approve_plan()
    assert "run_code" in prompt
    assert "read_file" in prompt
    assert "shell" in prompt.lower()
    assert chat.plan.active is False
