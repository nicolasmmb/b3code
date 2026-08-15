from b3code.commands.effects import DoctorMcp, Refresh
from b3code.commands.parse import parse_mcp_add
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.config.schema import McpServerConfig
from b3code.config.service import ConfigService
from b3code.services.chat import ChatService
from b3code.services.mcp import format_mcp_list

_ADD_USAGE = (
    "usage: /mcp add <name> -- <command> [args...] "
    "or /mcp add --transport http|sse <name> <url>"
)


def build_mcp(config_service: ConfigService, chat: ChatService) -> Command:
    return Command(
        "mcp",
        "list or edit MCP servers",
        lambda *args: _list(config_service, chat, args),
        children={
            "add": Command(
                "add",
                "add a server",
                lambda *args: _add(config_service, chat, args),
            ),
            "remove": Command(
                "remove",
                "delete a server",
                lambda *args: _remove(config_service, chat, args),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
            "enable": Command(
                "enable",
                "turn a server on",
                lambda *args: _set_enabled(config_service, chat, args, True),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
            "disable": Command(
                "disable",
                "turn a server off",
                lambda *args: _set_enabled(config_service, chat, args, False),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
            "doctor": Command(
                "doctor",
                "test a server connection",
                lambda *args: _doctor(config_service, args),
                lambda prefix="", *_: _complete_names(config_service, prefix),
            ),
        },
    )


def _list(
    config_service: ConfigService, chat: ChatService, args: tuple[str, ...]
) -> CommandResult:
    if args:
        return CommandResult(
            "usage: /mcp | /mcp add | /mcp remove | /mcp enable | "
            "/mcp disable | /mcp doctor"
        )
    return CommandResult(format_mcp_list(config_service.config.mcp_servers, chat.mcp))


def _add(
    config_service: ConfigService, chat: ChatService, args: tuple[str, ...]
) -> CommandResult:
    if not args:
        return CommandResult(_ADD_USAGE)
    try:
        parsed = parse_mcp_add(args)
        spec = McpServerConfig(
            command=parsed.command,
            args=parsed.args,
            env=parsed.env,
            url=parsed.url,
            headers=parsed.headers,
            transport=parsed.transport,
        )
        config_service.upsert_mcp_server(parsed.name, spec)
    except ValueError as exc:
        return CommandResult(str(exc))
    chat.reload(config_service.config)
    return CommandResult(f"mcp + {parsed.name}", effect=Refresh())


def _remove(
    config_service: ConfigService, chat: ChatService, args: tuple[str, ...]
) -> CommandResult:
    if len(args) != 1:
        return CommandResult("usage: /mcp remove <name>")
    config_service.remove_mcp_server(args[0])
    chat.reload(config_service.config)
    return CommandResult(f"mcp - {args[0]}", effect=Refresh())


def _set_enabled(
    config_service: ConfigService,
    chat: ChatService,
    args: tuple[str, ...],
    enabled: bool,
) -> CommandResult:
    verb = "enable" if enabled else "disable"
    if len(args) != 1:
        return CommandResult(f"usage: /mcp {verb} <name>")
    config_service.set_mcp_enabled(args[0], enabled)
    chat.reload(config_service.config)
    state = "on" if enabled else "off"
    return CommandResult(f"mcp {args[0]} {state}", effect=Refresh())


def _doctor(
    config_service: ConfigService, args: tuple[str, ...]
) -> CommandResult:
    servers = config_service.config.mcp_servers
    if not args:
        if not servers:
            return CommandResult("mcp: no servers")
        return CommandResult("", effect=DoctorMcp(tuple(servers)))
    if len(args) != 1:
        return CommandResult("usage: /mcp doctor [name]")
    name = args[0]
    if name not in servers:
        return CommandResult(f"unknown mcp server {name!r}")
    return CommandResult("", effect=DoctorMcp((name,)))


def _complete_names(config_service: ConfigService, prefix: str) -> list[Suggestion]:
    return [
        Suggestion(value=name, label=name, hint="server", kind="arg", consume=True)
        for name in config_service.config.mcp_servers
        if name.startswith(prefix)
    ]
