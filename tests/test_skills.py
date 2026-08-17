"""Skills: descoberta, parser, comandos, tools e chips."""

from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel

from b3code.commands.effects import ReloadSkills, RunPrompt
from b3code.commands.registry import CommandRegistry
from b3code.config.schema import AppConfig, SkillSettings
from b3code.config.store import ConfigStore
from b3code.services.chat import ChatService
from b3code.services.session import SessionStore
from b3code.services.skills import (
    MAX_SKILL_BODY,
    SkillIndex,
    normalize_skill_name,
    parse_skill_file,
    skill_from_file,
)
from b3code.tools.skills import skills_toolset
from b3code.utils.prompt import (
    build_user_content,
    display_user_content,
    replace_skill_blocks,
)


def _write_skill(root: Path, name: str, body: str = "Do the steps.\n") -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


def _index(
    cwd: Path,
    settings: SkillSettings | None = None,
    home: Path | None = None,
) -> SkillIndex:
    return SkillIndex(cwd, settings, home=home or cwd / "home")


def _registry(cwd: Path, home: Path | None = None) -> CommandRegistry:
    store = ConfigStore(cwd / "config.json")
    cfg = AppConfig(gateway_api_models=["gpt-4o"])
    store.save(cfg)
    sessions = SessionStore(cwd / "sessions.json")
    skills = _index(cwd, home=home)
    chat = ChatService(cfg, sessions, cwd, model=TestModel(), skills=skills)
    return CommandRegistry.build(store, cfg, sessions, chat, skills=skills)


# --- config schema -------------------------------------------------------


def test_skills_settings_defaults():
    cfg = AppConfig()
    assert cfg.skills.enabled is True
    assert cfg.skills.extra_paths == []
    assert cfg.skills.ignore == []
    assert cfg.skills.disabled == []


def test_old_config_without_skills_loads():
    raw = '{"gateway_api_models": ["gpt-4o"], "selected_model": "gpt-4o"}'
    cfg = AppConfig.model_validate_json(raw)
    assert cfg.skills.enabled is True
    assert cfg.selected_model == "gpt-4o"


# --- descoberta e prioridade ---------------------------------------------


def test_project_beats_user(tmp_path: Path):
    home = tmp_path / "home"
    proj_skill = _write_skill(
        tmp_path / ".b3code" / "skills",
        "commit",
        "---\nname: commit\ndescription: project\n---\nPROJ",
    )
    _write_skill(
        home / ".b3code" / "skills",
        "commit",
        "---\nname: commit\ndescription: user\n---\nUSER",
    )
    idx = _index(tmp_path, home=home)
    skills = idx.skills()
    assert len(skills) == 1
    assert skills[0].scope == "project"
    assert skills[0].body.strip() == "PROJ"
    assert skills[0].path == proj_skill


def test_grok_and_claude_compat_project_and_user(tmp_path: Path):
    home = tmp_path / "home"
    _write_skill(tmp_path / ".grok" / "skills", "grokproj")
    _write_skill(tmp_path / ".claude" / "skills", "claudeproj")
    _write_skill(home / ".grok" / "skills", "grokuser")
    _write_skill(home / ".claude" / "skills", "claudeuser")
    idx = _index(tmp_path, home=home)
    by_name = {s.name: s.scope for s in idx.skills()}
    assert by_name == {
        "grokproj": "project",
        "claudeproj": "project",
        "grokuser": "user",
        "claudeuser": "user",
    }


def test_extra_paths_file_and_recursive(tmp_path: Path):
    home = tmp_path / "home"
    direct = tmp_path / "extra" / "SKILL.md"
    direct.parent.mkdir(parents=True)
    direct.write_text("---\nname: extrafile\n---\nBODY", encoding="utf-8")
    nested = tmp_path / "extra2" / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: extranested\n---\nBODY", encoding="utf-8"
    )
    idx = _index(
        tmp_path,
        SkillSettings(extra_paths=[str(direct), str(tmp_path / "extra2")]),
        home=home,
    )
    names = {(s.name, s.scope) for s in idx.skills()}
    assert ("extrafile", "config") in names
    assert ("extranested", "config") in names


