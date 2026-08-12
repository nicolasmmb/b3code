from pathlib import Path

import pytest

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore


def test_select_model_moves_to_front():
    cfg = AppConfig(api_models=["a", "b", "c"])
    cfg.select_model("c")
    assert cfg.api_models == ["c", "a", "b"]
    assert cfg.model == "c"


def test_select_unknown_model():
    cfg = AppConfig(api_models=["a"])
    with pytest.raises(ValueError):
        cfg.select_model("nope")


def test_roundtrip(tmp_path: Path):
    path = tmp_path / ".b3code" / "config.json"
    store = ConfigStore(path)
    cfg = AppConfig(api_key="k", api_endpoint="https://x/openai/v1/", api_models=["m1"])
    store.save(cfg)
    loaded = store.load()
    assert loaded.api_key == "k"
    assert loaded.model == "m1"


def test_load_creates_default(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.api_models
    assert store.path.exists()
