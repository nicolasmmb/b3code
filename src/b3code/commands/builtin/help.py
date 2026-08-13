from collections.abc import Sequence

from b3code.commands.registry import Command
from b3code.commands.types import CommandResult


def build_help(commands: Sequence[Command]) -> Command:
    def handler(*_: str) -> CommandResult:
        lines = [f"/{cmd.name}  {cmd.help}" for cmd in commands]
        return CommandResult("\n".join(lines))

    return Command("help", "list commands", handler)
