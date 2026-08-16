import asyncio
from pathlib import Path

from pydantic_ai import BinaryContent
from pydantic_ai.models.test import TestModel

from b3code.config.schema import AppConfig
from b3code.services.chat import ChatEvent, ChatService
from b3code.services.session import SessionStore


def _service(tmp_path: Path) -> ChatService:
    cfg = AppConfig(
        gateway_api_key="test",
        gateway_api_endpoint="https://example.openai.azure.com/openai/v1/",
        gateway_api_models=["test"],
    )
    sessions = SessionStore(tmp_path / "sessions.json")
    return ChatService(cfg, sessions, tmp_path, model=TestModel())


async def test_saves_after_turn(tmp_path: Path):
    chat = _service(tmp_path)
    events: list[ChatEvent] = []
    await chat.enqueue("hi", events.append)
    assert any(e.kind == "done" for e in events)
    assert any(
        "hi" in str(getattr(part, "content", ""))
        for msg in chat.session.messages
        for part in getattr(msg, "parts", [])
    )
    assert chat.session.messages


async def test_serial_requests(tmp_path: Path):
    chat = _service(tmp_path)
    order: list[str] = []

    async def send(label: str) -> None:
        def on_event(event: ChatEvent) -> None:
            if event.kind == "done":
                order.append(label)

        await chat.enqueue(label, on_event)

    await asyncio.gather(send("one"), send("two"))
    assert set(order) == {"one", "two"}
    texts = []
    for msg in chat.session.messages:
        for part in getattr(msg, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
    assert "one" in texts
    assert "two" in texts
    assert chat.busy is False


async def test_enqueue_error_includes_traceback(tmp_path: Path):
    chat = _service(tmp_path)

    async def boom(*_args, **_kwargs):
        try:
            raise ConnectionError("dns failed")
        except ConnectionError as exc:
            raise RuntimeError("request failed") from exc

    chat._dispatch_turn = boom  # type: ignore[method-assign]
    events: list[ChatEvent] = []
    await chat.enqueue("hi", events.append)
    err = next(event for event in events if event.kind == "error")
    assert "ConnectionError" in err.text or "ConnectionError" in err.detail
    assert "dns failed" in err.detail
    assert "request failed" in err.detail
    assert "Traceback" in err.detail
    assert "RuntimeError" in err.detail


async def test_enqueue_in_plan_mode(tmp_path: Path):
    chat = _service(tmp_path)
    chat.enter_plan()
    events: list[ChatEvent] = []
    await chat.enqueue("sketch a plan", events.append)
    assert any(e.kind == "done" for e in events)
    assert chat.plan.active is True
    assert chat.busy is False
    dumped = " ".join(
        str(getattr(part, "content", ""))
        for msg in chat.session.messages
        for part in getattr(msg, "parts", [])
    )
    assert "sketch a plan" in dumped
    assert "plan mode" in dumped or "plan.md" in dumped
    assert chat._plan_history
    chat.exit_plan()
    assert chat._plan_history == []


async def test_enqueue_binary_content_round_trips(tmp_path: Path):
    chat = _service(tmp_path)
    payload = [
        "o que e",
        BinaryContent(
            data=b"\x89PNG\r\n\x1a\n", media_type="image/png", identifier="casa.jpg"
        ),
    ]
    events: list[ChatEvent] = []
    await chat.enqueue(payload, events.append)
    assert any(e.kind == "done" for e in events)
    found = False
    for msg in chat.session.messages:
        for part in getattr(msg, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, list) and any(
                isinstance(item, BinaryContent) for item in content
            ):
                found = True
    assert found
    reloaded = SessionStore(chat.session.path)
    turns = reloaded.display_turns()
    assert any("[IMG - casa.jpg]" in turn.text for turn in turns if turn.role == "user")
