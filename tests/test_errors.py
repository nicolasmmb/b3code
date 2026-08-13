from b3code.utils.errors import error_detail, error_summary, format_error, root_cause


def test_format_error_keeps_cause_and_traceback():
    try:
        try:
            raise ConnectionError("dns failed")
        except ConnectionError as exc:
            raise RuntimeError("request failed") from exc
    except RuntimeError as wrapped:
        summary, detail = format_error(wrapped)

    assert summary.startswith("ConnectionError:")
    assert "dns failed" in summary
    assert "Traceback" in detail
    assert "ConnectionError" in detail
    assert "dns failed" in detail
    assert "RuntimeError" in detail
    assert "request failed" in detail
    assert "The above exception was the direct cause" in detail


def test_root_cause_follows_cause_chain():
    inner = ValueError("leaf")
    mid = RuntimeError("mid")
    mid.__cause__ = inner
    outer = OSError("top")
    outer.__cause__ = mid
    assert root_cause(outer) is inner


def test_error_summary_truncates_long_message():
    long = "x" * 400
    summary = error_summary(RuntimeError(long))
    assert summary.startswith("RuntimeError:")
    assert summary.endswith("…")
    assert len(summary) < 200


def test_error_detail_ends_with_newline():
    try:
        raise TimeoutError("late")
    except TimeoutError as exc:
        detail = error_detail(exc)
    assert detail.endswith("\n")
    assert "TimeoutError" in detail
    assert "late" in detail
