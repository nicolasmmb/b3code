from b3code.utils.diffview import MAX_DIFF_LINES, DiffLine, diff_texts, summary


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


def test_truncates_display_but_keeps_full_counts():
    old = ""
    new = "\n".join(f"line {i}" for i in range(MAX_DIFF_LINES + 20))
    change = diff_texts("big.py", old, new)
    assert change.added == MAX_DIFF_LINES + 20
    assert change.removed == 0
    assert change.truncated is True
    assert len(change.lines) == MAX_DIFF_LINES
