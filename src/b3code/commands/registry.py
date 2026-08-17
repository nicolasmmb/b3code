"""Comandos `/` com subcomandos. Nunca vão para o LLM.

`complete()` é genérico: cada Command traz o próprio completer.
A UI não conhece model/resume/gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from b3code.commands.parse import slash_tokens
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore
from b3code.services.skills import SkillIndex


@dataclass
class Command:
    name: str
    help: str
    handler: Callable[..., CommandResult] | None = None
    completer: Callable[[str], list[Suggestion]] | None = None
    children: dict[str, Command] = field(default_factory=dict)


class CommandRegistry:
    def __init__(
        self,
        roots: dict[str, Command],
        config: AppConfig,
        skills: SkillIndex | None = None,
    ) -> None:
        self.roots = roots
        self.config = config
        self.skills = skills
        self._skill_names: set[str] = set()

    @classmethod
    def build(
        cls,
        store: ConfigStore,
        config: AppConfig,
        sessions: SessionStore,
        chat: ChatService,
        catalog=None,
        config_service=None,
        skills: SkillIndex | None = None,
    ) -> CommandRegistry:
        from b3code.commands.builtin import CommandServices, build_all
        from b3code.config.service import ConfigService
        from b3code.services.catalog import ModelCatalog

        cfg_svc = config_service or ConfigService(store, config)
        index = skills or SkillIndex(chat.cwd, cfg_svc.config.skills)
        services = CommandServices(
            config_service=cfg_svc,
            sessions=sessions,
            chat=chat,
            catalog=catalog or ModelCatalog(),
            skills=index,
        )
        roots = {cmd.name: cmd for cmd in build_all(services)}
        registry = cls(roots, cfg_svc.config, skills=index)
        registry._install_skills()
        return registry

    def _install_skills(self) -> None:
        if self.skills is None:
            return
        from b3code.commands.builtin.skills import build_skill_command

        for skill in self.skills.skills():
            if not skill.user_invocable:
                continue
            name = skill.name
            if name in self.roots:
                name = f"{skill.scope}:{skill.name}"
            self.roots[name] = build_skill_command(skill, self.skills, name=name)
            self._skill_names.add(name)

    def reload_skills(self) -> None:
        for name in self._skill_names:
            self.roots.pop(name, None)
        self._skill_names.clear()
        self._install_skills()

    def complete(self, line: str) -> list[Suggestion]:
        if not line.startswith("/"):
            return []
        tokens = slash_tokens(line)
        head = tokens[0] if tokens else ""
        root = self.roots.get(head)
        if root is None:
            return self._complete_roots(head) if len(tokens) <= 1 else []
        cmd, rest = self._resolve(root, tokens[1:])
        if cmd.completer is not None:
            return cmd.completer(*rest) if rest else cmd.completer("")
        if cmd.children:
            prefix = rest[0] if rest else ""
            return self._complete_children(cmd, prefix)
        return []

    def _resolve(self, cmd: Command, tokens: list[str]) -> tuple[Command, list[str]]:
        rest = list(tokens)
        while rest and rest[0] in cmd.children:
            cmd = cmd.children[rest[0]]
            rest = rest[1:]
        return cmd, rest

    def _complete_roots(self, head: str) -> list[Suggestion]:
        return [
            Suggestion(
                value=f"/{cmd.name}",
                label=f"/{cmd.name}",
                hint=cmd.help,
                kind="cmd",
                consume=cmd.completer is None and not cmd.children,
            )
            for cmd in self.roots.values()
            if cmd.name.startswith(head)
        ]

    def _complete_children(self, exact: Command, prefix: str) -> list[Suggestion]:
        return [
            Suggestion(
                value=child.name,
                label=child.name,
                hint=child.help,
                kind="arg",
                consume=child.completer is None and not child.children,
            )
            for child in exact.children.values()
            if child.name.startswith(prefix)
        ]

    def execute(self, line: str) -> CommandResult:
        tokens = line[1:].split()
        if not tokens:
            return CommandResult("empty command")
        name, *rest = tokens
        root = self.roots.get(name)
        if root is None:
            return CommandResult(f"unknown command /{name}")
        cmd, args = self._resolve(root, rest)
        if cmd.handler is None:
            return CommandResult(f"usage: /{cmd.name}")
        try:
            return cmd.handler(*args)
        except Exception as exc:
            return CommandResult(str(exc))
