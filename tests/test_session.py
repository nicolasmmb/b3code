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


def test_start_without_file_reuses_blank_session(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    session = store.start()
    assert session.id == store.current_id
    assert len(store.list_sessions()) == 1


def test_start_without_session_creates_new_per_launch(tmp_path: Path):
    path = tmp_path / "sessions.json"
    first = SessionStore(path)
    first.replace([ModelRequest(parts=[UserPromptPart(content="a")])])
    first_id = first.current_id

    second = SessionStore(path)
    session = second.start()
    assert session.id != first_id
    assert second.current_id == session.id
    assert second.messages == []


def test_start_with_id_resumes_session(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.replace([ModelRequest(parts=[UserPromptPart(content="hello")])])
    target = store.current_id

    resumed = SessionStore(path)
    session = resumed.start(target)
    assert session.id == target
    assert len(resumed.messages) == 1
    assert resumed.messages[0].parts[0].content == "hello"


def test_start_with_empty_id_creates_new(tmp_path: Path):
    path = tmp_path / "sessions.json"
    first = SessionStore(path)
    first.replace([ModelRequest(parts=[UserPromptPart(content="a")])])
    first_id = first.current_id

    second = SessionStore(path)
    session = second.start("")
    assert session.id != first_id


def test_start_with_unknown_id_raises(tmp_path: Path):
    store = SessionStore(tmp_path / "s.json")
    try:
        store.start("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown session id")


def test_draft_persists_across_reload(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.set_draft("refactor the parser")
    assert store.draft == "refactor the parser"

    reloaded = SessionStore(path)
    assert reloaded.current_id == store.current_id
    assert reloaded.draft == "refactor the parser"


def test_draft_is_per_session(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    first_id = store.current_id
    store.set_draft("draft A")

    other = store.new()
    assert other.id != first_id
    assert store.current_id == other.id
    assert store.draft == ""

    store.set_draft("draft B")
    store.activate(first_id)
    assert store.draft == "draft A"


def test_index_has_session_metadata_only(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.replace([ModelRequest(parts=[UserPromptPart(content="hello")])])
    store.set_draft("pending text")
    raw = path.read_text(encoding="utf-8")
    assert "message_count" in raw
    assert "draft" in raw
    assert "created_at" in raw
    assert "hello" not in raw  # mensagens vivem no blob, não no índice


def test_two_terminals_do_not_clobber_each_other(tmp_path: Path):
    path = tmp_path / "sessions.json"
    terminal_a = SessionStore(path)
    terminal_b = SessionStore(path)
    session_a = terminal_a.start()
    session_b = terminal_b.start()
    assert session_a.id != session_b.id

    terminal_a.replace([ModelRequest(parts=[UserPromptPart(content="msg de A")])])
    terminal_b.replace([ModelRequest(parts=[UserPromptPart(content="msg de B")])])

    reloaded = SessionStore(path)
    assert len(reloaded.list_sessions()) >= 2
    blob_a = tmp_path / "sessions" / f"{session_a.id}.json"
    blob_b = tmp_path / "sessions" / f"{session_b.id}.json"
    assert blob_a.exists()
    assert blob_b.exists()

    via_a = SessionStore(path)
    via_a.start(session_a.id)
    assert len(via_a.messages) == 1
    assert via_a.messages[0].parts[0].content == "msg de A"

    via_b = SessionStore(path)
    via_b.start(session_b.id)
    assert len(via_b.messages) == 1
    assert via_b.messages[0].parts[0].content == "msg de B"
