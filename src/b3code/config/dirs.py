"""Diretório central do b3code por usuário (stdlib apenas).

Contrato único para todos os SOs:

- `B3CODE_HOME` setada  -> usa ela (`Path(raw).expanduser().resolve()`);
- caso contrário        -> `~/.b3code` (Linux/macOS/Windows).

Nenhum diretório é criado na resolução — só na escrita (`atomic_write_text`
já faz `mkdir(parents=True)`).
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import re
from pathlib import Path

_SLUG = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX = 48
_HASH_LEN = 10


def _windows() -> bool:
    return os.name == "nt"


def b3code_home() -> Path:
    """Diretório central do b3code por usuário (ver docstring do módulo)."""
    raw = os.environ.get("B3CODE_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".b3code"


def project_key(cwd: Path | str) -> str:
    """Chave estável do projeto: slug do nome + sha1 do path resolvido.

    Segura para filesystem em qualquer SO (sem `/`, `\\`, espaço ou acento).
    No Windows aplica `ntpath.normcase` antes do hash para não duplicar
    projetos por casing.
    """
    resolved = Path(cwd).resolve()
    name = resolved.name or "root"
    slug = _SLUG.sub("-", name.lower()).strip("-._")[:_SLUG_MAX]
    if not slug:
        slug = "root"
    # Windows: normcase evita duplicar projetos por casing do path.
    norm = ntpath.normcase(str(resolved)).encode() if _windows() else str(resolved).encode()
    digest = hashlib.sha1(norm).hexdigest()[:_HASH_LEN]
    return f"{slug}-{digest}"


def project_dir(cwd: Path | str) -> Path:
    """Estado por projeto (plan, sessões, skills do projeto, anexos)."""
    return b3code_home() / "projects" / project_key(cwd)
