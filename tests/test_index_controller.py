from pathlib import Path

from b3code.services.chat import ChatEvent
from b3code.services.files import FileIndex
from b3code.ui.index_controller import IndexController
from b3code.utils.diffview import diff_texts


def test_diff_adds_and_deletes_via_injected_index(tmp_path: Path):
    (tmp_path / "a.py").write_text("x\n")
    idx = FileIndex(tmp_path)
    idx.scan()
    listed: list[int] = []
    refreshed: list[int] = []
    ctl = IndexController(
        idx,
        on_listed=lambda: listed.append(1),
        on_refresh=lambda: refreshed.append(1),
    )
    ctl.on_event(ChatEvent(kind="diff", change=diff_texts("b.py", "", "hi\n")))
    assert "b.py" in [str(p) for p in idx.search("b")]
    assert listed == [1]
    ctl.on_event(ChatEvent(kind="diff", change=diff_texts("a.py", "x\n", "")))
    assert "a.py" not in [str(p) for p in idx.search("")]
    ctl.on_event(ChatEvent(kind="done", text="ok"))
    assert refreshed == [1]


def test_ignores_diff_without_change(tmp_path: Path):
    idx = FileIndex(tmp_path)
    idx.scan()
    ctl = IndexController(idx, on_listed=lambda: None, on_refresh=lambda: None)
    ctl.on_event(ChatEvent(kind="diff"))
    assert idx.search("") == []
