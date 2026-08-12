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


def test_strip_file_blocks_in_display():
    msgs = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content='veja\n<file path="a.py">\nprint(1)\n</file>'
                )
            ]
        )
    ]
    turns = turns_from_messages(msgs)
    assert turns[0].text == "veja"
