"""Comandos `/` com subcomandos. Nunca vão para o LLM.

`complete()` é genérico: cada Command traz o próprio completer.
A UI não conhece model/resume/gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.catalog import complete_models
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
    ) -> "CommandRegistry":
        def help_cmd(*_: str) -> CommandResult:
            lines = [f"/{c.name}  {c.help}" for c in roots.values()]
            return CommandResult("\n".join(lines))

        def new_cmd(*_: str) -> CommandResult:
            sessions.new()
            return CommandResult("new session", action="new")

        def quit_cmd(*_: str) -> CommandResult:
            return CommandResult("bye", action="quit")

        def resume_cmd(*args: str) -> CommandResult:
            if not args:
                rows = []
                for session in sessions.list_sessions():
                    mark = "*" if session.id == sessions.current_id else " "
                    rows.append(
                        f"{mark} {session.id}  {session.created_at}  {len(session.messages)} msgs"
                    )
                return CommandResult("sessions:\n" + "\n".join(rows) or "(none)")
            sessions.activate(args[0])
            return CommandResult(f"resumed {args[0]}", action="refresh")

        def resume_complete(prefix: str) -> list[Suggestion]:
            needle = prefix.lower()
            out: list[Suggestion] = []
            for session in sessions.list_sessions():
                if needle and needle not in session.id.lower():
                    continue
                mark = "* " if session.id == sessions.current_id else ""
                date = session.created_at[:10] if session.created_at else ""
                out.append(
                    Suggestion(
                        value=session.id,
                        label=session.id,
                        hint=f"{mark}{date}  {len(session.messages)} msgs".strip(),
                        kind="arg",
                        consume=True,
                    )
                )
            return out

        def model_cmd(*args: str) -> CommandResult:
            if not args:
                mode = "gateway" if config.use_provider_gateway else "catalog"
                return CommandResult(
                    f"model: {config.selected_model}  ({mode})\n"
                    "type /model <name> or search in the autocomplete"
                )
            name = " ".join(args)
            config.select_model(name)
            store.save(config)
            chat.reload(config)
            return CommandResult(f"model → {config.selected_model}", action="refresh")

        def model_complete(prefix: str) -> list[Suggestion]:
            hint = "gateway" if config.use_provider_gateway else "catalog"
            return [
                Suggestion(value=name, label=name, hint=hint, kind="arg", consume=True)
                for name in complete_models(config, prefix)
            ]

        def gateway_cmd(*args: str) -> CommandResult:
            if not args:
                state = "on" if config.use_provider_gateway else "off"
                return CommandResult(f"gateway: {state}")
            token = args[0].lower()
            if token not in {"on", "off", "true", "false"}:
                return CommandResult("usage: /gateway on|off")
            config.use_provider_gateway = token in {"on", "true"}
            if (
                config.use_provider_gateway
                and config.api_models
                and config.selected_model not in config.api_models
            ):
                config.selected_model = config.api_models[0]
            store.save(config)
            chat.reload(config)
            state = "on" if config.use_provider_gateway else "off"
            return CommandResult(f"gateway: {state}", action="refresh")

        def gateway_complete(prefix: str) -> list[Suggestion]:
            return [
                Suggestion(value=v, label=v, hint="toggle", kind="arg", consume=True)
                for v in ("on", "off")
                if v.startswith(prefix)
            ]

        roots = {
            "help": Command("help", "list commands", help_cmd),
            "new": Command("new", "start a new session", new_cmd),
            "resume": Command(
                "resume", "list or resume a session", resume_cmd, resume_complete
            ),
            "quit": Command("quit", "quit the app", quit_cmd),
            "exit": Command("exit", "quit the app", quit_cmd),
            "model": Command("model", "list or switch model", model_cmd, model_complete),
            "gateway": Command(
                "gateway", "toggle Azure gateway", gateway_cmd, gateway_complete
            ),
        }
        return cls(roots, config)

    def complete(self, line: str) -> list[Suggestion]:
        if not line.startswith("/"):
            return []
        tokens = _slash_tokens(line)
        head = tokens[0] if tokens else ""
        exact = self.roots.get(head)
        if exact is not None and exact.completer is not None:
            if len(tokens) >= 2 or head == exact.name:
                prefix = tokens[1] if len(tokens) >= 2 else ""
                return exact.completer(prefix)
        if len(tokens) <= 1:
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
        if exact is None:
            return []
        prefix = tokens[1]
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


def _slash_tokens(line: str) -> list[str]:
    """`/model ` (espaço no fim) = próximo token vazio, para listar subcomandos."""
    body = line[1:]
    parts = body.split()
    if body.endswith(" ") or body == "":
        return parts + [""]
    return parts
