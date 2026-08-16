"""Reproduz cancelamento no plan mode (serviço + TUI)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic_ai.models.test import TestModel

from b3code.config.schema import AppConfig
from b3code.container import AppContainer
from b3code.services.chat import ChatEvent, ChatService
from b3code.services.session import SessionStore
from b3code.ui.app import B3App
from b3code.ui.prompt_bar import PromptBar
from b3code.ui.screens.chat import ChatScreen


def _service(tmp_path: Path) -> ChatService:
    cfg = AppConfig(
        gateway_api_key="test",
        gateway_api_endpoint="https://example.openai.azure.com/openai/v1/",
        gateway_api_models=["test"],
    )
    return ChatService(cfg, SessionStore(tmp_path / "sessions.json"), tmp_path, model=TestModel())


async def test_cancel_current_stops_function_model_planner(tmp_path: Path):
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    started = asyncio.Event()

    async def hang(_messages, _info):
        started.set()
        await asyncio.sleep(30)
        return ModelResponse(parts=[TextPart(content="should not finish")])

    async def hang_stream(_messages, _info):
        started.set()
        await asyncio.sleep(30)
        yield "should not finish"

    chat = ChatService(
        AppConfig(gateway_api_models=["test"]),
        SessionStore(tmp_path / "sessions.json"),
        tmp_path,
        model=FunctionModel(hang, stream_function=hang_stream),
    )
    chat.enter_plan()
    events: list[ChatEvent] = []
    task = asyncio.create_task(chat.enqueue("sketch", events.append))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert chat.busy is True
    chat.cancel_current()
    await asyncio.wait_for(task, timeout=3)
    assert chat.busy is False
    kinds = [event.kind for event in events]
    assert "plan_ready" not in kinds
    assert any(event.kind == "error" for event in events)


async def test_escape_while_prompt_focused_cancels_busy_plan(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    cancelled = []
    started = asyncio.Event()

    async def hang(prompt: str, on_event) -> None:
        started.set()
        await asyncio.Event().wait()

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.deps.chat.enter_plan()
        screen.deps.chat.enqueue = hang  # type: ignore[method-assign]
        screen.deps.chat.cancel_current = lambda: cancelled.append("cancel")  # type: ignore[method-assign]
        screen.deps.chat.busy = True
        screen._send_chat("faz um plano")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert cancelled == ["cancel"], (
            f"Esc com o prompt focado não chegou em cancel_current: {cancelled!r}"
        )


async def test_escape_cancels_real_enqueue_in_plan_mode(tmp_path: Path):
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    started = asyncio.Event()

    async def hang(_messages, _info):
        started.set()
        await asyncio.sleep(30)
        return ModelResponse(parts=[TextPart(content="nope")])

    async def hang_stream(_messages, _info):
        started.set()
        await asyncio.sleep(30)
        yield "nope"

    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        chat = screen.deps.chat
        chat._injected_model = FunctionModel(hang, stream_function=hang_stream)
        chat.enter_plan()
        screen._send_chat("faz um plano longo")
        await asyncio.wait_for(started.wait(), timeout=3)
        assert chat.busy is True
        await pilot.press("escape")
        await asyncio.wait_for(_until(lambda: not chat.busy), timeout=3)
        assert chat.busy is False
        assert chat.plan.active is True


async def _until(pred, *, interval: float = 0.05) -> None:
    while not pred():
        await asyncio.sleep(interval)


async def test_q_during_busy_plan_cancels(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    cancelled = []

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.deps.chat.enter_plan()
        screen.deps.chat.busy = True
        screen.deps.chat.cancel_current = lambda: cancelled.append("cancel")  # type: ignore[method-assign]
        screen.query_one(PromptBar).disable_input()
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert cancelled == ["cancel"]
        assert screen.deps.chat.plan.active is True


async def test_q_when_plan_idle_exits(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.deps.chat.enter_plan()
        screen.action_plan_quit()
        await pilot.pause()
        assert screen.deps.chat.plan.active is False
