from pathlib import Path

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


def test_strip_file_blocks_in_display():
    msgs = [
        ModelRequest(
            parts=[
                UserPromptPart(content='veja\n<file path="a.py">\nprint(1)\n</file>')
            ]
        )
    ]
    turns = turns_from_messages(msgs)
    assert turns[0].text == "veja"
