from pathlib import Path

from b3code.services.files import FileIndex
from b3code.utils.prompt import apply_suggestion, expand_attachments


def test_search_respects_gitignore(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    (tmp_path / "skip.log").write_text("no")
    (tmp_path / ".gitignore").write_text("*.log\n")
    idx = FileIndex(tmp_path)
    names = [str(p) for p in idx.search("")]
    assert "keep.py" in names
    assert "skip.log" not in names


def test_expand_attachments(tmp_path: Path):
    (tmp_path / "a.py").write_text("print(1)")
    idx = FileIndex(tmp_path)
    out = expand_attachments("explica @a.py", tmp_path, idx.read)
    assert '<file path="a.py">' in out
    assert "print(1)" in out


def test_apply_file_suggestion():
    text, cursor = apply_suggestion("veja @ap", 8, "app.py", "file")
    assert text == "veja @app.py"
    assert cursor == len(text)


def test_apply_cmd_suggestion():
    text, _ = apply_suggestion("/he", 3, "/help", "cmd")
    assert text == "/help "
