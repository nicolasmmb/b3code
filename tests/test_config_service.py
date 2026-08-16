from pathlib import Path

import pytest

from b3code.config.schema import AppConfig, McpServerConfig, ThemeColors
from b3code.config.service import ConfigService
from b3code.config.store import ConfigStore


def _service(tmp_path: Path, **kwargs) -> ConfigService:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(**kwargs)
    store.save(cfg)
    return ConfigService(store, cfg)


def test_select_model_persists(tmp_path: Path):
    service = _service(tmp_path, gateway_api_models=["a", "b"])
    service.select_model("b")
    assert service.config.selected_model == "b"
    assert service.store.load().selected_model == "b"


def test_toggle_gateway(tmp_path: Path):
    service = _service(tmp_path, gateway_api_models=["a"])
    service.toggle_gateway(False)
    assert service.config.use_provider_gateway is False
    assert service.store.load().use_provider_gateway is False


def test_toggle_gateway_snaps_to_api_model(tmp_path: Path):
    service = _service(
        tmp_path,
        use_provider_gateway=False,
        gateway_api_models=["a"],
        selected_model="openai:gpt-4o",
    )
    service.toggle_gateway(True)
    assert service.config.selected_model == "a"


def test_set_thinking(tmp_path: Path):
    service = _service(tmp_path)
    assert service.config.thinking == "off"
    service.set_thinking("high")
    assert service.config.thinking == "high"
    assert service.store.load().thinking == "high"
    with pytest.raises(ValueError, match="thinking"):
        service.set_thinking("max")


def test_set_multiline(tmp_path: Path):
    service = _service(tmp_path)
    assert service.config.multiline is True
    service.set_multiline(False)
    assert service.config.multiline is False
    assert service.store.load().multiline is False


def test_select_theme_persists(tmp_path: Path):
    service = _service(
        tmp_path,
        themes=[
            ThemeColors(name="b3code"),
            ThemeColors(name="crimson", accent="#DC143C"),
        ],
        selected_theme="b3code",
    )
    service.select_theme("crimson")
    assert service.config.selected_theme == "crimson"
    assert service.config.accent == "#DC143C"
    assert service.store.load().selected_theme == "crimson"


def test_set_theme_color_persists(tmp_path: Path):
    service = _service(tmp_path)
    service.set_theme_color("background", "#111111")
    assert service.config.theme.background == "#111111"
    assert service.store.load().theme.background == "#111111"


def test_set_theme_color_rejects_unknown_and_bad_hex(tmp_path: Path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.set_theme_color("glow", "#fff")
    with pytest.raises(ValueError):
        service.set_theme_color("accent", "red")


def test_save_theme_clones_current(tmp_path: Path):
    service = _service(tmp_path)
    service.set_theme_color("accent", "#DC143C")
    service.save_theme("crimson")
    loaded = service.store.load()
    names = [item.name for item in loaded.themes]
    assert names == ["b3code", "github-dark", "crimson"]
    assert loaded.selected_theme == "crimson"
    assert loaded.theme.accent == "#DC143C"


def test_save_theme_slugifies_spaces(tmp_path: Path):
    service = _service(tmp_path)
    service.save_theme("Tokyo Night")
    loaded = service.store.load()
    assert loaded.selected_theme == "tokyo-night"
    assert loaded.theme.name == "tokyo-night"
    assert loaded.theme.label == "Tokyo Night"
    assert loaded.theme.display == "Tokyo Night"


def test_mcp_crud_persists(tmp_path: Path):
    service = _service(tmp_path)
    spec = McpServerConfig(command="npx", args=["-y", "demo"])
    service.upsert_mcp_server("github", spec)
    assert service.store.load().mcp_servers["github"].command == "npx"
    service.set_mcp_enabled("github", False)
    assert service.store.load().mcp_servers["github"].enabled is False
    service.remove_mcp_server("github")
    assert service.store.load().mcp_servers == {}
    with pytest.raises(ValueError, match="unknown"):
        service.get_mcp_server("github")


def test_persist_allowed_path(tmp_path: Path):
    service = _service(tmp_path)
    path = Path("/tmp").resolve()
    service.persist_allowed_path(path)
    assert str(path) in service.config.shell_allowed_paths
    assert str(path) in service.store.load().shell_allowed_paths