def test_extra_path_tilde_expands(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    _write_skill(home / ".b3code" / "skills", "tilde")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    idx = SkillIndex(
        tmp_path, SkillSettings(extra_paths=["~/.b3code/skills/tilde"])
    )
    assert idx.get("tilde") is not None


# --- parser e fallbacks ---------------------------------------------------


def test_frontmatter_fields(tmp_path: Path):
    path = _write_skill(
        tmp_path / ".b3code" / "skills",
        "commit",
        """---
name: commit
description: create a commit
when-to-use: user asks to commit
argument-hint: [message]
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - write_file
  - run_command
---

Body here
""",
    )
    skill = skill_from_file(path, "project")
    assert skill is not None
    assert skill.name == "commit"
    assert skill.description == "create a commit"
    assert skill.when_to_use == "user asks to commit"
    assert skill.argument_hint == "[message]"
    assert skill.allowed_tools == ("write_file", "run_command")
    assert skill.user_invocable is True
    assert skill.disable_model_invocation is False
    assert skill.body.strip() == "Body here"


def test_frontmatter_comma_list_and_false_bools(tmp_path: Path):
    path = _write_skill(
        tmp_path / ".b3code" / "skills",
        "review",
        """---
name: review
description: do a review, report issues
user-invocable: no
disable-model-invocation: yes
allowed-tools: read_file, grep
---

Body
""",
    )
    skill = skill_from_file(path, "project")
    assert skill.description == "do a review, report issues"
    assert skill.user_invocable is False
    assert skill.disable_model_invocation is True
    assert skill.allowed_tools == ("read_file", "grep")


def test_fallback_name_and_description(tmp_path: Path):
    path = _write_skill(
        tmp_path / ".b3code" / "skills",
        "My Skill!",
        "First paragraph is the description.\n\nReal body.\n",
    )
    skill = skill_from_file(path, "project")
    assert skill.name == "my-skill"
    assert skill.description == "First paragraph is the description."
    assert skill.body == "First paragraph is the description.\n\nReal body.\n"


def test_frontmatter_without_closing_is_whole_body(tmp_path: Path):
    path = _write_skill(
        tmp_path / ".b3code" / "skills",
        "broken",
        "---\nname: broken\ndescription: x\n",
    )
    meta, body = parse_skill_file(path)
    assert meta == {}
    assert body.startswith("---")
    skill = skill_from_file(path, "project")
    assert skill.name == "broken"
    assert skill.body == body


def test_normalize_skill_name():
    assert normalize_skill_name("My Skill!") == "my-skill"
    assert normalize_skill_name("  --commit--  ") == "commit"
    assert len(normalize_skill_name("x" * 100)) <= 64


def test_body_truncated(tmp_path: Path):
    path = _write_skill(
        tmp_path / ".b3code" / "skills",
        "big",
        "x" * (MAX_SKILL_BODY + 100),
    )
    skill = skill_from_file(path, "project")
    assert len(skill.body) == MAX_SKILL_BODY


# --- ignore / disabled / enabled -----------------------------------------


def test_ignore_hides_path(tmp_path: Path):
    home = tmp_path / "home"
    _write_skill(tmp_path / ".b3code" / "skills", "commit")
    _write_skill(home / ".b3code" / "skills", "commit")
    idx = _index(
        tmp_path,
        SkillSettings(ignore=[str(tmp_path / ".b3code" / "skills")]),
        home=home,
    )
    skills = idx.skills()
    assert len(skills) == 1
    assert skills[0].scope == "user"


def test_disabled_marked_but_not_available(tmp_path: Path):
    _write_skill(tmp_path / ".b3code" / "skills", "commit")
    idx = _index(tmp_path, SkillSettings(disabled=["commit"]))
    assert idx.skills() == []
    all_skills = idx.skills(include_disabled=True)
    assert len(all_skills) == 1
    assert all_skills[0].disabled is True


def test_enabled_false_empty(tmp_path: Path):
    _write_skill(tmp_path / ".b3code" / "skills", "commit")
    idx = _index(tmp_path, SkillSettings(enabled=False))
    assert idx.skills() == []
    assert idx.catalog() == "no skills available"


def test_catalog_and_load(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "commit",
        "---\nname: commit\ndescription: create a commit\nwhen-to-use: user asks to commit\n---\nSteps\n",
    )
    idx = _index(tmp_path)
    assert "commit — create a commit (when: user asks to commit)" in idx.catalog()
    loaded = idx.load("commit")
    assert loaded.startswith('<skill name="commit" scope="project">')
    assert "Steps" in loaded
    assert loaded.rstrip().endswith("</skill>")
    assert idx.load("nope") == ""


# --- registry -------------------------------------------------------------


def test_skill_command_in_autocomplete_and_run_prompt(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "commit",
        "---\nname: commit\ndescription: create a commit\n---\n1. git status\n2. commit\n",
    )
    reg = _registry(tmp_path)
    names = [s.label for s in reg.complete("/")]
    assert "/commit" in names
    assert "/skills" in names
    result = reg.execute("/commit fix the build")
    assert isinstance(result.effect, RunPrompt)
    assert "Task: fix the build" in result.effect.text
    assert '<skill name="commit" scope="project">' in result.effect.text
    assert "1. git status" in result.effect.text


def test_skill_command_no_args_sends_follow(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills", "commit", "---\nname: commit\n---\nSteps\n"
    )
    reg = _registry(tmp_path)
    result = reg.execute("/commit")
    assert isinstance(result.effect, RunPrompt)
    assert "Follow the skill instructions now." in result.effect.text


def test_collision_qualifies_skill(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "model",
        "---\nname: model\ndescription: a skill named model\n---\nMODEL BODY\n",
    )
    reg = _registry(tmp_path)
    names = [s.label for s in reg.complete("/")]
    assert "/model" in names  # nativo continua
    assert "/project:model" in names  # skill qualificada
    native = reg.execute("/model")
    assert not isinstance(native.effect, RunPrompt)
    skill_run = reg.execute("/project:model do it")
    assert isinstance(skill_run.effect, RunPrompt)
    assert "MODEL BODY" in skill_run.effect.text
    assert "Task: do it" in skill_run.effect.text


def test_user_invocable_false_not_installed(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "hidden",
        "---\nname: hidden\nuser-invocable: false\n---\nBODY\n",
    )
    reg = _registry(tmp_path)
    names = [s.label for s in reg.complete("/")]
    assert "/hidden" not in names
    result = reg.execute("/hidden")
    assert "unknown command" in result.message


def test_skills_list_reload_paths(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills", "commit", "---\nname: commit\n---\nBODY\n"
    )
    reg = _registry(tmp_path)
    listed = reg.execute("/skills")
    assert "commit  project" in listed.message
    assert listed.effect is None
    reloaded = reg.execute("/skills reload")
    assert isinstance(reloaded.effect, ReloadSkills)
    paths = reg.execute("/skills paths")
    assert ".b3code/skills" in paths.message
    assert "project" in paths.message


def test_skills_reload_installs_new_command(tmp_path: Path):
    reg = _registry(tmp_path)
    assert "/fresh" not in [s.label for s in reg.complete("/")]
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "fresh",
        "---\nname: fresh\n---\nFRESH BODY\n",
    )
    reg.skills.scan()  # o handler de /skills reload faz o scan; a UI chama reload_skills
    reg.reload_skills()
    names = [s.label for s in reg.complete("/")]
    assert "/fresh" in names
    result = reg.execute("/fresh")
    assert isinstance(result.effect, RunPrompt)
    assert "FRESH BODY" in result.effect.text


