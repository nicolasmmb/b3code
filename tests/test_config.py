import json
from pathlib import Path

import pytest

from b3code.config.schema import (
    DEFAULT_EXCLUDE_DIRECTORIES,
    THEME_COLOR_DEFAULTS,
    AppConfig,
    McpServerConfig,
    github_dark_theme,
    slugify_theme,
)
from b3code.config.service import ConfigService
from b3code.config.store import ConfigStore


def test_select_model_moves_to_front(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["a", "b", "c"])
    store.save(cfg)
    service = ConfigService(store, cfg)
    service.select_model("c")
    assert cfg.gateway_api_models == ["c", "a", "b"]
    assert cfg.selected_model == "c"


def test_select_unknown_model(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["a"])
    store.save(cfg)
    service = ConfigService(store, cfg)
    with pytest.raises(ValueError):
        service.select_model("nope")


def test_accent_rejects_bad_hex():
    assert AppConfig(accent="red").accent == "#00b0e6"
    assert AppConfig(accent="#fff").accent == "#fff"
    assert AppConfig(accent="#c9a227").accent == "#c9a227"


def test_legacy_accent_migrates_into_default_theme():
    cfg = AppConfig(accent="#DC143C")
    assert cfg.theme.name == "b3code"
    assert cfg.theme.accent == "#DC143C"
    assert "accent" not in cfg.model_dump()
    assert cfg.themes[0].accent == "#DC143C"


def test_theme_color_rejects_bad_hex():
    theme = AppConfig(themes=[{"name": "x", "background": "blue"}]).theme
    assert theme.background == "#1c1d1f"
    assert AppConfig(themes=[{"name": "x", "background": "#111"}]).theme.background == (
        "#111"
    )


def test_default_themes_include_github_dark():
    cfg = AppConfig()
    names = [item.name for item in cfg.themes]
    assert names == ["b3code", "github-dark"]
    assert cfg.selected_theme == "b3code"
    assert cfg.theme.model_dump(exclude={"name", "label"}) == THEME_COLOR_DEFAULTS
    github = github_dark_theme()
    saved = next(item for item in cfg.themes if item.name == "github-dark")
    assert saved.background == "#0d1117"
    assert saved.accent == "#58a6ff"
    assert saved.model_dump() == github.model_dump()


def test_slugify_theme_names():
    assert slugify_theme("B3 Light") == "b3-light"
    assert slugify_theme("Tokyo Night") == "tokyo-night"
    assert slugify_theme("DeepDark") == "deepdark"
    assert slugify_theme("  Github Dark  ") == "github-dark"
    assert slugify_theme("!!!") == ""


def test_spaced_theme_name_keeps_label():
    cfg = AppConfig(
        selected_theme="B3 Light",
        themes=[{"name": "B3 Light", "accent": "#1818b7"}],
    )
    assert cfg.theme.name == "b3-light"
    assert cfg.theme.label == "B3 Light"
    assert cfg.theme.display == "B3 Light"
    assert cfg.selected_theme == "b3-light"


def test_selected_theme_matches_slug_case():
    cfg = AppConfig(
        selected_theme="deepdark",
        themes=[{"name": "DeepDark", "accent": "#FFD32C"}],
    )
    assert cfg.theme.name == "deepdark"
    assert cfg.theme.label == "DeepDark"
    assert cfg.selected_theme == "deepdark"


def test_unknown_selected_theme_snaps_to_first():
    cfg = AppConfig(
        selected_theme="missing",
        themes=[{"name": "crimson", "accent": "#DC143C"}],
    )
    assert cfg.selected_theme == "crimson"
    assert cfg.theme.accent == "#DC143C"


def test_shell_allowed_paths_roundtrip(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(shell_allowed_paths=["/tmp"])
    store.save(cfg)
    assert store.load().shell_allowed_paths == ["/tmp"]


def test_roundtrip(tmp_path: Path):
    path = tmp_path / ".b3code" / "config.json"
    store = ConfigStore(path)
    cfg = AppConfig(
        gateway_api_key="k",
        gateway_api_endpoint="https://x/openai/v1/",
        gateway_api_models=["m1"],
    )
    store.save(cfg)
    loaded = store.load()
    assert loaded.gateway_api_key == "k"
    assert loaded.selected_model == "m1"
    assert loaded.use_provider_gateway is True


def test_load_creates_default(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.gateway_api_models
    assert store.path.exists()


def test_mcp_servers_roundtrip_and_reject_bad(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(
        mcp_servers={
            "github": McpServerConfig(command="npx", args=["-y", "demo"]),
            "linear": McpServerConfig(url="https://mcp.linear.app/mcp", enabled=False),
        }
    )
    store.save(cfg)
    loaded = store.load()
    assert loaded.mcp_servers["github"].command == "npx"
    assert loaded.mcp_servers["github"].enabled is True
    assert loaded.mcp_servers["linear"].enabled is False
    assert loaded.mcp_servers["github"].transport == "stdio"
    assert loaded.mcp_servers["linear"].transport == "http"
    assert loaded.mcp_servers["github"].tool_timeout_sec == 120
    sse = McpServerConfig(url="https://x.example/mcp", transport="sse")
    assert sse.transport == "sse"
    assert McpServerConfig(url="https://x.example/sse").transport == "sse"
    with pytest.raises(ValueError, match="invalid mcp server name"):
        AppConfig(mcp_servers={"bad name": {"command": "npx"}})
    with pytest.raises(ValueError, match="command or url"):
        McpServerConfig(command="npx", url="https://x.example/mcp")
    with pytest.raises(ValueError, match="command or url"):
        McpServerConfig()


def test_first_run_creates_project_settings_with_all_fields(tmp_path: Path):
    store = ConfigStore.for_cwd(tmp_path)
    cfg = store.load()
    settings = tmp_path / ".b3code" / "config.json"
    assert settings.exists()
    payload = json.loads(settings.read_text())
    assert payload == cfg.model_dump(mode="json")
    assert set(payload) == set(AppConfig.model_fields)


def test_first_run_writes_gateway_and_exclude_defaults(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    payload = json.loads(store.path.read_text())
    assert payload["exclude_directories"] == DEFAULT_EXCLUDE_DIRECTORIES
    assert payload["exclude_extensions"] == []
    assert payload["gateway_api_key"] == ""
    assert payload["gateway_api_endpoint"] == ""
    assert payload["gateway_api_models"] == ["gpt-4o"]
    assert cfg.exclude_directories == DEFAULT_EXCLUDE_DIRECTORIES


def test_load_adds_missing_exclude_directories(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"gateway_api_models": ["m1"], "exclude_extensions": [".log"]}\n'
    )
    loaded = ConfigStore(path).load()
    assert loaded.exclude_directories == DEFAULT_EXCLUDE_DIRECTORIES
    payload = json.loads(path.read_text())
    assert payload["exclude_directories"] == DEFAULT_EXCLUDE_DIRECTORIES


def test_load_adds_missing_exclude_extensions(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"gateway_api_models": ["m1"], "exclude_directories": ["dist"]}\n'
    )
    loaded = ConfigStore(path).load()
    assert loaded.exclude_extensions == []
    payload = json.loads(path.read_text())
    assert payload["exclude_extensions"] == []


def test_exclude_fields_normalize_on_load():
    cfg = AppConfig(
        exclude_directories=[" dist ", "", " node_modules "],
        exclude_extensions=["PYC", ".Log", "  "],
    )
    assert cfg.exclude_directories == ["dist", "node_modules"]
    assert cfg.exclude_extensions == [".pyc", ".log"]

