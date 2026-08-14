import pytest
from mcp.server.fastmcp import FastMCP
from pydantic_ai.exceptions import ModelRetry

from b3code.config.schema import AppConfig, McpServerConfig
from b3code.services.mcp import (
    MAX_MCP_OUTPUT,
    McpHub,
    clip_mcp_output,
    expand_vars,
    format_mcp_list,
    split_mcp_tool,
)


def _stdio(**kwargs) -> McpServerConfig:
    payload = {"command": "npx", "args": ["-y", "demo"], **kwargs}
    return McpServerConfig.model_validate(payload)


def _http(**kwargs) -> McpServerConfig:
    payload = {"url": "https://mcp.example.com/mcp", **kwargs}
    return McpServerConfig.model_validate(payload)


def test_expand_vars_and_default():
    env = {"TOKEN": "abc"}
    assert expand_vars("Bearer ${TOKEN}", env) == "Bearer abc"
    assert expand_vars("${MISSING:-x}", env) == "x"
    with pytest.raises(ValueError, match="MISSING"):
        expand_vars("${MISSING}", env)


def test_format_list_and_transport():
    servers = {
        "github": _stdio(),
        "linear": _http(enabled=False),
        "legacy": McpServerConfig(url="https://x.example/sse"),
    }
    text = format_mcp_list(servers)
    assert "github  on  stdio  npx -y demo" in text
    assert "linear  off  http  https://mcp.example.com/mcp" in text
    assert "legacy  on  sse  https://x.example/sse" in text
    assert format_mcp_list({}) == "mcp: no servers"


def test_split_and_clip():
    assert split_mcp_tool("github__create_issue") == ("github", "create_issue")
    with pytest.raises(ModelRetry, match="server__tool"):
        split_mcp_tool("create_issue")
    huge = "x" * (MAX_MCP_OUTPUT + 10)
    out = clip_mcp_output(huge)
    assert out.endswith("…")
    assert len(out) == MAX_MCP_OUTPUT + 2


def test_reload_does_not_connect():
    cfg = AppConfig(mcp_servers={"github": _stdio(), "off": _http(enabled=False)})
    hub = McpHub(cfg)
    assert hub.connects == 0
    hub.reload(cfg)
    assert hub.connects == 0


def _demo_server() -> FastMCP:
    app = FastMCP("demo")

    @app.tool()
    def ping() -> str:
        """Health check."""
        return "pong"

    @app.tool()
    def echo(text: str) -> str:
        """Repeat text."""
        return text

    return app


async def test_search_and_use_in_process():
    hub = McpHub()
    hub.bind("demo", _demo_server())
    assert hub.connects == 0
    listed = await hub.search("")
    assert hub.connects == 1
    assert "demo__ping" in listed
    assert "Health check" in listed
    hits = await hub.search("echo")
    assert "demo__echo" in hits
    assert "demo__ping" not in hits
    assert await hub.use("demo__echo", {"text": "hi"}) == "hi"
    assert hub.connects == 1


async def test_disabled_server_absent_from_search():
    hub = McpHub(AppConfig(mcp_servers={"gone": _http(enabled=False)}))
    assert await hub.search("ping") == "no MCP servers enabled"


async def test_use_unknown_and_truncates():
    blob = "z" * (MAX_MCP_OUTPUT + 50)
    app = _demo_server()

    @app.tool()
    def dump() -> str:
        return blob

    hub = McpHub()
    hub.bind("demo", app)
    with pytest.raises(ModelRetry, match="unknown MCP server"):
        await hub.use("other__ping", {})
    out = await hub.use("demo__dump", {})
    assert out.endswith("…")
    assert len(out) == MAX_MCP_OUTPUT + 2
