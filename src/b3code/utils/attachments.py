"""Classifica drops/paste e monta chips `[TIPO - arquivo]`."""

from __future__ import annotations

import re
import shlex
import struct
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

DROP_MAX_BYTES = 10 * 1024 * 1024
ATTACH_MAX_BYTES = 10 * 1024 * 1024

_FILE_URL = re.compile(r"^file://", re.I)


class AttachKind(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    TEXT = "text"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Attachment:
    kind: AttachKind
    path: Path
    filename: str
    label: str
    media_type: str | None = None

    @property
    def token(self) -> str:
        return chip_token(self.label, self.filename)

    def with_filename(self, filename: str) -> Attachment:
        return Attachment(self.kind, self.path, filename, self.label, self.media_type)


def chip_token(label: str, filename: str) -> str:
    return f"[{label} - {filename}]"


def detect_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    return None


def png_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def is_tiny_image(data: bytes) -> bool:
    size = png_size(data)
    return size is not None and size[0] <= 1 and size[1] <= 1


def looks_like_text(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def label_for_text(name: str) -> str:
    ext = Path(name).suffix.lstrip(".").upper()
    return ext or "TXT"


def classify_bytes(data: bytes, name: str) -> tuple[AttachKind, str | None, str]:
    mime = detect_mime(data)
    if mime is not None and mime.startswith("image/"):
        if is_tiny_image(data):
            return AttachKind.UNSUPPORTED, mime, "IMG"
        return AttachKind.IMAGE, mime, "IMG"
    if mime == "application/pdf":
        return AttachKind.PDF, mime, "PDF"
    if looks_like_text(data):
        return AttachKind.TEXT, None, label_for_text(name)
    return AttachKind.UNSUPPORTED, mime, "BIN"


def classify_path(path: Path) -> Attachment | None:
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        head = path.read_bytes() if size <= 64 else path.read_bytes()[:64]
    except OSError:
        return None
    mime = detect_mime(head)
    if mime is not None and size > ATTACH_MAX_BYTES:
        return None
    try:
        sample = head if size <= 64 else path.read_bytes()[:8192]
        if mime == "image/png" and size <= ATTACH_MAX_BYTES:
            sample = path.read_bytes()[:24]
    except OSError:
        return None
    kind, media_type, label = classify_bytes(sample, path.name)
    return Attachment(kind, path.resolve(), path.name, label, media_type)


def decode_file_url(token: str) -> Path | None:
    if not _FILE_URL.match(token):
        return None
    parsed = urlparse(token)
    raw = unquote(parsed.path)
    if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1"}:
        raw = f"/{parsed.netloc}{raw}"
    if raw.startswith("//"):
        raw = raw[1:]
    return Path(raw) if raw else None


def _resolve_token(token: str, cwd: Path) -> Path | None:
    decoded = decode_file_url(token)
    candidate = decoded if decoded is not None else Path(token).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        if candidate.is_file():
            return candidate.resolve()
    except OSError:
        return None
    return None


def drop_tokens(text: str) -> list[str]:
    if not text or len(text) >= DROP_MAX_BYTES:
        return []
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return [part for part in text.split() if part]


def try_read_dropped_paths(text: str, cwd: Path) -> list[Path] | None:
    """None = não é drop. Lista (possivelmente vazia de arquivos válidos) = drop."""
    tokens = drop_tokens(text.strip())
    if not tokens:
        return None
    resolved: list[Path] = []
    for token in tokens:
        path = _resolve_token(token, cwd)
        if (
            path is None
            and not _FILE_URL.match(token)
            and not token.startswith(("/", "~"))
        ):
            return None
        if path is not None:
            resolved.append(path)
    return resolved or None


def uniquify(attachment: Attachment, existing: dict[str, Attachment]) -> Attachment:
    if attachment.token not in existing:
        return attachment
    stem = Path(attachment.filename).stem
    suffix = Path(attachment.filename).suffix
    index = 2
    while True:
        candidate = attachment.with_filename(f"{stem}-{index}{suffix}")
        if candidate.token not in existing:
            return candidate
        index += 1


def persist_bytes(cwd: Path, data: bytes, suffix: str) -> Path:
    dest_dir = cwd / ".b3code" / "attachments"
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    dest = dest_dir / f"{uuid4().hex[:8]}{ext}"
    dest.write_bytes(data)
    return dest


def mime_suffix(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime, ".bin")


def attachment_from_bytes(cwd: Path, data: bytes, filename: str) -> Attachment | None:
    if len(data) > ATTACH_MAX_BYTES:
        return None
    kind, mime, label = classify_bytes(data, filename)
    if kind not in {AttachKind.IMAGE, AttachKind.PDF} or mime is None:
        return None
    path = persist_bytes(cwd, data, mime_suffix(mime))
    return Attachment(kind, path, filename, label, mime)


def next_paste_name(existing: dict[str, Attachment], suffix: str) -> str:
    used = 0
    for item in existing.values():
        if item.filename.startswith("paste-") and item.kind == AttachKind.IMAGE:
            used += 1
    return f"paste-{used + 1}{suffix}"


def chip_span(text: str, cursor: int, tokens: list[str]) -> tuple[int, int] | None:
    for token in sorted(tokens, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(token, start)
            if index < 0:
                break
            end = index + len(token)
            extra = 1 if end < len(text) and text[end] == " " else 0
            if index < cursor <= end + extra:
                return index, end + extra
            start = index + 1
    return None


def read_clipboard_image() -> bytes | None:
    try:
        result = subprocess.run(
            ["pngpaste", "-"],
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        result = None
    if result is not None and result.returncode == 0 and detect_mime(result.stdout):
        return result.stdout
    return _clipboard_image_osascript()


def _clipboard_image_osascript() -> bytes | None:
    dest = Path(f"/tmp/b3code-clip-{uuid4().hex[:8]}.png")
    script = (
        f'set out to POSIX file "{dest}"\n'
        "try\n"
        "  set png to the clipboard as «class PNGf»\n"
        "  set fh to open for access out with write permission\n"
        "  write png to fh\n"
        "  close access fh\n"
        "on error\n"
        "  try\n"
        "    close access out\n"
        "  end try\n"
        '  return ""\n'
        "end try\n"
    )
    try:
        done = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0 or not dest.exists():
        return None
    try:
        data = dest.read_bytes()
    except OSError:
        return None
    finally:
        dest.unlink(missing_ok=True)
    return data if detect_mime(data) else None
