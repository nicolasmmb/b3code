import pytest
from mcp.server.fastmcp import FastMCP
from pydantic_ai.mcp import MCPToolset

from b3code.config.schema import AppConfig, McpServerConfig
from b3code.services.mcp import (
    MAX_MCP_OUTPUT,
    McpHub,
    clip_mcp_output,
    expand_vars,
    format_mcp_list,
    is_mutation,
    unwrap_mcp,
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
        "remote": McpServerConfig(url="https://x.example/mcp", transport="sse"),
    }
    text = format_mcp_list(servers)
    assert "github  idle  stdio  npx -y demo" in text
    assert "linear  off  http  https://mcp.example.com/mcp" in text
    assert "legacy  idle  sse  https://x.example/sse" in text
    assert "remote  idle  sse  https://x.example/mcp" in text
    assert format_mcp_list({}) == "mcp: no servers"
    assert servers["github"].tool_timeout_sec == 120


def test_clip_and_mutation():
    huge = "x" * (MAX_MCP_OUTPUT + 10)
    out = clip_mcp_output(huge)
    assert out.endswith("…")
    assert len(out) == MAX_MCP_OUTPUT + 2
    assert is_mutation("demo_create_issue")
    assert is_mutation("github_delete_file")
    assert not is_mutation("demo_ping")
    assert not is_mutation("demo_echo")


def test_reload_does_not_connect():
    cfg = AppConfig(mcp_servers={"github": _stdio(), "off": _http(enabled=False)})
    hub = McpHub(cfg)
    assert hub.connects == 0
    assert len(hub.toolsets()) == 1
    hub.reload(cfg)
    assert hub.connects == 0
    assert not unwrap_mcp(hub.toolsets()[0]).is_running


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

    @app.tool()
    def create_issue(title: str) -> str:
        return title

    return app


async def test_toolsets_defer_and_list_in_process():
    hub = McpHub()
    hub.bind("demo", _demo_server())
    wrapped = hub.toolsets()[0]
    kinds = []
    current = wrapped
    while hasattr(current, "wrapped"):
        kinds.append(type(current).__name__)
        current = current.wrapped
    assert "DeferredLoadingToolset" in kinds
    raw = unwrap_mcp(wrapped)
    assert isinstance(raw, MCPToolset)
    assert raw.is_running is False
    assert hub.connects == 0
    async with raw:
        listed = await raw.list_tools()
    names = {tool.name for tool in listed}
    assert names == {"ping", "echo", "create_issue"}
    echo = next(tool for tool in listed if tool.name == "echo")
    schema = echo.inputSchema or {}
    props = schema.get("properties") or {}
    assert "text" in props
    await hub.aclose()
    assert raw.is_running is False


async def test_aclose_is_idempotent():
    hub = McpHub()
    hub.bind("demo", _demo_server())
    raw = hub.raw("demo")
    await raw.__aenter__()
    assert raw.is_running is True
    await hub.aclose()
    await hub.aclose()
    assert raw.is_running is False


def test_planner_filters_mutation():
    hub = McpHub()
    hub.bind("demo", _demo_server())
    coder = hub.toolsets(mutate=True)
    planner = hub.toolsets(mutate=False)
    assert coder
    assert planner
    assert type(planner[0]).__name__ == "FilteredToolset"


def test_disabled_server_absent():
    hub = McpHub(AppConfig(mcp_servers={"gone": _http(enabled=False)}))
    assert hub.toolsets() == []


async def test_list_shows_ok_after_enter():
    cfg = AppConfig(mcp_servers={"demo": _http()})
    hub = McpHub(cfg)
    hub.bind("demo", _demo_server())
    listed = format_mcp_list(cfg.mcp_servers, hub)
    assert "demo  idle  http" in listed
    raw = hub.raw("demo")
    await raw.__aenter__()
    listed = format_mcp_list(cfg.mcp_servers, hub)
    assert "demo  ok  http" in listed
    await hub.aclose()


def test_stdio_log_file_uses_cwd(tmp_path):
    cfg = AppConfig(mcp_servers={"github": _stdio()})
    hub = McpHub(cfg, cwd=tmp_path)
    transport = hub.raw("github").client.transport
    log = tmp_path / ".b3code" / "mcp" / "github.stderr.log"
    assert transport.log_file == log
    assert log.parent.is_dir()


def test_sse_builder_uses_sse_transport():
    hub = McpHub(
        AppConfig(
            mcp_servers={
                "remote": McpServerConfig(url="https://x.example/mcp", transport="sse")
            }
        )
    )
    raw = hub.raw("remote")
    assert type(raw.client.transport).__name__ == "SSETransport"
    assert raw.client._init_timeout == 30.0
