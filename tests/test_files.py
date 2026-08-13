from pathlib import Path

from b3code.commands.apply import apply_suggestion
from b3code.commands.types import Suggestion
from b3code.services.files import FileIndex
from b3code.utils.prompt import expand_attachments


def test_constructor_does_not_scan(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path)
    assert idx.search("") == []
    idx.scan()
    assert [str(p) for p in idx.search("")] == ["a.py"]


def test_search_respects_gitignore(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    (tmp_path / "skip.log").write_text("no")
    (tmp_path / ".gitignore").write_text("*.log\n")
    idx = FileIndex(tmp_path)
    idx.scan()
    names = [str(p) for p in idx.search("")]
    assert "keep.py" in names
    assert "skip.log" not in names


def test_scan_prunes_skip_dirs(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    junk = tmp_path / "node_modules"
    junk.mkdir()
    (junk / "pkg.js").write_text("no")
    idx = FileIndex(tmp_path)
    idx.scan()
    names = [str(p) for p in idx.search("")]
    assert "keep.py" in names
    assert not any("node_modules" in n for n in names)


def test_expand_attachments(tmp_path: Path):
    (tmp_path / "a.py").write_text("print(1)")
    idx = FileIndex(tmp_path)
    out = expand_attachments("explica @a.py", tmp_path, idx.read)
    assert '<file path="a.py">' in out
    assert "print(1)" in out


def test_apply_file_suggestion():
    item = Suggestion(value="app.py", label="app.py", hint="file", kind="file")
    text, cursor = apply_suggestion("veja @ap", 8, item)
    assert text == "veja @app.py"
    assert cursor == len(text)


def test_apply_cmd_suggestion():
    item = Suggestion(
        value="/help", label="/help", hint="list", kind="cmd", consume=True
    )
    text, _ = apply_suggestion("/he", 3, item)
    assert text == "/help"
