"""Hub MCP: specs no config, handshake só no run ou no doctor."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from b3code.config.schema import AppConfig, McpServerConfig

MAX_MCP_OUTPUT = 20_000
_MUTATION = frozenset(
    {
        "create",
        "update",
        "delete",
        "write",
        "post",
        "patch",
        "remove",
        "merge",
        "close",
        "comment",
    }
)
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_vars(text: str, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ

    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in env:
            return env[name]
        if default is not None:
            return default
        raise ValueError(f"undefined environment variable {name!r}")

    return _ENV_REF.sub(repl, text)


def expand_map(
    values: Mapping[str, str], environ: Mapping[str, str] | None
) -> dict[str, str]:
    return {key: expand_vars(value, environ) for key, value in values.items()}


def clip_mcp_output(text: str) -> str:
    if len(text) <= MAX_MCP_OUTPUT:
        return text
    return text[:MAX_MCP_OUTPUT] + "\n…"


def is_mutation(name: str) -> bool:
    parts = name.replace("-", "_").lower().split("_")
    return any(part in _MUTATION for part in parts)


def is_mcp_tool(tool_def: Any) -> bool:
    meta = getattr(tool_def, "metadata", None) or {}
    return bool(meta.get("mcp"))


def unwrap_mcp(toolset: Any) -> Any:
    current = toolset
    while hasattr(current, "wrapped"):
        current = current.wrapped
    return current


def mcp_state(spec: McpServerConfig, running: bool) -> str:
    if not spec.enabled:
        return "off"
    return "ok" if running else "idle"


def format_mcp_list(
    servers: Mapping[str, McpServerConfig], hub: McpHub | None = None
) -> str:
    if not servers:
        return "mcp: no servers"
    lines = []
    for name, spec in servers.items():
        running = bool(hub is not None and hub.running(name))
        lines.append(
            f"{name}  {mcp_state(spec, running)}  {spec.transport}  {spec.target}"
        )
    return "\n".join(lines)


class McpHub:
    def __init__(
        self, config: AppConfig | None = None, cwd: Path | None = None
    ) -> None:
        self.cwd = cwd
        self._specs: dict[str, McpServerConfig] = {}
        self._bound: dict[str, Any] = {}
        self._raw: dict[str, Any] = {}
        self._connects = 0
        if config is not None:
            self.reload(config)

    @property
    def connects(self) -> int:
        return self._connects

    def reload(self, config: AppConfig) -> None:
        wanted = {
            name: spec for name, spec in config.mcp_servers.items() if spec.enabled
        }
        for name in list(self._raw):
            if name not in wanted and name not in self._bound:
                self._drop(name)
        self._specs = wanted

    def bind(self, name: str, client: Any) -> None:
        """Testes: FastMCP in-process. Não faz handshake."""
        self._bound[name] = client

    def toolsets(self, *, mutate: bool = True) -> list[Any]:
        return [self._wrap(name, mutate=mutate) for name in self._enabled()]

    async def aclose(self) -> None:
        for name in list(self._raw):
            await self._exit(name)

    def running(self, name: str) -> bool:
        toolset = self._raw.get(name)
        return bool(toolset is not None and getattr(toolset, "is_running", False))

    def raw(self, name: str) -> Any:
        if name not in self._raw:
            self._raw[name] = self._build(name)
        return self._raw[name]

    def _wrap(self, name: str, *, mutate: bool) -> Any:
        wrapped = self.raw(name).prefixed(name).defer_loading().with_metadata(mcp=True)
        if mutate:
            return wrapped
        return wrapped.filtered(lambda _ctx, tool_def: not is_mutation(tool_def.name))

    def _drop(self, name: str) -> None:
        import asyncio

        toolset = self._raw.pop(name, None)
        if toolset is None or not getattr(toolset, "is_running", False):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(toolset.__aexit__(None, None, None))

    async def _exit(self, name: str) -> None:
        toolset = self._raw.get(name)
        if toolset is None or not getattr(toolset, "is_running", False):
            return
        await toolset.__aexit__(None, None, None)

    def _enabled(self) -> list[str]:
        return list(dict.fromkeys([*self._specs, *self._bound]))

    def _build(self, name: str) -> Any:
        from pydantic_ai.mcp import MCPToolset

        if name in self._bound:
            return MCPToolset(self._bound[name])
        spec = self._specs[name]
        init = float(spec.startup_timeout_sec)
        read = float(spec.tool_timeout_sec)
        if spec.transport == "sse":
            return self._sse(spec, init, read)
        if spec.transport == "http":
            url = expand_vars(spec.url)
            headers = expand_map(spec.headers, None)
            return MCPToolset(
                url, headers=headers or None, init_timeout=init, read_timeout=read
            )
        return MCPToolset(self._stdio(name, spec), init_timeout=init, read_timeout=read)

    def _sse(self, spec: McpServerConfig, init: float, read: float) -> Any:
        from fastmcp.client.transports import SSETransport
        from pydantic_ai.mcp import MCPToolset

        url = expand_vars(spec.url)
        headers = expand_map(spec.headers, None)
        return MCPToolset(
            SSETransport(url, headers=headers or None),
            init_timeout=init,
            read_timeout=read,
        )

    def _stdio(self, name: str, spec: McpServerConfig) -> Any:
        from fastmcp.client.transports import StdioTransport

        extra = expand_map(spec.env, None)
        env = {**os.environ, **extra} if extra else None
        args = [expand_vars(item) for item in spec.args]
        return StdioTransport(
            expand_vars(spec.command), args, env=env, log_file=self._log_file(name)
        )

    def _log_file(self, name: str) -> Path | None:
        if self.cwd is None:
            return None
        path = self.cwd / ".b3code" / "mcp" / f"{name}.stderr.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
