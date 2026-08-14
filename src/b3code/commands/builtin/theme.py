from b3code.commands.effects import Refresh
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import THEME_COLOR_DEFAULTS
from b3code.config.service import ConfigService

_USAGE = (
    "usage: /theme | /theme set <name> | /theme update <token> <#hex> "
    "| /theme save <name>"
)


def build_theme(config_service: ConfigService) -> Command:
    return Command(
        "theme",
        "list or edit themes",
        lambda *args: _list(config_service, args),
        children={
            "set": Command(
                "set",
                "activate a saved theme",
                lambda *args: _set(config_service, args),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
            "update": Command(
                "update",
                "edit a color of the active theme",
                lambda *args: _update(config_service, args),
                lambda prefix="", *more: _complete_update(config_service, prefix, more),
            ),
            "save": Command(
                "save",
                "copy active theme to a new name",
                lambda *args: _save(config_service, args),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
        },
    )


def _list(config_service: ConfigService, args: tuple[str, ...]) -> CommandResult:
    if args:
        return CommandResult(_USAGE)
    return CommandResult(_list_themes(config_service))


def _set(config_service: ConfigService, args: tuple[str, ...]) -> CommandResult:
    if not args:
        return CommandResult("usage: /theme set <name>")
    config_service.select_theme(" ".join(args))
    return CommandResult(
        f"theme → {config_service.config.theme.display}", effect=Refresh()
    )


def _update(config_service: ConfigService, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 2:
        return CommandResult("usage: /theme update <token> <#hex>")
    config_service.set_theme_color(args[0], args[1])
    token = args[0]
    shown = config_service.config.theme.display
    color = getattr(config_service.config.theme, token)
    return CommandResult(f"theme {shown}.{token} → {color}", effect=Refresh())


def _save(config_service: ConfigService, args: tuple[str, ...]) -> CommandResult:
    if not args:
        return CommandResult("usage: /theme save <name>")
    config_service.save_theme(" ".join(args))
    return CommandResult(
        f"theme saved {config_service.config.theme.display}", effect=Refresh()
    )


def _complete_names(config_service: ConfigService, prefix: str) -> list[Suggestion]:
    needle = prefix.lower()
    hits: list[Suggestion] = []
    for item in config_service.config.themes:
        if needle and not (
            item.name.startswith(needle) or item.display.lower().startswith(needle)
        ):
            continue
        hits.append(
            Suggestion(
                value=item.name,
                label=item.display,
                hint="",
                kind="arg",
                consume=True,
            )
        )
    return hits


def _complete_update(
    config_service: ConfigService, prefix: str, more: tuple[str, ...]
) -> list[Suggestion]:
    if not more:
        return [
            Suggestion(value=token, label=token, hint="color", kind="arg", consume=False)
            for token in THEME_COLOR_DEFAULTS
            if token.startswith(prefix)
        ]
    if prefix not in THEME_COLOR_DEFAULTS:
        return []
    current = getattr(config_service.config.theme, prefix)
    if not str(current).startswith(more[0]):
        return []
    return [
        Suggestion(value=current, label=current, hint="current", kind="arg", consume=True)
    ]


def _list_themes(config_service: ConfigService) -> str:
    cfg = config_service.config
    current = cfg.theme
    lines = [f"theme: {current.display}", ""]
    for item in cfg.themes:
        mark = "*" if item.name == current.name else " "
        lines.append(f"{mark} {item.display}")
    lines.append("")
    for token in THEME_COLOR_DEFAULTS:
        lines.append(f"  {token:<11} {getattr(current, token)}")
    return "\n".join(lines)
