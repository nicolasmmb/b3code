"""Comandos `/` com subcomandos. Nunca vão para o LLM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore


@dataclass
class Suggestion:
    value: str
    label: str
    hint: str
    kind: str  # cmd | file


@dataclass
class CommandResult:
    message: str
    action: str | None = None  # quit | refresh | new
    payload: str | None = None


@dataclass
class Command:
    name: str
    help: str
    handler: Callable[..., CommandResult] | None = None
    children: dict[str, Command] = field(default_factory=dict)


class CommandRegistry:
    def __init__(self, roots: dict[str, Command], models: list[str] | None = None) -> None:
        self.roots = roots
        self.models = models or []

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
                    rows.append(f"{mark} {session.id}  {session.created_at}  {len(session.messages)} msgs")
                return CommandResult("sessions:\n" + "\n".join(rows) or "(none)")
            sessions.activate(args[0])
            return CommandResult(f"resumed {args[0]}", action="refresh")

        def model_cmd(*args: str) -> CommandResult:
            if not args:
                lines = []
                for i, name in enumerate(config.api_models):
                    mark = "*" if i == 0 else " "
                    lines.append(f"{mark} {name}")
                return CommandResult("models:\n" + "\n".join(lines))
            config.select_model(args[0])
            store.save(config)
            chat.reload(config)
            return CommandResult(f"model → {config.model}", action="refresh")

        roots = {
            "help": Command("help", "list commands", help_cmd),
            "new": Command("new", "start a new session", new_cmd),
            "resume": Command("resume", "list or resume a session", resume_cmd),
            "quit": Command("quit", "quit the app", quit_cmd),
            "exit": Command("exit", "quit the app", quit_cmd),
            "model": Command("model", "list or switch model", model_cmd),
        }
        return cls(roots, models=list(config.api_models))

    def complete(self, line: str) -> list[Suggestion]:
        if not line.startswith("/"):
            return []
        tokens = _slash_tokens(line)
        head = tokens[0] if tokens else ""
        if len(tokens) <= 1:
            return [
                Suggestion(value=f"/{c.name}", label=f"/{c.name}", hint=c.help, kind="cmd")
                for c in self.roots.values()
                if c.name.startswith(head)
            ]
        cmd = self.roots.get(tokens[0])
        if cmd is None:
            return []
        prefix = tokens[1]
        if cmd.name == "model":
            return [
                Suggestion(value=name, label=name, hint="deployment", kind="cmd")
                for name in self.models
                if name.startswith(prefix)
            ]
        if cmd.name == "resume":
            return []
        return [
            Suggestion(value=f"/{cmd.name} {child.name}", label=f"/{cmd.name} {child.name}", hint=child.help, kind="cmd")
            for child in cmd.children.values()
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
