from b3code.commands.effects import Refresh
from b3code.commands.parse import parse_on_off
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.service import ConfigService
from b3code.services.catalog import ModelCatalog
from b3code.services.chat import ChatService


def build_model(
    config_service: ConfigService, catalog: ModelCatalog, chat: ChatService
) -> Command:
    def handler(*args: str) -> CommandResult:
        config = config_service.config
        if not args:
            mode = "gateway" if config.use_provider_gateway else "catalog"
            return CommandResult(
                f"model: {config.selected_model}  ({mode})\n"
                "type /model <name> or search in the autocomplete"
            )
        name = " ".join(args)
        config_service.select_model(name)
        chat.reload(config_service.config)
        return CommandResult(
            f"model → {config_service.config.selected_model}", effect=Refresh()
        )

    def complete(prefix: str) -> list[Suggestion]:
        config = config_service.config
        hint = "gateway" if config.use_provider_gateway else "catalog"
        return [
            Suggestion(value=name, label=name, hint=hint, kind="arg", consume=True)
            for name in catalog.complete(config, prefix)
        ]

    return Command("model", "list or switch model", handler, complete)


def build_gateway(config_service: ConfigService, chat: ChatService) -> Command:
    def handler(*args: str) -> CommandResult:
        config = config_service.config
        if not args:
            state = "on" if config.use_provider_gateway else "off"
            return CommandResult(f"gateway: {state}")
        enabled = parse_on_off(args[0])
        if enabled is None:
            return CommandResult("usage: /gateway on|off")
        config_service.toggle_gateway(enabled)
        chat.reload(config_service.config)
        state = "on" if config_service.config.use_provider_gateway else "off"
        return CommandResult(f"gateway: {state}", effect=Refresh())

    def complete(prefix: str) -> list[Suggestion]:
        return [
            Suggestion(
                value=value, label=value, hint="toggle", kind="arg", consume=True
            )
            for value in ("on", "off")
            if value.startswith(prefix)
        ]

    return Command("gateway", "toggle Azure gateway", handler, complete)