# --- toolset --------------------------------------------------------------


def _tools(index: SkillIndex) -> dict:
    return {
        name: tool.function for name, tool in skills_toolset(index).tools.items()
    }


def test_toolset_list_and_load(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "commit",
        "---\nname: commit\ndescription: create a commit\nwhen-to-use: user asks to commit\n---\nSteps\n",
    )
    fns = _tools(_index(tmp_path))
    assert "list_skills" in fns and "load_skill" in fns
    catalog = fns["list_skills"]()
    assert "commit — create a commit (when: user asks to commit)" in catalog
    loaded = fns["load_skill"]("commit")
    assert '<skill name="commit"' in loaded
    with pytest.raises(ModelRetry, match="unknown or disabled"):
        fns["load_skill"]("nope")


def test_toolset_hides_model_invocation_disabled(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills",
        "secret",
        "---\nname: secret\ndescription: hidden\ndisable-model-invocation: true\n---\nBODY\n",
    )
    fns = _tools(_index(tmp_path))
    assert "secret" not in fns["list_skills"]()
    with pytest.raises(ModelRetry, match="unknown or disabled"):
        fns["load_skill"]("secret")


def test_toolset_skips_disabled(tmp_path: Path):
    _write_skill(
        tmp_path / ".b3code" / "skills", "commit", "---\nname: commit\n---\nBODY\n"
    )
    fns = _tools(_index(tmp_path, SkillSettings(disabled=["commit"])))
    with pytest.raises(ModelRetry, match="unknown or disabled"):
        fns["load_skill"]("commit")


# --- prompt / chips -------------------------------------------------------


def test_replace_skill_blocks_makes_chip():
    text = (
        '<skill name="commit" scope="project">\n'
        "Steps\n"
        "</skill>\n\n"
        "Task: fix the build"
    )
    replaced = replace_skill_blocks(text)
    assert "[SKILL - commit]" in replaced
    assert "<skill" not in replaced
    assert "Steps" not in replaced
    assert "Task: fix the build" in replaced


def test_display_user_content_shows_chip():
    text = (
        '<skill name="commit" scope="project">\n'
        "Steps\n"
        "</skill>\n\n"
        "Task: fix the build"
    )
    shown = display_user_content(text)
    assert "[SKILL - commit]" in shown
    assert "Steps" not in shown


def test_build_user_content_keeps_skill_block(tmp_path: Path):
    text = (
        '<skill name="commit" scope="project">\n'
        "Steps\n"
        "</skill>\n\n"
        "Task: fix the build"
    )
    content = build_user_content(text, tmp_path, lambda rel: "")
    assert isinstance(content, str)
    assert '<skill name="commit"' in content
    assert "</skill>" in content
