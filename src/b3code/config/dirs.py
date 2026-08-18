"""Diretório central do b3code por usuário (stdlib apenas).

Contrato por SO (replica um subconjunto pequeno e documentado do
`platformdirs`, sem importar nada externo):

- `B3CODE_HOME` setada  -> usa ela (`Path(raw).expanduser().resolve()`);
- Windows (`os.name == "nt"`) -> `%APPDATA%\b3code`; se `APPDATA` ausente,
  `%LOCALAPPDATA%\b3code`; se ambos ausentes, `~/b3code`;
- macOS (`sys.platform == "darwin"`) -> `~/Library/Application Support/b3code`;
- Linux/BSD/outros -> `$XDG_CONFIG_HOME/b3code`; se `XDG_CONFIG_HOME` ausente,
  `~/.config/b3code`.

Nenhum diretório é criado na resolução — só na escrita (`atomic_write_text`
já faz `mkdir(parents=True)`).
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import re
import sys
from pathlib import Path

_SLUG = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX = 48
_HASH_LEN = 10


def _windows() -> bool:
    return os.name == "nt"


def _macos() -> bool:
    return sys.platform == "darwin"


def b3code_home() -> Path:
    """Diretório central do b3code por usuário (ver docstring do módulo)."""
    raw = os.environ.get("B3CODE_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    if _windows():
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home()) / "b3code"
    if _macos():
        return Path.home() / "Library" / "Application Support" / "b3code"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "b3code"


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


def legacy_project_dir(cwd: Path) -> Path:
    """`.b3code` antigo no cwd do projeto (fonte da migração de 1º boot)."""
    return cwd.resolve() / ".b3code"
