from b3code.commands.effects import Refresh
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import THEME_COLOR_DEFAULTS
from b3code.config.service import ConfigService


def build_theme(config_service: ConfigService) -> Command:
    tokens = tuple(THEME_COLOR_DEFAULTS)

    def handler(*args: str) -> CommandResult:
        if not args:
            return CommandResult(_list_themes(config_service))
        if args[0] == "save":
            return _save(config_service, args[1:])
        if len(args) == 1:
            return _select(config_service, args[0])
        if len(args) == 2 and args[0] in tokens:
            return _set_color(config_service, args[0], args[1])
        return CommandResult(
            "usage: /theme [name] | /theme <token> <#hex> | /theme save <name>"
        )

    def complete(prefix: str) -> list[Suggestion]:
        values = [("save", "copy current")]
        values.extend((item.name, "saved") for item in config_service.config.themes)
        values.extend((token, "color") for token in tokens)
        return [
            Suggestion(value=name, label=name, hint=hint, kind="arg", consume=True)
            for name, hint in values
            if name.startswith(prefix)
        ]

    return Command("theme", "list, switch or edit saved themes", handler, complete)


def _list_themes(config_service: ConfigService) -> str:
    cfg = config_service.config
    current = cfg.theme
    lines = [f"theme: {current.name}", ""]
    for item in cfg.themes:
        mark = "*" if item.name == current.name else " "
        lines.append(f"{mark} {item.name}")
    lines.append("")
    for token in THEME_COLOR_DEFAULTS:
        lines.append(f"  {token:<11} {getattr(current, token)}")
    return "\n".join(lines)


def _select(config_service: ConfigService, name: str) -> CommandResult:
    config_service.select_theme(name)
    return CommandResult(f"theme → {config_service.config.theme.name}", effect=Refresh())


def _set_color(config_service: ConfigService, token: str, value: str) -> CommandResult:
    config_service.set_theme_color(token, value)
    color = getattr(config_service.config.theme, token)
    name = config_service.config.theme.name
    return CommandResult(f"theme {name}.{token} → {color}", effect=Refresh())


def _save(config_service: ConfigService, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        return CommandResult("usage: /theme save <name>")
    config_service.save_theme(args[0])
    return CommandResult(f"theme saved {config_service.config.theme.name}", effect=Refresh())
