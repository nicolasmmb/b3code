import struct
import zlib
from pathlib import Path

from pydantic_ai import BinaryContent

from b3code.services.files import FileIndex
from b3code.utils.attachments import (
    ATTACH_MAX_BYTES,
    AttachKind,
    Attachment,
    chip_span,
    classify_bytes,
    classify_path,
    detect_mime,
    persist_bytes,
    try_read_dropped_paths,
    uniquify,
)
from b3code.utils.prompt import build_user_content, chip_token


def make_png(
    width: int, height: int, rgb: tuple[int, int, int] = (80, 80, 80)
) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_detect_mime_by_magic():
    assert detect_mime(make_png(8, 8)).startswith("image/png")
    assert detect_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_mime(b"GIF89a....") == "image/gif"
    assert detect_mime(b"RIFF\x00\x00\x00\x00WEBP....") == "image/webp"
    assert detect_mime(b"%PDF-1.4\n") == "application/pdf"


def test_classify_each_kind(tmp_path: Path):
    cases = [
        (
            "casa.jpg",
            b"\xff\xd8\xff" + b"x" * 20,
            AttachKind.IMAGE,
            "image/jpeg",
            "IMG",
        ),
        ("shot.png", make_png(8, 8), AttachKind.IMAGE, "image/png", "IMG"),
        ("anim.gif", b"GIF89a" + b"x" * 20, AttachKind.IMAGE, "image/gif", "IMG"),
        (
            "icon.webp",
            b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 8,
            AttachKind.IMAGE,
            "image/webp",
            "IMG",
        ),
        ("report.pdf", b"%PDF-1.4\n%%EOF\n", AttachKind.PDF, "application/pdf", "PDF"),
        ("app.py", b"print(1)\n", AttachKind.TEXT, None, "PY"),
        ("README.md", b"# hi\n", AttachKind.TEXT, None, "MD"),
        ("notes.txt", b"hello\n", AttachKind.TEXT, None, "TXT"),
        ("data.json", b'{"a":1}\n', AttachKind.TEXT, None, "JSON"),
        ("blob.bin", b"\x00\x01\x02\xff", AttachKind.UNSUPPORTED, None, "BIN"),
    ]
    for name, data, kind, mime, label in cases:
        got_kind, got_mime, got_label = classify_bytes(data, name)
        assert got_kind == kind, name
        assert got_mime == mime, name
        assert got_label == label, name
        path = _write(tmp_path / name, data)
        item = classify_path(path)
        assert item is not None, name
        assert item.kind == kind, name
        assert item.token == chip_token(label, name)


def test_tiny_png_is_unsupported(tmp_path: Path):
    path = _write(tmp_path / "dot.png", make_png(1, 1))
    item = classify_path(path)
    assert item is not None
    assert item.kind == AttachKind.UNSUPPORTED


def test_magic_overrides_extension(tmp_path: Path):
    path = _write(tmp_path / "shot.png", b"%PDF-1.4\n%%EOF\n")
    item = classify_path(path)
    assert item is not None
    assert item.kind == AttachKind.PDF
    assert item.token == "[PDF - shot.png]"


def test_missing_path_and_dir(tmp_path: Path):
    assert classify_path(tmp_path / "missing.jpg") is None
    assert classify_path(tmp_path) is None


def test_drop_file_url_and_percent_space(tmp_path: Path):
    folder = tmp_path / "My Documents"
    folder.mkdir()
    file = _write(folder / "readme report.md", b"x\n")
    encoded = str(file).replace(" ", "%20")
    got = try_read_dropped_paths(f"file://{encoded}", tmp_path)
    assert got == [file.resolve()]


def test_drop_quoted_and_relative(tmp_path: Path):
    file = _write(tmp_path / "app.py", b"print(1)\n")
    assert try_read_dropped_paths(f'"{file}"', tmp_path) == [file.resolve()]
    assert try_read_dropped_paths("app.py", tmp_path) == [file.resolve()]


def test_drop_unquoted_path_with_spaces(tmp_path: Path):
    folder = tmp_path / "My Documents"
    folder.mkdir()
    file = _write(folder / "Captura de Tela.png", make_png(8, 8))
    assert try_read_dropped_paths(str(file), tmp_path) == [file.resolve()]
    assert try_read_dropped_paths(f"{file} ", tmp_path) == [file.resolve()]
    escaped = str(file).replace(" ", r"\ ")
    assert try_read_dropped_paths(escaped, tmp_path) == [file.resolve()]


def test_drop_rejects_prose_with_filename(tmp_path: Path):
    _write(tmp_path / "app.py", b"print(1)\n")
    assert try_read_dropped_paths("please see app.py thanks", tmp_path) is None


