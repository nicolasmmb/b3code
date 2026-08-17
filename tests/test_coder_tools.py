"""Coder usa CodeMode; planner continua nativo. Sem Planning() do harness."""

from pathlib import Path

from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition

from b3code.config.schema import AppConfig
from b3code.services.agents import (
    CODER_INSTRUCTIONS,
    HOST_TOOLS,
    _host_tool,
    build_coder,
    thinking_cap,
)
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
    # CODER_INSTRUCTIONS é um bloco de texto único (não mais uma tupla).
    text = CODER_INSTRUCTIONS
    assert "run_code" in text
    assert "not in the schema" in text
    assert "search_tools" in text
    assert "todo_write" not in text
    assert "ask_user_question" in text
    assert "spawn_subagent" in text
    assert "use_tool" not in text


def test_orchestration_tools_stay_native():
    class _Def:
        def __init__(self, name: str) -> None:
            self.name = name

    for name in HOST_TOOLS:
        assert _host_tool(None, _Def(name)) is False
    assert _host_tool(None, _Def("read_file")) is True


def test_coder_has_codemode_and_shell_not_planning(tmp_path: Path):
    caps = _capability_names(_coder(tmp_path))
    assert "CodeMode" in caps
    assert "Shell" in caps
    assert "WebSearch" in caps
    assert "Planning" not in caps


def test_thinking_cap_follows_config():
    assert thinking_cap(AppConfig(thinking="off")) is None
    auto = thinking_cap(AppConfig(thinking="auto"))
    assert auto is not None
    assert auto.effort is True
    high = thinking_cap(AppConfig(thinking="high"))
    assert high is not None
    assert high.effort == "high"


def test_coder_includes_thinking_when_enabled(tmp_path: Path):
    off = build_coder(
        config=AppConfig(
            use_provider_gateway=False, selected_model="openai:gpt-4o", thinking="off"
        ),
        cwd=tmp_path,
    )
    on = build_coder(
        config=AppConfig(
            use_provider_gateway=False, selected_model="openai:gpt-4o", thinking="high"
        ),
        cwd=tmp_path,
    )
    assert "Thinking" not in _capability_names(off)
    assert "Thinking" in _capability_names(on)


def test_websearch_falls_back_on_gateway_chat_model(tmp_path: Path):
    agent = _coder(tmp_path)
    web = next(
        cap
        for cap in agent.root_capability.capabilities
        if type(cap).__name__ == "WebSearch"
    )
    inner = web.get_toolset().wrapped
    params = ModelRequestParameters(
        native_tools=list(web.get_native_tools()),
        function_tools=[
            ToolDefinition(
                name=name,
                description=name,
                parameters_json_schema={"type": "object", "properties": {}},
                unless_native=web._native_unique_id(),
            )
            for name in inner.tools
        ],
    )
    model = OpenAIChatModel(
        "deepseek-v4-pro",
        provider=OpenAIProvider(api_key="x", base_url="https://example.invalid/v1"),
    )
    model.prepare_request(None, params)
    assert "duckduckgo_search" in inner.tools
    assert "duckduckgo_search" in HOST_TOOLS


def test_approve_plan_sends_implementer_through_run_code(tmp_path: Path):
    chat = ChatService(
        AppConfig(gateway_api_models=["test"]),
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
