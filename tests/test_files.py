import asyncio
import inspect
from pathlib import Path

import pytest

from b3code.commands.apply import apply_suggestion
from b3code.commands.types import Suggestion
from b3code.config.schema import DEFAULT_EXCLUDE_DIRECTORIES
from b3code.services.files import FileIndex
from b3code.utils.prompt import current_token, expand_attachments


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
    idx = FileIndex(tmp_path, skip_dirs=DEFAULT_EXCLUDE_DIRECTORIES)
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


def test_read_rejects_binary_image(tmp_path: Path):
    from test_attachments import make_png

    (tmp_path / "shot.png").write_bytes(make_png(8, 8))
    with pytest.raises(ValueError, match="not a text file"):
        FileIndex(tmp_path).read("shot.png")


def test_expand_attachments_truncates_large_file(tmp_path: Path):
    from b3code.utils.prompt import ATTACH_CHAR_LIMIT

    (tmp_path / "big.txt").write_text("z" * (ATTACH_CHAR_LIMIT + 50))
    out = expand_attachments("veja @big.txt", tmp_path, FileIndex(tmp_path).read)
    assert "...[truncated]" in out
    assert "z" * (ATTACH_CHAR_LIMIT + 50) not in out


def test_current_token_splits_on_newline():
    text = "linha 1\n@src/app.py"
    start, end, token = current_token(text, len(text))
    assert token == "@src/app.py"
    assert text[start:end] == token


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


def test_add_path_is_searchable(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path)
    idx.scan()
    idx.add_path("b.py")
    assert "b.py" in [str(p) for p in idx.search("b")]


def test_add_path_idempotent_and_skips_junk(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path, skip_dirs=DEFAULT_EXCLUDE_DIRECTORIES)
    idx.scan()
    idx.add_path("a.py")
    idx.add_path("node_modules/pkg.js")
    names = [str(p) for p in idx.search("", limit=100)]
    assert names.count("a.py") == 1
    assert not any("node_modules" in n for n in names)


def test_remove_path_missing_is_noop(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path)
    idx.scan()
    idx.remove_path("missing.py")
    assert [str(p) for p in idx.search("")] == ["a.py"]
    idx.remove_path("a.py")
    assert idx.search("") == []


def test_mutate_before_scan_is_ignored(tmp_path: Path):
    idx = FileIndex(tmp_path)
    idx.add_path("ghost.py")
    idx.remove_path("ghost.py")
    assert idx.search("") == []


def test_scan_omits_excluded_dir(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    junk = tmp_path / "vendor"
    junk.mkdir()
    (junk / "pkg.py").write_text("no")
    idx = FileIndex(tmp_path, skip_dirs=["vendor"])
    idx.scan()
    names = [str(p) for p in idx.search("")]
    assert "keep.py" in names
    assert not any("vendor" in n for n in names)


def test_scan_omits_excluded_extension(tmp_path: Path):
    (tmp_path / "keep.py").write_text("ok")
    (tmp_path / "blob.pyc").write_bytes(b"no")
    idx = FileIndex(tmp_path, skip_exts=[".pyc"])
    idx.scan()
    names = [str(p) for p in idx.search("")]
    assert "keep.py" in names
    assert "blob.pyc" not in names


def test_refresh_is_coroutine():
    assert inspect.iscoroutinefunction(FileIndex.refresh)
    assert inspect.iscoroutinefunction(FileIndex.search_async)


async def test_search_async_skips_scan_inside_ttl(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path)
    idx.scan()
    scanned_at = idx._scanned_at
    (tmp_path / "late.py").write_text("x")
    hits = await idx.search_async("late")
    assert "late.py" not in [str(p) for p in hits]
    assert idx._scanned_at == scanned_at


async def test_search_async_sees_disk_after_ttl(tmp_path: Path):
    (tmp_path / "a.py").write_text("ok")
    idx = FileIndex(tmp_path)
    idx.scan()
    (tmp_path / "late.py").write_text("x")
    hits = await idx.search_async("late", max_age=0)
    assert "late.py" in [str(p) for p in hits]


async def test_refresh_does_not_block_loop(tmp_path: Path):
    for i in range(80):
        (tmp_path / f"f{i:03d}.txt").write_text("x")
    idx = FileIndex(tmp_path)
    ticks = 0

    async def beat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0)
            ticks += 1

    task = asyncio.create_task(beat())
    await asyncio.sleep(0)
    await idx.refresh()
    task.cancel()
    assert ticks >= 1
    assert len(idx.search("", limit=100)) == 80
