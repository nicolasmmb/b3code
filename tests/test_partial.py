import asyncio
from pathlib import Path

from pydantic_ai import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from b3code.config.schema import AppConfig
from b3code.services.chat import ChatEvent, ChatService
from b3code.services.partial import PartialTurnRecorder
from b3code.services.session import SessionStore


def _parts(model_response) -> list:
    return list(model_response.parts)


# --- unit ----------------------------------------------------------------


def test_recorder_text_and_thinking():
    rec = PartialTurnRecorder()
    rec.record(PartStartEvent(index=0, part=ThinkingPart(content="pensei ")))
    rec.record(PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta="mais")))
    rec.record(PartStartEvent(index=1, part=TextPart(content="oi ")))
    rec.record(PartDeltaEvent(index=1, delta=TextPartDelta(content_delta="mundo")))

    msgs = rec.messages([], "pergunta")
    assert isinstance(msgs[0], ModelRequest)
    assert isinstance(msgs[0].parts[0], UserPromptPart)
    assert msgs[0].parts[0].content == "pergunta"
    response = msgs[1]
    assert isinstance(response, ModelResponse)
    kinds = [type(p).__name__ for p in _parts(response)]
    assert kinds == ["ThinkingPart", "TextPart"]
    assert _parts(response)[0].content == "pensei mais"
    assert _parts(response)[1].content == "oi mundo"


def test_recorder_drops_response_with_pending_tool_call():
    rec = PartialTurnRecorder()
    rec.record(PartStartEvent(index=0, part=TextPart(content="antes ")))
    rec.record(
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="read_file", args={"path": "a.py"}, tool_call_id="c1"
            ),
            args_valid=True,
        )
    )
    # tool call nunca recebe return → resposta incompleta é descartada
    msgs = rec.messages([], "p")
    assert len(msgs) == 1  # só o UserPromptPart
    assert isinstance(msgs[0], ModelRequest)


def test_recorder_tool_call_with_return():
    rec = PartialTurnRecorder()
    rec.record(
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="read_file", args={"path": "a.py"}, tool_call_id="c1"
            ),
            args_valid=True,
        )
    )
    rec.record(
        FunctionToolResultEvent(
            part=ToolReturnPart(
                tool_name="read_file",
                content="conteudo",
                tool_call_id="c1",
            ),
            content="conteudo",
        )
    )
    rec.record(PartStartEvent(index=0, part=TextPart(content="resposta final")))

    msgs = rec.messages([], "p")
    # [UserPrompt, ModelResponse(toolcall), ModelRequest(return), ModelResponse(text)]
    assert len(msgs) == 4
    assert isinstance(msgs[1], ModelResponse)
    assert isinstance(_parts(msgs[1])[0], ToolCallPart)
    assert isinstance(msgs[2], ModelRequest)
    assert isinstance(msgs[2].parts[0], ToolReturnPart)
    assert isinstance(msgs[3], ModelResponse)
    assert isinstance(_parts(msgs[3])[0], TextPart)
    assert _parts(msgs[3])[0].content == "resposta final"


def test_recorder_keeps_prior():
    prior = [ModelResponse(parts=[TextPart(content="hist")])]
    rec = PartialTurnRecorder()
    rec.record(PartStartEvent(index=0, part=TextPart(content="novo")))
    msgs = rec.messages(prior, "p")
    assert msgs[0] is prior[0]
    assert isinstance(msgs[1], ModelRequest)
    assert isinstance(msgs[1].parts[0], UserPromptPart)
    assert msgs[1].parts[0].content == "p"


# --- integração -----------------------------------------------------------


def _service(tmp_path: Path) -> ChatService:
    cfg = AppConfig(
        gateway_api_key="test",
        gateway_api_endpoint="https://example.openai.azure.com/openai/v1/",
        gateway_api_models=["test"],
    )
    return ChatService(
        cfg, SessionStore(tmp_path / "sessions.json"), tmp_path, model=_model()
    )


def _model():
    async def stream(_messages, _info):
        yield "parcial"
        raise ConnectionError("rede caiu")

    return FunctionModel(lambda m, i: None, stream_function=stream)


async def test_partial_persisted_on_error(tmp_path: Path):
    chat = _service(tmp_path)
    events: list[ChatEvent] = []
    await chat.enqueue("faz algo", events.append)
    assert any(e.kind == "error" for e in events)
    texts = [
        str(getattr(p, "content", ""))
        for msg in chat.session.messages
        for p in getattr(msg, "parts", [])
    ]
    assert "parcial" in texts, texts
    assert any(
        "faz algo" in str(getattr(p, "content", ""))
        for msg in chat.session.messages
        for p in getattr(msg, "parts", [])
    )


async def test_cancel_does_not_persist(tmp_path: Path):
    started = asyncio.Event()

    async def stream(_messages, _info):
        started.set()
        await asyncio.sleep(30)
        yield "nunca"

    chat = ChatService(
        AppConfig(gateway_api_models=["test"]),
        SessionStore(tmp_path / "sessions.json"),
        tmp_path,
        model=FunctionModel(lambda m, i: None, stream_function=stream),
    )
    task = asyncio.create_task(chat.enqueue("hi", lambda e: None))
    await asyncio.wait_for(started.wait(), timeout=2)
    chat.cancel_current()
    await asyncio.wait_for(task, timeout=3)
    assert chat.session.messages == []
