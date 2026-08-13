from pathlib import Path

from pydantic_ai.models.test import TestModel

from b3code.commands.apply import apply_suggestion, decide_submit
from b3code.commands.registry import CommandRegistry
from b3code.commands.types import Suggestion
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore


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


def _arg(value: str) -> Suggestion:
    return Suggestion(value=value, label=value, hint="arg", kind="arg", consume=True)


def _cmd(value: str, *, consume: bool = False) -> Suggestion:
    return Suggestion(value=value, label=value, hint="cmd", kind="cmd", consume=consume)


def test_apply_model_replaces_prefix():
    item = _arg("anthropic:claude-fable-5")
    text, _ = apply_suggestion("/model claude-fable", 19, item)
    assert text == "/model anthropic:claude-fable-5"
    again, _ = apply_suggestion(text, len(text), item)
    assert again == text
    spaced, _ = apply_suggestion(text + " ", len(text) + 1, item)
    assert spaced == text


def test_apply_session_keeps_command():
    item = _arg("abc123")
    text, _ = apply_suggestion("/resume", 7, item)
    assert text == "/resume abc123"
    text, _ = apply_suggestion("/resume ", 8, item)
    assert text == "/resume abc123"


def test_decide_submit_apply_then_execute():
    item = _arg("gpt-4o")
    first = decide_submit("/model gpt", 10, item)
    assert first.kind == "apply"
    assert first.line == "/model gpt-4o"
    second = decide_submit(first.line, len(first.line), item)
    assert second.kind == "execute"
    assert second.line == "/model gpt-4o"


def test_decide_submit_help_executes():
    item = _cmd("/help", consume=True)
    decision = decide_submit("/he", 3, item)
    assert decision.kind == "apply"
    assert decision.line == "/help"
    done = decide_submit("/help", 5, item)
    assert done.kind == "execute"


def test_complete_resume_lists_sessions(tmp_path: Path):
    sessions = SessionStore(tmp_path / "sessions.json")
    sid = sessions.current_id
    sessions.new()
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(api_models=["gpt-4o"])
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    ids = [s.value for s in reg.complete("/resume")]
    assert sid in ids
    assert sessions.current_id in ids
    assert all(s.consume for s in reg.complete("/resume "))
    filtered = [s.value for s in reg.complete(f"/resume {sid[:2]}")]
    assert sid in filtered


def test_complete_partial_still_lists_command(tmp_path: Path):
    reg = _registry(tmp_path)
    labels = [s.label for s in reg.complete("/mo")]
    assert labels == ["/model"]
    assert all(not s.consume for s in reg.complete("/mo"))
