from b3code.commands.effects import Refresh
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import THINKING_LEVELS
from b3code.config.service import ConfigService
from b3code.services.chat import ChatService

_USAGE = "usage: /thinking " + "|".join(THINKING_LEVELS)


def build_thinking(config_service: ConfigService, chat: ChatService) -> Command:
    def handler(*args: str) -> CommandResult:
        if not args:
            return CommandResult(f"thinking: {config_service.config.thinking}")
        if len(args) != 1:
            return CommandResult(_USAGE)
        config_service.set_thinking(args[0])
        chat.reload(config_service.config)
        return CommandResult(
            f"thinking → {config_service.config.thinking}", effect=Refresh()
        )

    def complete(prefix: str = "", *_: str) -> list[Suggestion]:
        needle = prefix.lower()
        return [
            Suggestion(
                value=level, label="effort", hint=level, kind="arg", consume=True
            )
            for level in THINKING_LEVELS
            if level.startswith(needle)
        ]

    return Command("thinking", "set thinking effort", handler, complete)
