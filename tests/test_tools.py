from pathlib import Path

import pytest

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
        for name, tool in workspace_toolset(tmp_path, on_change=seen.append).tools.items()
    }
    assert fns["write_file"]("n.txt", "hello world") == "wrote n.txt (+1 -0)"
    assert seen and seen[0].path == "n.txt"
    assert seen[0].added == 1
    assert fns["read_file"]("n.txt") == "hello world"
    assert "n.txt" in fns["list_dir"](".")
    assert "n.txt" in fns["grep"]("hello")
