import json
from pathlib import Path

import pytest

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore


def test_select_model_moves_to_front():
    cfg = AppConfig(api_models=["a", "b", "c"])
    cfg.select_model("c")
    assert cfg.api_models == ["c", "a", "b"]
    assert cfg.selected_model == "c"


def test_select_unknown_model():
    cfg = AppConfig(api_models=["a"])
    with pytest.raises(ValueError):
        cfg.select_model("nope")


def test_legacy_json_defaults_gateway(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"api_key": "k", "api_endpoint": "https://x/", "api_models": ["m1"]}\n'
    )
    loaded = ConfigStore(path).load()
    assert loaded.use_provider_gateway is True
    assert loaded.selected_model == "m1"
    assert loaded.shell_allowed_paths == []
    assert loaded.accent == "#c9a227"


def test_accent_rejects_bad_hex():
    assert AppConfig(accent="red").accent == "#c9a227"
    assert AppConfig(accent="#fff").accent == "#fff"
    assert AppConfig(accent="#c9a227").accent == "#c9a227"


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
