from b3code.commands.parse import parse_on_off
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.service import ConfigService


def build_multiline(config_service: ConfigService) -> Command:
    def handler(*args: str) -> CommandResult:
        if not args:
            config_service.set_multiline(not config_service.config.multiline)
        else:
            enabled = parse_on_off(args[0])
            if enabled is None:
                return CommandResult("usage: /multiline on|off")
            config_service.set_multiline(enabled)
        state = "on" if config_service.config.multiline else "off"
        return CommandResult(f"multiline: {state}")

    def complete(prefix: str = "", *_: str) -> list[Suggestion]:
        return [
            Suggestion(
                value=value, label=value, hint="toggle", kind="arg", consume=True
            )
            for value in ("on", "off")
            if value.startswith(prefix)
        ]

    return Command(
        "multiline",
        "toggle multiline input (shift+enter newline)",
        handler,
        complete,
    )
