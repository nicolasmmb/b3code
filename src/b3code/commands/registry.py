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


@dataclass
class Command:
    name: str
    help: str
    handler: Callable[..., CommandResult] | None = None
    completer: Callable[[str], list[Suggestion]] | None = None
    children: dict[str, Command] = field(default_factory=dict)


class CommandRegistry:
    def __init__(self, roots: dict[str, Command], config: AppConfig) -> None:
        self.roots = roots
        self.config = config

    @classmethod
    def build(
        cls,
        store: ConfigStore,
        config: AppConfig,
        sessions: SessionStore,
        chat: ChatService,
        catalog=None,
        config_service=None,
    ) -> CommandRegistry:
        from b3code.commands.builtin import CommandServices, build_all
        from b3code.config.service import ConfigService
        from b3code.services.catalog import ModelCatalog

        cfg_svc = config_service or ConfigService(store, config)
        services = CommandServices(
            config_service=cfg_svc,
            sessions=sessions,
            chat=chat,
            catalog=catalog or ModelCatalog(),
        )
        roots = {cmd.name: cmd for cmd in build_all(services)}
        return cls(roots, cfg_svc.config)

    def complete(self, line: str) -> list[Suggestion]:
        if not line.startswith("/"):
            return []
        tokens = slash_tokens(line)
        head = tokens[0] if tokens else ""
        exact = self.roots.get(head)
        arg_hits = self._complete_args(exact, tokens)
        if arg_hits is not None:
            return arg_hits
        if len(tokens) <= 1:
            return self._complete_roots(head)
        if exact is None:
            return []
        return self._complete_children(exact, tokens[1])

    def _complete_args(
        self, exact: Command | None, tokens: list[str]
    ) -> list[Suggestion] | None:
        if exact is None or exact.completer is None:
            return None
        head = tokens[0] if tokens else ""
        if len(tokens) < 2 and head != exact.name:
            return None
        prefix = tokens[1] if len(tokens) >= 2 else ""
        return exact.completer(prefix)

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
                value=f"/{exact.name} {child.name}",
                label=f"/{exact.name} {child.name}",
                hint=child.help,
                kind="cmd",
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
        cmd = self.roots.get(name)
        if cmd is None:
            return CommandResult(f"unknown command /{name}")
        if cmd.handler is None:
            return CommandResult(f"usage: /{cmd.name}")
        try:
            return cmd.handler(*rest)
        except Exception as exc:
            return CommandResult(str(exc))
