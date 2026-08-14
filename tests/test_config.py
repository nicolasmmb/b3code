import json
from pathlib import Path

import pytest

from b3code.config.schema import THEME_COLOR_DEFAULTS, AppConfig, github_dark_theme
from b3code.config.service import ConfigService
from b3code.config.store import ConfigStore


def test_select_model_moves_to_front(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["a", "b", "c"])
    store.save(cfg)
    service = ConfigService(store, cfg)
    service.select_model("c")
    assert cfg.api_models == ["c", "a", "b"]
    assert cfg.selected_model == "c"


def test_select_unknown_model(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["a"])
    store.save(cfg)
    service = ConfigService(store, cfg)
    with pytest.raises(ValueError):
        service.select_model("nope")


def test_legacy_json_defaults_gateway(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"api_key": "k", "api_endpoint": "https://x/", "api_models": ["m1"]}\n'
    )
    loaded = ConfigStore(path).load()
    assert loaded.use_provider_gateway is True
    assert loaded.selected_model == "m1"
    assert loaded.shell_allowed_paths == []
    assert loaded.accent == "#00b0e6"
    assert loaded.selected_theme == "b3code"
    assert loaded.theme.name == "b3code"
    assert loaded.multiline is True


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
    assert cfg.theme.model_dump(exclude={"name"}) == THEME_COLOR_DEFAULTS
    github = github_dark_theme()
    saved = next(item for item in cfg.themes if item.name == "github-dark")
    assert saved.background == "#0d1117"
    assert saved.accent == "#58a6ff"
    assert saved.model_dump() == github.model_dump()


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
    cfg = AppConfig(api_key="k", api_endpoint="https://x/openai/v1/", api_models=["m1"])
    store.save(cfg)
    loaded = store.load()
    assert loaded.api_key == "k"
    assert loaded.selected_model == "m1"
    assert loaded.use_provider_gateway is True


def test_load_creates_default(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.api_models
    assert store.path.exists()


def test_first_run_creates_project_settings_with_all_fields(tmp_path: Path):
    store = ConfigStore.for_cwd(tmp_path)
    cfg = store.load()
    settings = tmp_path / ".b3code" / "config.json"
    assert settings.exists()
    payload = json.loads(settings.read_text())
    assert payload == cfg.model_dump(mode="json")
    assert set(payload) == set(AppConfig.model_fields)
