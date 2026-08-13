from dataclasses import dataclass

from b3code.commands.builtin.help import build_help
from b3code.commands.builtin.model import build_gateway, build_model
from b3code.commands.builtin.multiline import build_multiline
from b3code.commands.builtin.plan import build_plan, build_view_plan
from b3code.commands.builtin.session import (
    build_exit,
    build_new,
    build_quit,
    build_resume,
)
from b3code.commands.registry import Command
from b3code.config.service import ConfigService
from b3code.services.catalog import ModelCatalog
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore


@dataclass
class CommandServices:
    config_service: ConfigService
    sessions: SessionStore
    chat: ChatService
    catalog: ModelCatalog


def build_all(services: CommandServices) -> list[Command]:
    commands: list[Command] = []
    commands.append(build_help(commands))
    commands.extend(
        [
            build_new(services.sessions),
            build_resume(services.sessions),
            build_quit(),
            build_exit(),
            build_model(services.config_service, services.catalog, services.chat),
            build_gateway(services.config_service, services.chat),
            build_multiline(services.config_service),
            build_plan(services.chat),
            build_view_plan(services.chat),
        ]
    )
    return commands
