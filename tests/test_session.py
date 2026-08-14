from pathlib import Path

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelRequest, UserPromptPart

from b3code.services.session import SessionStore, turns_from_messages


def test_replace_and_reload(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    msgs = [ModelRequest(parts=[UserPromptPart(content="hello")])]
    store.replace(msgs)
    assert path.exists()

    reloaded = SessionStore(path)
    assert reloaded.current_id == store.current_id
    assert len(reloaded.messages) == 1
    turns = reloaded.display_turns()
    assert turns[0].role == "user"
    assert turns[0].text == "hello"


def test_new_session_switches_active(tmp_path: Path):
    store = SessionStore(tmp_path / "s.json")
    first = store.current_id
    store.new()
    assert store.current_id != first
    assert len(store.list_sessions()) == 2


def test_messages_are_cached(tmp_path: Path):
    store = SessionStore(tmp_path / "s.json")
    msgs = [ModelRequest(parts=[UserPromptPart(content="hello")])]
    store.replace(msgs)
    first = store.messages
    second = store.messages
    assert first is second
    assert first[0].parts[0].content == "hello"


def test_atomic_replace_writes_valid_json(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.replace([ModelRequest(parts=[UserPromptPart(content="hello")])])
    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    reloaded = SessionStore(path)
    assert reloaded.messages[0].parts[0].content == "hello"
    leftovers = list(tmp_path.glob(".sessions.json.*.tmp"))
    assert leftovers == []


async def test_replace_async_persists(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    await store.replace_async([ModelRequest(parts=[UserPromptPart(content="async")])])
    reloaded = SessionStore(path)
    assert reloaded.messages[0].parts[0].content == "async"


def test_binary_content_persists_across_reload(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions.json")
    payload = [
        "o que e",
        BinaryContent(
            data=b"\x89PNG\r\n\x1a\n",
            media_type="image/png",
            identifier="casa.jpg",
        ),
    ]
    store.replace([ModelRequest(parts=[UserPromptPart(content=payload)])])
    reloaded = SessionStore(tmp_path / "sessions.json")
    turns = reloaded.display_turns()
    assert "[IMG - casa.jpg]" in turns[0].text
    content = reloaded.messages[0].parts[0].content
    assert isinstance(content, list)
    assert any(isinstance(item, BinaryContent) for item in content)


def test_strip_file_blocks_in_display():
    msgs = [
        ModelRequest(
            parts=[
                UserPromptPart(content='veja\n<file path="a.py">\nprint(1)\n</file>')
            ]
        )
    ]
    turns = turns_from_messages(msgs)
    assert "[PY - a.py]" in turns[0].text
    assert "veja" in turns[0].text
    assert "print(1)" not in turns[0].text


def test_display_binary_image_chip():
    msgs = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        "o que e",
                        BinaryContent(
                            data=b"\x89PNG\r\n\x1a\n",
                            media_type="image/png",
                            identifier="casa.jpg",
                        ),
                    ]
                )
            ]
        )
    ]
    turns = turns_from_messages(msgs)
    assert "[IMG - casa.jpg]" in turns[0].text
    assert "o que e" in turns[0].text


def test_display_binary_pdf_chip():
    msgs = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        BinaryContent(
                            data=b"%PDF-1.4\n",
                            media_type="application/pdf",
                            identifier="report.pdf",
                        )
                    ]
                )
            ]
        )
    ]
    turns = turns_from_messages(msgs)
    assert turns[0].text == "[PDF - report.pdf]"
