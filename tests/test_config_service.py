from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.config.service import ConfigService
from b3code.config.store import ConfigStore


def _service(tmp_path: Path, **kwargs) -> ConfigService:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(**kwargs)
    store.save(cfg)
    return ConfigService(store, cfg)


def test_select_model_persists(tmp_path: Path):
    service = _service(tmp_path, api_models=["a", "b"])
    service.select_model("b")
    assert service.config.selected_model == "b"
    assert service.store.load().selected_model == "b"


def test_toggle_gateway(tmp_path: Path):
    service = _service(tmp_path, api_models=["a"])
    service.toggle_gateway(False)
    assert service.config.use_provider_gateway is False
    assert service.store.load().use_provider_gateway is False


def test_toggle_gateway_snaps_to_api_model(tmp_path: Path):
    service = _service(
        tmp_path,
        use_provider_gateway=False,
        api_models=["a"],
        selected_model="openai:gpt-4o",
    )
    service.toggle_gateway(True)
    assert service.config.selected_model == "a"


def test_set_multiline(tmp_path: Path):
    service = _service(tmp_path)
    assert service.config.multiline is True
    service.set_multiline(False)
    assert service.config.multiline is False
    assert service.store.load().multiline is False


def test_persist_allowed_path(tmp_path: Path):
    service = _service(tmp_path)
    path = Path("/tmp").resolve()
    service.persist_allowed_path(path)
    assert str(path) in service.config.shell_allowed_paths
    assert str(path) in service.store.load().shell_allowed_paths
