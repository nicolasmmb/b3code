from pathlib import Path

from b3code.commands.registry import CommandRegistry
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore
from pydantic_ai.models.test import TestModel


def _registry(tmp_path: Path) -> CommandRegistry:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["gpt-4o", "gpt-4o-mini"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    return CommandRegistry.build(store, cfg, sessions, chat)


def test_complete_root(tmp_path: Path):
    reg = _registry(tmp_path)
    names = [s.label for s in reg.complete("/")]
    assert "/help" in names
    assert "/model" in names


def test_complete_model_names(tmp_path: Path):
    reg = _registry(tmp_path)
    names = [s.value for s in reg.complete("/model ")]
    assert "gpt-4o" in names
    assert "gpt-4o-mini" in names


def test_execute_help(tmp_path: Path):
    reg = _registry(tmp_path)
    result = reg.execute("/help")
    assert "/new" in result.message


def test_execute_model_switch(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["gpt-4o", "gpt-4o-mini"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    result = reg.execute("/model gpt-4o-mini")
    assert result.action == "refresh"
    assert cfg.selected_model == "gpt-4o-mini"
    assert store.load().selected_model == "gpt-4o-mini"


def test_gateway_toggle(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    assert cfg.use_provider_gateway is True
    result = reg.execute("/gateway off")
    assert result.action == "refresh"
    assert cfg.use_provider_gateway is False
    assert store.load().use_provider_gateway is False


def test_complete_catalog_models(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(use_provider_gateway=False, api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    names = [s.value for s in reg.complete("/model openai:")]
    assert any(n.startswith("openai:") for n in names)
