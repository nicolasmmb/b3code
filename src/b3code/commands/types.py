"""Tipos de comando. Sem Textual e sem services — a UI e o registry compartilham isto."""

from __future__ import annotations

from dataclasses import dataclass

from b3code.commands.effects import CommandEffect


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
    effect: CommandEffect | None = None
