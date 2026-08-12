"""Composition root. Sem framework de DI — só construtores."""

from dataclasses import dataclass
from pathlib import Path

from b3code.commands.registry import CommandRegistry
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.files import FileIndex
from b3code.services.session import SessionStore


@dataclass
class AppContainer:
    config: AppConfig
    config_store: ConfigStore
    session_store: SessionStore
    file_index: FileIndex
    commands: CommandRegistry
    chat: ChatService
    cwd: Path

    @classmethod
    def build(cls, cwd: Path | None = None) -> "AppContainer":
        cwd = (cwd or Path.cwd()).resolve()
        store = ConfigStore.for_cwd(cwd)
        config = store.load()
        sessions = SessionStore.for_cwd(cwd)
        files = FileIndex(cwd)
        chat = ChatService(config=config, session=sessions, cwd=cwd)
        commands = CommandRegistry.build(store, config, sessions, chat)
        return cls(config, store, sessions, files, commands, chat, cwd)
