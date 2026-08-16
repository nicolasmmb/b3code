from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry

from b3code.tools.workspace import workspace_toolset
from b3code.utils.paths import safe_workspace_path


def test_safe_path_blocks_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        safe_workspace_path("../secret", tmp_path)


def test_safe_path_accepts_work_prefix(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    assert safe_workspace_path("/work/a.py", tmp_path) == (tmp_path / "a.py").resolve()


def test_read_write_list_grep(tmp_path: Path):
    seen = []
    fns = {
        name: tool.function
        for name, tool in workspace_toolset(
            tmp_path, on_change=seen.append
        ).tools.items()
    }
    assert fns["write_file"]("n.txt", "hello world") == "wrote n.txt (+1 -0)"
    assert seen and seen[0].path == "n.txt"
    assert seen[0].added == 1
    assert fns["read_file"]("n.txt") == "hello world"
    assert "n.txt" in fns["list_dir"](".")
    assert "n.txt" in fns["grep"]("hello")


def _fns(tmp_path: Path, seen=None):
    return {
        name: tool.function
        for name, tool in workspace_toolset(
            tmp_path, on_change=None if seen is None else seen.append
        ).tools.items()
    }


def test_replace_one_occurrence(tmp_path: Path):
    seen: list = []
    fns = _fns(tmp_path, seen)
    (tmp_path / "a.py").write_text("x = 1\ny = 1\n")
    out = fns["replace_in_file"]("a.py", "x = 1", "x = 2")
    assert "replaced 1" in out
    assert (tmp_path / "a.py").read_text() == "x = 2\ny = 1\n"
    assert seen and seen[-1].path == "a.py"


def test_replace_missing_and_ambiguous(tmp_path: Path):
    fns = _fns(tmp_path)
    (tmp_path / "a.py").write_text("foo\nfoo\n")
    with pytest.raises(ModelRetry, match="not found"):
        fns["replace_in_file"]("a.py", "bar", "baz")
    with pytest.raises(ModelRetry, match="2 times"):
        fns["replace_in_file"]("a.py", "foo", "qux")
    assert fns["replace_in_file"]("a.py", "foo", "qux", True).startswith("replaced 2")
    assert (tmp_path / "a.py").read_text() == "qux\nqux\n"


def test_delete_file(tmp_path: Path):
    seen: list = []
    fns = _fns(tmp_path, seen)
    (tmp_path / "gone.txt").write_text("bye")
    assert fns["delete_file"]("gone.txt") == "deleted gone.txt"
    assert not (tmp_path / "gone.txt").exists()
    assert seen
    with pytest.raises(ModelRetry, match="missing"):
        fns["delete_file"]("gone.txt")
    (tmp_path / "d").mkdir()
    with pytest.raises(ModelRetry, match="directory"):
        fns["delete_file"]("d")


def test_move_file(tmp_path: Path):
    fns = _fns(tmp_path)
    (tmp_path / "old.py").write_text("ok")
    (tmp_path / "sub").mkdir()
    out = fns["move_file"]("old.py", "sub/new.py")
    assert "moved" in out
    assert not (tmp_path / "old.py").exists()
    assert (tmp_path / "sub" / "new.py").read_text() == "ok"
    (tmp_path / "other.py").write_text("x")
    with pytest.raises(ModelRetry, match="exists"):
        fns["move_file"]("sub/new.py", "other.py")
    fns["move_file"]("sub/new.py", "other.py", True)
    assert (tmp_path / "other.py").read_text() == "ok"


def test_read_file_line_range(tmp_path: Path):
    fns = _fns(tmp_path)
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    assert fns["read_file"]("a.py", 2, 3) == "2|two\n3|three"


def test_mutate_tools_block_escape(tmp_path: Path):
    fns = _fns(tmp_path)
    (tmp_path / "a.py").write_text("x")
    with pytest.raises(ValueError):
        fns["replace_in_file"]("../secret", "a", "b")
    with pytest.raises(ValueError):
        fns["delete_file"]("../secret")
    with pytest.raises(ValueError):
        fns["move_file"]("a.py", "../secret")


def test_list_dir_omits_excluded_dirs_and_exts(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    (tmp_path / "blob.pyc").write_bytes(b"x")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "pkg.py").write_text("x")
    fns = {
        name: tool.function
        for name, tool in workspace_toolset(
            tmp_path, skip_dirs=["vendor"], skip_exts=[".pyc"]
        ).tools.items()
    }
    names = fns["list_dir"](".")
    assert "keep.py" in names
    assert "vendor/" not in names
    assert "blob.pyc" not in names


def test_grep_omits_excluded_dirs_and_exts(tmp_path: Path):
    (tmp_path / "hit.py").write_text("class Foo:\n    pass\n")
    (tmp_path / "blob.pyc").write_bytes(b"class Hidden\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "pkg.py").write_text("class Hidden\n")
    fns = {
        name: tool.function
        for name, tool in workspace_toolset(
            tmp_path, skip_dirs=["vendor"], skip_exts=[".pyc"]
        ).tools.items()
    }
    out = fns["grep"]("class")
    assert "hit.py" in out
    assert "vendor" not in out
    assert "blob.pyc" not in out


def test_read_file_explicit_path_ignores_exclusions(tmp_path: Path):
    (tmp_path / "blob.pyc").write_text("hidden text")
    fns = {
        name: tool.function
        for name, tool in workspace_toolset(tmp_path, skip_exts=[".pyc"]).tools.items()
    }
    assert fns["read_file"]("blob.pyc") == "hidden text"

