"""Composition root. Sem framework de DI — só construtores."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from b3code.commands.registry import CommandRegistry
from b3code.config.dirs import legacy_project_dir, project_dir
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


def migrate_legacy(cwd: Path) -> None:
    """Promove o `.b3code` legado do cwd para o diretório central (1º boot).

    Copia config/plan/sessões/skills/anexos só quando o destino ainda não
    existe. Config legado inválido é ignorado (o default nasce). A pasta
    legada do projeto não é apagada — o usuário decide.
    """

    legacy = legacy_project_dir(cwd)
    project = project_dir(cwd)
    central = ConfigStore.for_global()
    legacy_config = legacy / "config.json"
    if legacy_config.exists() and not central.path.exists():
        try:
            cfg = AppConfig.model_validate_json(
                legacy_config.read_text(encoding="utf-8")
            )
            central.save(cfg)
        except Exception:
            pass
    _copy_legacy_file(legacy / "plan.md", project / "plan.md")
    _copy_legacy_file(legacy / "sessions.json", project / "sessions.json")
    for name in ("sessions", "skills", "attachments"):
        _copy_legacy_dir(legacy / name, project / name)


def _copy_legacy_file(src: Path, dest: Path) -> None:
    if src.is_file() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _copy_legacy_dir(src: Path, dest: Path) -> None:
    if src.is_dir() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)


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
        if not store.path.exists():
            migrate_legacy(cwd)
        catalog = ModelCatalog()
        cfg_svc = ConfigService(store, catalog=catalog)
        config = cfg_svc.config
        sessions = SessionStore.for_project(cwd)
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
