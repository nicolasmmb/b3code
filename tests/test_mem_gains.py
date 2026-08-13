"""Contratos DEPOIS das melhorias. Falham no código antigo; passam no novo.

Os números de `scripts/mem_hotspots.py` (mem-before vs mem-after) medem o ganho.
Aqui afirmamos os tetos: truncar, não indexar junk, não guardar diff/args inteiros.
"""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)

from b3code.services.files import FileIndex
from b3code.services.session import SessionStore, turns_from_messages
from b3code.tools.workspace import workspace_toolset
from b3code.ui.chat_view import visible_turns
from b3code.utils.diffview import EXPAND_CAP, diff_texts, hidden_count, visible
from b3code.utils.prompt import ATTACH_CHAR_LIMIT, expand_attachments


def test_expand_small_file_unchanged(tmp_path: Path):
    (tmp_path / "a.py").write_text("print(1)")
    out = expand_attachments("explica @a.py", tmp_path, FileIndex(tmp_path).read)
    assert '<file path="a.py">' in out
    assert "print(1)" in out
    assert "...[truncated]" not in out


def test_expand_large_file_is_truncated(tmp_path: Path):
    body = "x" * (ATTACH_CHAR_LIMIT + 40_000)
    (tmp_path / "big.txt").write_text(body)
    out = expand_attachments("veja @big.txt", tmp_path, FileIndex(tmp_path).read)
    assert "...[truncated]" in out
    assert body not in out
    assert len(out) < len(body)


def test_index_skips_target_dir(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    junk = tmp_path / "target"
    junk.mkdir()
    (junk / "out.o").write_text("no")
    idx = FileIndex(tmp_path)
    idx.scan()
    names = [str(p) for p in idx.search("", limit=1000)]
    assert "keep.py" in names
    assert not any(n == "target" or n.startswith("target/") for n in names)


def test_grep_skips_nul_binary(tmp_path: Path):
    (tmp_path / "hit.py").write_text("class Foo:\n    pass\n")
    (tmp_path / "blob.bin").write_bytes(b"class Hidden\x00zzz")
    fns = {
        name: tool.function for name, tool in workspace_toolset(tmp_path).tools.items()
    }
    out = fns["grep"]("class")
    assert "hit.py" in out
    assert "blob.bin" not in out


def test_diff_stores_at_most_expand_cap():
    new = "\n".join(f"line {i}" for i in range(EXPAND_CAP + 40))
    change = diff_texts("huge.py", "", new)
    assert change.added == EXPAND_CAP + 40
    assert len(change.lines) == EXPAND_CAP
    assert change.line_count == EXPAND_CAP + 40
    assert len(visible(change, expanded=True)) == EXPAND_CAP
    assert hidden_count(change, expanded=True) == 40


def test_tool_display_turn_drops_full_args():
    huge = "payload " * 5_000
    msgs = [
        ModelResponse(parts=[ToolCallPart(tool_name="read_file", args={"path": huge})])
    ]
    turns = turns_from_messages(msgs)
    assert turns[0].role == "tool"
    assert turns[0].tool == "read_file"
    assert huge not in turns[0].text
    assert turns[0].detail


def test_visible_turns_windows_old_history():
    turns = [
        turns_from_messages([ModelRequest(parts=[UserPromptPart(content=f"t{i}")])])[0]
        for i in range(120)
    ]
    hidden, shown = visible_turns(turns, window=100)
    assert hidden == 20
    assert len(shown) == 100
    assert shown[0].text == "t20"
    assert shown[-1].text == "t119"


def test_session_index_and_per_id_files(tmp_path: Path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.replace([ModelRequest(parts=[UserPromptPart(content="alpha")])])
    sid_a = store.current_id
    store.new()
    store.replace([ModelRequest(parts=[UserPromptPart(content="beta")])])
    sid_b = store.current_id

    reloaded = SessionStore(path)
    assert reloaded.current_id == sid_b
    assert "beta" in reloaded.messages[0].parts[0].content
    index = path.read_text(encoding="utf-8")
    assert "alpha" not in index
    assert "beta" not in index
    assert (tmp_path / "sessions" / f"{sid_a}.json").exists()
    assert (tmp_path / "sessions" / f"{sid_b}.json").exists()
    reloaded.activate(sid_a)
    assert "alpha" in reloaded.messages[0].parts[0].content
    ids = {item.id for item in reloaded.list_sessions()}
    assert {sid_a, sid_b} <= ids


def test_recorded_hotspots_show_gains():
    """Compara `.b3code/mem-before.txt` e `mem-after.txt` quando os dois existem."""
    root = Path(__file__).resolve().parents[1] / ".b3code"
    before_path = root / "mem-before.txt"
    after_path = root / "mem-after.txt"
    if not before_path.exists() or not after_path.exists():
        pytest.skip("rode scripts/mem_hotspots.py --out mem-before/after primeiro")
    before = {row["label"]: row for row in json.loads(before_path.read_text())["steps"]}
    after = {row["label"]: row for row in json.loads(after_path.read_text())["steps"]}
    assert (
        after["index_scan"]["indexed_target"] < before["index_scan"]["indexed_target"]
    )
    assert after["expand_120k"]["expand_chars"] < before["expand_120k"]["expand_chars"]
    assert after["expand_120k"]["truncated"] is True
    assert (
        after["session_40_turns"]["session_json_bytes"]
        < before["session_40_turns"]["session_json_bytes"]
    )
    assert after["session_40_turns"]["display_tool_text_chars"] == 0
    assert after["session_40_turns"]["split_dir"] is True
    assert after["grep_class"]["grep_hit_bin"] is False
    assert (
        after["diff_2k"]["diff_stored_lines"] < before["diff_2k"]["diff_stored_lines"]
    )
    assert after["diff_2k"]["diff_added"] == before["diff_2k"]["diff_added"]
