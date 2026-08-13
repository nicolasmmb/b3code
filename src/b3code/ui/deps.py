"""Dependências concretas da tela. Sem Protocol — tipos reais."""

from dataclasses import dataclass
from pathlib import Path

from b3code.commands.registry import CommandRegistry
from b3code.config.schema import AppConfig
from b3code.config.service import ConfigService
from b3code.services.chat import ChatService
from b3code.services.files import FileIndex
from b3code.services.session import SessionStore


@dataclass(frozen=True)
class ScreenDeps:
    cwd: Path
    config: AppConfig
    config_service: ConfigService
    sessions: SessionStore
    commands: CommandRegistry
    chat: ChatService
    files: FileIndex
