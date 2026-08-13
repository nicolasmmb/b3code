from b3code.utils.diffview import (
    COLLAPSE,
    EXPAND_CAP,
    DiffLine,
    diff_texts,
    hidden_count,
    summary,
    visible,
)


def test_new_file_is_all_plus():
    change = diff_texts("n.txt", "", "hello\nworld")
    assert change.path == "n.txt"
    assert change.added == 2
    assert change.removed == 0
    assert change.lines == (
        DiffLine("+", "hello", 1),
        DiffLine("+", "world", 2),
    )
    assert change.truncated is False
    assert summary(change) == "n.txt  +2 −0"


def test_edit_has_plus_minus_and_context():
    old = "def foo():\n    return 1\n\ndef bar():\n    return 0\n"
    new = "def foo():\n    return 2\n\ndef bar():\n    return 0\n"
    change = diff_texts("a.py", old, new)
    kinds = [line.kind for line in change.lines]
    assert "-" in kinds
    assert "+" in kinds
    assert any(line.text == "    return 1" for line in change.lines if line.kind == "-")
    assert any(line.text == "    return 2" for line in change.lines if line.kind == "+")
    assert all(line.number >= 1 for line in change.lines)
    assert change.added == 1
    assert change.removed == 1
    assert summary(change) == "a.py  +1 −1"


def test_keeps_full_hunk_and_slices_for_display():
    old = ""
    new = "\n".join(f"line {i}" for i in range(COLLAPSE + 20))
    change = diff_texts("big.py", old, new)
    assert change.added == COLLAPSE + 20
    assert change.removed == 0
    assert change.truncated is True
    assert len(change.lines) == COLLAPSE + 20
    assert len(visible(change, expanded=False)) == COLLAPSE
    assert hidden_count(change, expanded=False) == 20
    assert len(visible(change, expanded=True)) == COLLAPSE + 20
    assert hidden_count(change, expanded=True) == 0


def test_expand_cap_limits_visible_lines():
    new = "\n".join(f"line {i}" for i in range(EXPAND_CAP + 40))
    change = diff_texts("huge.py", "", new)
    assert change.added == EXPAND_CAP + 40
    assert change.line_count == EXPAND_CAP + 40
    assert len(change.lines) == EXPAND_CAP
    assert len(visible(change, expanded=True)) == EXPAND_CAP
    assert hidden_count(change, expanded=True) == 40
