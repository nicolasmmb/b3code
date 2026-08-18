"""Composition root. Sem framework de DI — só construtores."""

from dataclasses import dataclass
from pathlib import Path

from b3code.commands.registry import CommandRegistry
from b3code.config.schema import AppConfig
from b3code.config.service import ConfigService
from b3code.config.store import ConfigStore
from b3code.services.catalog import ModelCatalog
from b3code.services.chat import ChatService
from b3code.services.files import FileIndex
from b3code.services.permission import PermissionGate
from b3code.services.session import SessionStore
from b3code.services.skills import SkillIndex
from b3code.ui.deps import ScreenDeps


@dataclass
class AppContainer:
    config: AppConfig
    config_store: ConfigStore
    config_service: ConfigService
    session_store: SessionStore
    file_index: FileIndex
    commands: CommandRegistry
    chat: ChatService
    cwd: Path

    @classmethod
    def build(cls, cwd: Path | None = None) -> "AppContainer":
        cwd = (cwd or Path.cwd()).resolve()
        store = ConfigStore.for_global()
        catalog = ModelCatalog()
        cfg_svc = ConfigService(store, catalog=catalog)
        config = cfg_svc.config
        sessions = SessionStore.for_global()
        files = FileIndex(
            cwd,
            skip_dirs=config.exclude_directories,
            skip_exts=config.exclude_extensions,
            cap=config.file_index_cap,
            refresh_seconds=config.file_index_refresh_seconds,
        )
        gate = PermissionGate(cfg_svc, cwd)
        skills = SkillIndex(cwd, config.skills)
        chat = ChatService(
            config=config, session=sessions, cwd=cwd, gate=gate, skills=skills
        )
        commands = CommandRegistry.build(
            store,
            config,
            sessions,
            chat,
            catalog=catalog,
            config_service=cfg_svc,
            skills=skills,
        )
        return cls(config, store, cfg_svc, sessions, files, commands, chat, cwd)

    def screen_deps(self) -> ScreenDeps:
        return ScreenDeps(
            cwd=self.cwd,
            config=self.config,
            config_service=self.config_service,
            sessions=self.session_store,
            commands=self.commands,
            chat=self.chat,
            files=self.file_index,
            skills=self.chat.skills,
        )