def test_drop_mixed_image_and_text(tmp_path: Path):
    png = _write(tmp_path / "casa.jpg", b"\xff\xd8\xff" + b"x" * 20)
    txt = _write(tmp_path / "notes.txt", b"hi\n")
    payload = f"file://{png}\nfile://{txt}"
    got = try_read_dropped_paths(payload, tmp_path)
    assert got == [png.resolve(), txt.resolve()]


def test_oversized_binary_rejected(tmp_path: Path):
    path = tmp_path / "huge.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (ATTACH_MAX_BYTES + 10))
    assert classify_path(path) is None


def test_persist_bytes(tmp_path: Path):
    dest = persist_bytes(tmp_path, make_png(8, 8), ".png")
    assert dest.is_relative_to(tmp_path / ".b3code" / "attachments")
    assert dest.suffix == ".png"
    assert dest.read_bytes().startswith(b"\x89PNG")


def test_chip_span_includes_trailing_space():
    token = "[IMG - casa.jpg]"
    text = f"{token} "
    assert chip_span(text, len(text), [token]) == (0, len(text))
    assert chip_span(text, len(token), [token]) == (0, len(text))
    assert chip_span("hello", 5, [token]) is None


def test_uniquify_duplicate_names():
    first = Attachment(
        AttachKind.IMAGE, Path("/a/casa.jpg"), "casa.jpg", "IMG", "image/jpeg"
    )
    second = Attachment(
        AttachKind.IMAGE, Path("/b/casa.jpg"), "casa.jpg", "IMG", "image/jpeg"
    )
    existing = {first.token: first}
    unique = uniquify(second, existing)
    assert unique.token == "[IMG - casa-2.jpg]"


def test_build_user_content_image(tmp_path: Path):
    png = _write(tmp_path / "casa.jpg", make_png(8, 8))
    item = classify_path(png)
    assert item is not None
    out = build_user_content(
        f"o que e {item.token}",
        tmp_path,
        FileIndex(tmp_path).read,
        {item.token: item},
    )
    assert isinstance(out, list)
    assert out[0] == "o que e"
    assert isinstance(out[1], BinaryContent)
    assert out[1].media_type == "image/png"
    assert out[1].identifier == "casa.jpg"


def test_build_user_content_pdf(tmp_path: Path):
    pdf = _write(tmp_path / "report.pdf", b"%PDF-1.4\n%%EOF\n")
    item = classify_path(pdf)
    assert item is not None
    out = build_user_content(
        item.token, tmp_path, FileIndex(tmp_path).read, {item.token: item}
    )
    assert isinstance(out, list)
    assert isinstance(out[0], BinaryContent)
    assert out[0].media_type == "application/pdf"


def test_build_user_content_text_file(tmp_path: Path):
    py = _write(tmp_path / "app.py", b"print(1)\n")
    item = classify_path(py)
    assert item is not None
    out = build_user_content(
        f"explica {item.token}",
        tmp_path,
        FileIndex(tmp_path).read,
        {item.token: item},
    )
    assert isinstance(out, str)
    assert '<file path="app.py">' in out
    assert "print(1)" in out
    assert "BinaryContent" not in type(out).__name__


def test_build_user_content_mixed(tmp_path: Path):
    png = _write(tmp_path / "a.png", make_png(8, 8))
    py = _write(tmp_path / "a.py", b"print(1)\n")
    img = classify_path(png)
    text = classify_path(py)
    assert img is not None and text is not None
    prompt = f"{img.token} olha {text.token}"
    out = build_user_content(
        prompt,
        tmp_path,
        FileIndex(tmp_path).read,
        {img.token: img, text.token: text},
    )
    assert isinstance(out, list)
    assert any(isinstance(part, BinaryContent) for part in out)
    joined = " ".join(part if isinstance(part, str) else "" for part in out)
    assert '<file path="a.py">' in joined


def test_at_image_becomes_binary(tmp_path: Path):
    _write(tmp_path / "shot.png", make_png(8, 8))
    out = build_user_content("veja @shot.png", tmp_path, FileIndex(tmp_path).read, {})
    assert isinstance(out, list)
    assert isinstance(out[1], BinaryContent)
    assert out[1].media_type == "image/png"


def test_at_python_stays_file_block(tmp_path: Path):
    _write(tmp_path / "app.py", b"print(1)\n")
    out = build_user_content("explica @app.py", tmp_path, FileIndex(tmp_path).read, {})
    assert isinstance(out, str)
    assert '<file path="app.py">' in out
