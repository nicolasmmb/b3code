from pathlib import Path

from b3code.utils.paths import escaped_paths, safe_workspace_path


def test_local_commands_do_not_escape(tmp_path: Path):
    assert escaped_paths("pytest -q", tmp_path) == []
    assert escaped_paths("git status", tmp_path) == []
    assert escaped_paths("ls src", tmp_path) == []


def test_absolute_tmp_escapes(tmp_path: Path):
    hits = escaped_paths("ls /tmp", tmp_path)
    assert Path("/tmp").expanduser().resolve() in hits


def test_parent_escape(tmp_path: Path):
    cwd = tmp_path / "proj"
    cwd.mkdir()
    hits = escaped_paths("cat ../secret.txt", cwd)
    assert (tmp_path / "secret.txt").resolve() in hits


def test_safe_workspace_still_blocks(tmp_path: Path):
    import pytest

    with pytest.raises(ValueError):
        safe_workspace_path("../secret", tmp_path)
