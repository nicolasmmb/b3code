from dataclasses import dataclass

from b3code.commands.builtin.help import build_help
from b3code.commands.builtin.mcp import build_mcp
from b3code.commands.builtin.model import build_gateway, build_model
from b3code.commands.builtin.multiline import build_multiline
from b3code.commands.builtin.plan import build_plan, build_view_plan
from b3code.commands.builtin.session import (
    build_exit,
    build_new,
    build_quit,
    build_resume,
)
from b3code.commands.builtin.skills import build_skill_run, build_skills_command
from b3code.commands.builtin.theme import build_theme
from b3code.commands.builtin.thinking import build_thinking
from b3code.commands.registry import Command
from b3code.config.service import ConfigService
from b3code.services.catalog import ModelCatalog
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore
from b3code.services.skills import SkillIndex


@dataclass
class CommandServices:
    config_service: ConfigService
    sessions: SessionStore
    chat: ChatService
    catalog: ModelCatalog
    skills: SkillIndex | None = None


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
            build_thinking(services.config_service, services.chat),
            build_multiline(services.config_service),
            build_theme(services.config_service),
            build_mcp(services.config_service, services.chat),
            build_plan(services.chat),
            build_view_plan(services.chat),
        ]
    )
    if services.skills is None:
        services.skills = SkillIndex(
            services.chat.cwd, services.config_service.config.skills
        )
    commands.append(build_skill_run(services.skills))
    commands.append(build_skills_command(services.skills))
    return commands
