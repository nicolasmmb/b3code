"""Tipos de comando. Sem Textual e sem services — a UI e o registry compartilham isto."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Suggestion:
    value: str
    label: str
    hint: str
    kind: str  # cmd | arg | file
    consume: bool = False
    """True: aceitar este item fecha o comando (arg final ou comando sem args)."""


@dataclass
class CommandResult:
    message: str
    action: str | None = None  # quit | refresh | new
    payload: str | None = None
