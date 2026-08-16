from pathlib import Path

from pydantic_ai.models.test import TestModel

from b3code.commands.apply import apply_suggestion, decide_submit
from b3code.commands.effects import (
    DoctorMcp,
    PlanOff,
    Refresh,
    RunPrompt,
    ShowPlanDoc,
)
from b3code.commands.parse import parse_mcp_add
from b3code.commands.registry import CommandRegistry
from b3code.commands.types import Suggestion
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore


def _registry(tmp_path: Path) -> CommandRegistry:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o", "gpt-4o-mini"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    return CommandRegistry.build(store, cfg, sessions, chat)


def test_complete_root(tmp_path: Path):
    reg = _registry(tmp_path)
    names = [s.label for s in reg.complete("/")]
    assert "/help" in names
    assert "/model" in names
    assert "/mcp" in names


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
    cfg = AppConfig(gateway_api_models=["gpt-4o", "gpt-4o-mini"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    result = reg.execute("/model gpt-4o-mini")
    assert isinstance(result.effect, Refresh)
    assert cfg.selected_model == "gpt-4o-mini"
    assert store.load().selected_model == "gpt-4o-mini"


def test_gateway_toggle(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    assert cfg.use_provider_gateway is True
    result = reg.execute("/gateway off")
    assert isinstance(result.effect, Refresh)
    assert cfg.use_provider_gateway is False
    assert store.load().use_provider_gateway is False


def test_theme_list_and_set(tmp_path: Path):
    reg = _registry(tmp_path)
    listed = reg.execute("/theme")
    assert "b3code" in listed.message
    assert "accent" in listed.message
    result = reg.execute("/theme update accent #DC143C")
    assert isinstance(result.effect, Refresh)
    assert "#DC143C" in result.message
    saved = reg.execute("/theme save crimson")
    assert isinstance(saved.effect, Refresh)
    switched = reg.execute("/theme set crimson")
    assert "crimson" in switched.message
    subs = [s.value for s in reg.complete("/theme ")]
    assert subs == ["set", "update", "save"] or set(subs) == {"set", "update", "save"}
    assert "accent" not in subs
    assert "b3code" not in subs
    names = [s.value for s in reg.complete("/theme set ")]
    assert "crimson" in names
    assert "b3code" in names
    tokens = [s.value for s in reg.complete("/theme update ")]
    assert "accent" in tokens
    assert "background" in tokens
    current = [s.value for s in reg.complete("/theme update accent ")]
    assert current == ["#DC143C"]


def test_theme_set_and_save_accept_spaces(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(
        gateway_api_models=["gpt-4o"],
        themes=[
            {"name": "B3 Light", "accent": "#1818b7"},
            {"name": "b3code"},
        ],
        selected_theme="b3code",
    )
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    listed = reg.execute("/theme")
    assert "B3 Light" in listed.message
    assert "b3-light" not in listed.message
    switched = reg.execute("/theme set B3 Light")
    assert "B3 Light" in switched.message
    assert cfg.selected_theme == "b3-light"
    shown = {s.label: s.value for s in reg.complete("/theme set ")}
    assert shown["B3 Light"] == "b3-light"
    saved = reg.execute("/theme save Tokyo Night")
    assert "Tokyo Night" in saved.message
    assert any(item.name == "tokyo-night" for item in cfg.themes)


def test_complete_catalog_models(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(use_provider_gateway=False, gateway_api_models=["gpt-4o"])
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


def test_apply_theme_child_does_not_repeat_command():
    item = Suggestion(
        value="set", label="set", hint="activate a saved theme", kind="arg", consume=False
    )
    spaced, _ = apply_suggestion("/theme ", 7, item)
    assert spaced == "/theme set "
    bare, _ = apply_suggestion("/theme", 6, item)
    assert bare == "/theme set "
    partial, _ = apply_suggestion("/theme s", 8, item)
    assert partial == "/theme set "


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
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
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


def test_multiline_toggle(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    assert "/multiline" in [s.label for s in reg.complete("/")]
    assert cfg.multiline is True
    toggled = reg.execute("/multiline")
    assert "off" in toggled.message
    assert cfg.multiline is False
    assert store.load().multiline is False
    on = reg.execute("/multiline on")
    assert "on" in on.message
    assert cfg.multiline is True
    off = reg.execute("/multiline off")
    assert "off" in off.message
    assert cfg.multiline is False
    bad = reg.execute("/multiline maybe")
    assert "usage" in bad.message


def test_mcp_add_enable_disable_remove(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    empty = reg.execute("/mcp")
    assert "no servers" in empty.message
    added = reg.execute("/mcp add github -- npx -y @modelcontextprotocol/server-github")
    assert isinstance(added.effect, Refresh)
    assert "github" in added.message
    listed = reg.execute("/mcp")
    assert "github  idle  stdio" in listed.message
    off = reg.execute("/mcp disable github")
    assert isinstance(off.effect, Refresh)
    assert store.load().mcp_servers["github"].enabled is False
    enabled = reg.execute("/mcp enable github")
    assert isinstance(enabled.effect, Refresh)
    assert store.load().mcp_servers["github"].enabled is True
    remote = reg.execute("/mcp add --transport http linear https://mcp.linear.app/mcp")
    assert isinstance(remote.effect, Refresh)
    assert store.load().mcp_servers["linear"].transport == "http"
    stream = reg.execute("/mcp add --transport sse events https://x.example/mcp")
    assert isinstance(stream.effect, Refresh)
    assert store.load().mcp_servers["events"].transport == "sse"
    names = [s.value for s in reg.complete("/mcp enable ")]
    assert "github" in names
    assert "linear" in names
    subs = [s.value for s in reg.complete("/mcp ")]
    assert set(subs) >= {"add", "remove", "enable", "disable", "doctor"}
    empty_root = tmp_path / "empty-doc"
    empty_root.mkdir()
    empty_doc = _registry(empty_root).execute("/mcp doctor")
    assert "no servers" in empty_doc.message
    assert empty_doc.effect is None
    missing = reg.execute("/mcp doctor missing")
    assert "unknown" in missing.message
    assert missing.effect is None
    one = reg.execute("/mcp doctor github")
    assert isinstance(one.effect, DoctorMcp)
    assert one.effect.names == ("github",)
    assert chat.mcp.connects == 0
    all_docs = reg.execute("/mcp doctor")
    assert isinstance(all_docs.effect, DoctorMcp)
    assert set(all_docs.effect.names) == {"github", "linear", "events"}
    docs = [s.value for s in reg.complete("/mcp doctor ")]
    assert "github" in docs
    gone = reg.execute("/mcp remove github")
    assert isinstance(gone.effect, Refresh)
    assert "github" not in store.load().mcp_servers
    assert chat.mcp.connects == 0


def test_parse_mcp_add_flags():
    stdio = parse_mcp_add(
        ("postgres", "-e", "DATABASE_URL=postgres://x", "--", "npx", "-y", "pg")
    )
    assert stdio.name == "postgres"
    assert stdio.command == "npx"
    assert stdio.args == ["-y", "pg"]
    assert stdio.env == {"DATABASE_URL": "postgres://x"}
    http = parse_mcp_add(
        (
            "--transport",
            "http",
            "api",
            "https://mcp.example.com/mcp",
            "--header",
            "Authorization=Bearer tok",
        )
    )
    assert http.url == "https://mcp.example.com/mcp"
    assert http.headers == {"Authorization": "Bearer tok"}


def test_plan_on_off_and_view(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(tmp_path / "sessions.json")
    chat = ChatService(cfg, sessions, tmp_path, model=TestModel())
    reg = CommandRegistry.build(store, cfg, sessions, chat)
    assert "/plan" in [s.label for s in reg.complete("/")]
    on = reg.execute("/plan")
    assert on.effect is None
    assert chat.plan.active is True
    empty = reg.execute("/view-plan")
    assert "no plan" in empty.message
    chat.plan.write("# hello\n")
    shown = reg.execute("/view-plan")
    assert isinstance(shown.effect, ShowPlanDoc)
    assert "hello" in shown.message
    with_prompt = reg.execute("/plan implement it")
    assert isinstance(with_prompt.effect, RunPrompt)
    assert with_prompt.effect.text == "implement it"
    off = reg.execute("/plan off")
    assert isinstance(off.effect, PlanOff)
    assert chat.plan.active is False
