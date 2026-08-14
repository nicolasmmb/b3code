"""Hub MCP: specs em memória, handshake só no search/use."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping
from typing import Any

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from b3code.config.schema import AppConfig, McpServerConfig

MAX_MCP_OUTPUT = 20_000
MCP_TOOLS = frozenset({"search_tool", "use_tool"})
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_QUALIFIED = re.compile(r"^([A-Za-z0-9_-]+)__(.+)$")


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


def split_mcp_tool(name: str) -> tuple[str, str]:
    match = _QUALIFIED.match(name)
    if match is None:
        raise ModelRetry(f"use server__tool (got {name!r})")
    return match.group(1), match.group(2)


def format_mcp_list(servers: Mapping[str, McpServerConfig]) -> str:
    if not servers:
        return "mcp: no servers"
    lines = []
    for name, spec in servers.items():
        state = "on" if spec.enabled else "off"
        lines.append(f"{name}  {state}  {spec.transport}  {spec.target}")
    return "\n".join(lines)


def _render_result(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return clip_mcp_output(text)


class McpHub:
    def __init__(self, config: AppConfig | None = None) -> None:
        self._specs: dict[str, McpServerConfig] = {}
        self._bound: dict[str, Any] = {}
        self._toolsets: dict[str, Any] = {}
        self._open: set[str] = set()
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
        for name in list(self._toolsets):
            if name not in wanted and name not in self._bound:
                self._drop(name)
        self._specs = wanted

    def bind(self, name: str, client: Any) -> None:
        """Testes: FastMCP in-process. Não faz handshake."""
        self._bound[name] = client

    def _drop(self, name: str) -> None:
        toolset = self._toolsets.pop(name, None)
        self._open.discard(name)
        if toolset is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if getattr(toolset, "is_running", False):
            loop.create_task(toolset.__aexit__(None, None, None))

    async def search(self, query: str) -> str:
        names = self._enabled()
        if not names:
            return "no MCP servers enabled"
        hits: list[str] = []
        needle = query.strip().lower()
        for name in names:
            hits.extend(await self._search_server(name, needle))
        if not hits:
            return f"no MCP tools match {query!r}"
        return "\n".join(hits)

    async def use(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        server, local = split_mcp_tool(tool_name)
        if server not in self._enabled():
            raise ModelRetry(f"unknown MCP server {server!r}")
        toolset = await self._ensure(server)
        result = await toolset.direct_call_tool(local, arguments or {})
        return _render_result(result)

    def tools(self) -> FunctionToolset:
        async def search_tool(query: str) -> str:
            """Discover MCP tools across enabled servers. Names are server__tool."""
            try:
                return await self.search(query)
            except Exception as exc:
                raise ModelRetry(str(exc)) from exc

        async def use_tool(
            tool_name: str, arguments: dict[str, Any] | None = None
        ) -> str:
            """Call an MCP tool discovered via search_tool. tool_name is server__tool."""
            try:
                return await self.use(tool_name, arguments)
            except ModelRetry:
                raise
            except Exception as exc:
                raise ModelRetry(str(exc)) from exc

        return FunctionToolset(tools=[search_tool, use_tool])

    def _enabled(self) -> list[str]:
        return list(dict.fromkeys([*self._specs, *self._bound]))

    async def _search_server(self, name: str, needle: str) -> list[str]:
        try:
            toolset = await self._ensure(name)
            listed = await toolset.list_tools()
        except Exception as exc:
            return [f"{name}  error  {exc}"]
        hits: list[str] = []
        for tool in listed:
            qualified = f"{name}__{tool.name}"
            desc = (tool.description or "").replace("\n", " ").strip()
            blob = f"{qualified} {desc}".lower()
            if needle and needle not in blob:
                continue
            hits.append(f"{qualified}  {desc}" if desc else qualified)
        return hits

    async def _ensure(self, name: str) -> Any:
        if name not in self._toolsets:
            self._toolsets[name] = self._build(name)
        toolset = self._toolsets[name]
        if name not in self._open:
            await toolset.__aenter__()
            self._open.add(name)
            self._connects += 1
        return toolset

    def _build(self, name: str) -> Any:
        from pydantic_ai.mcp import MCPToolset

        if name in self._bound:
            return MCPToolset(self._bound[name])
        spec = self._specs[name]
        timeout = float(spec.startup_timeout_sec)
        if spec.url:
            url = expand_vars(spec.url)
            headers = expand_map(spec.headers, None)
            return MCPToolset(url, headers=headers or None, init_timeout=timeout)
        return MCPToolset(self._stdio(spec), init_timeout=timeout)

    def _stdio(self, spec: McpServerConfig) -> Any:
        from fastmcp.client.transports import StdioTransport

        extra = expand_map(spec.env, None)
        env = {**os.environ, **extra} if extra else None
        args = [expand_vars(item) for item in spec.args]
        return StdioTransport(expand_vars(spec.command), args, env=env)
