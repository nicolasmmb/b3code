from b3code.ui.stream import TextBuffer


def test_push_schedules_once():
    buf = TextBuffer()
    assert buf.push("one") is True
    assert buf.push("two") is False
    assert buf.push("three") is False
    assert buf.pending == ["one", "two", "three"]


def test_drain_clears_and_allows_reschedule():
    buf = TextBuffer()
    buf.push("a")
    buf.push("b")
    assert buf.drain() == "ab"
    assert buf.pending == []
    assert buf.scheduled is False
    assert buf.push("c") is True


def test_reset():
    buf = TextBuffer()
    buf.push("x")
    buf.reset()
    assert buf.pending == []
    assert buf.scheduled is False
