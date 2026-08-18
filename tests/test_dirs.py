"""Resolvedor do diretório central por SO (monkeypatch) + chave de projeto + migração.

Os ramos de SO rodam em qualquer host via monkeypatch dos helpers
`dirs._windows()` / `dirs._macos()` e das env vars correspondentes.
"""

import json
from pathlib import Path

from b3code.config import dirs as dirs_mod
from b3code.config.dirs import (
    b3code_home,
    legacy_project_dir,
    project_dir,
    project_key,
)
from b3code.config.store import ConfigStore
from b3code.container import AppContainer, migrate_legacy
from b3code.services.plan import PlanMode
from b3code.services.session import SessionStore

# --- B3CODE_HOME -----------------------------------------------------------


def test_b3code_home_env_var_wins(tmp_path: Path, monkeypatch):
    target = tmp_path / "custom"
    monkeypatch.setenv("B3CODE_HOME", str(target))
    assert b3code_home() == target.resolve()


def test_b3code_home_env_var_expands_tilde(tmp_path: Path, monkeypatch):
    home = tmp_path / "fake-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("B3CODE_HOME", "~/b3code")
    assert b3code_home() == (home / "b3code").resolve()


def _force_platform(monkeypatch, windows: bool, macos: bool) -> None:
    monkeypatch.setattr(dirs_mod, "_windows", lambda: windows)
    monkeypatch.setattr(dirs_mod, "_macos", lambda: macos)


def test_b3code_home_windows_appdata(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    _force_platform(monkeypatch, windows=True, macos=False)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    assert b3code_home() == (appdata / "b3code").resolve()


def test_b3code_home_windows_localappdata_fallback(tmp_path: Path, monkeypatch):
    local = tmp_path / "AppData" / "Local"
    _force_platform(monkeypatch, windows=True, macos=False)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert b3code_home() == (local / "b3code").resolve()


def test_b3code_home_windows_home_fallback(tmp_path: Path, monkeypatch):
    _force_platform(monkeypatch, windows=True, macos=False)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert b3code_home() == Path.home() / "b3code"


def test_b3code_home_macos(tmp_path: Path, monkeypatch):
    _force_platform(monkeypatch, windows=False, macos=True)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    assert b3code_home() == (
        Path.home() / "Library" / "Application Support" / "b3code"
    )


def test_b3code_home_xdg_config_home(tmp_path: Path, monkeypatch):
    xdg = tmp_path / "xdg"
    _force_platform(monkeypatch, windows=False, macos=False)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert b3code_home() == (xdg / "b3code").resolve()


def test_b3code_home_default_dot_config(tmp_path: Path, monkeypatch):
    _force_platform(monkeypatch, windows=False, macos=False)
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert b3code_home() == Path.home() / ".config" / "b3code"


# --- project_key / project_dir ---------------------------------------------


def test_project_key_stable_and_filesystem_safe(tmp_path: Path):
    cwd = tmp_path / "Meu Projeto"
    cwd.mkdir()
    key = project_key(cwd)
    assert key == project_key(cwd)
    assert len(key) <= 60
    assert "/" not in key
    assert "\\" not in key
    assert " " not in key
    assert all(ord(ch) < 128 for ch in key)


def test_project_key_differs_for_different_cwds(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert project_key(a) != project_key(b)


def test_project_key_symbolic_name_uses_root_slug(tmp_path: Path):
    weird = tmp_path / "!!!"
    weird.mkdir()
    assert project_key(weird).startswith("root-")


def test_project_key_case_insensitive_on_windows(tmp_path: Path, monkeypatch):
    # FS com case-insensitive (APFS) não permite os dois dirs; resolve() sem
    # strict funciona para paths que ainda não existem.
    monkeypatch.setattr(dirs_mod, "_windows", lambda: True)
    upper = tmp_path / "MyProj"
    lower = tmp_path / "myproj"
    assert project_key(upper) == project_key(lower)


def test_project_dir_lives_under_home(tmp_path: Path):
    assert project_dir(tmp_path).is_relative_to(b3code_home())
    assert legacy_project_dir(tmp_path) == (tmp_path.resolve() / ".b3code")


def test_plan_path_and_session_store_centralized(tmp_path: Path):
    assert PlanMode(tmp_path).plan_path == project_dir(tmp_path) / "plan.md"
    assert SessionStore.for_project(tmp_path).path == (
        project_dir(tmp_path) / "sessions.json"
    )


# --- migração --------------------------------------------------------------


def _write_legacy(tmp_path: Path, config: dict | None = None) -> Path:
    legacy = tmp_path / ".b3code"
    legacy.mkdir()
    if config is not None:
        (legacy / "config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
    return legacy


def test_migrate_legacy_promotes_config_and_files(tmp_path: Path):
    _write_legacy(
        tmp_path,
        {"gateway_api_key": "k", "gateway_api_endpoint": "https://x/v1/"},
    )
    (tmp_path / ".b3code" / "plan.md").write_text("# plan\n", encoding="utf-8")
    (tmp_path / ".b3code" / "sessions.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / ".b3code" / "attachments").mkdir()
    (tmp_path / ".b3code" / "attachments" / "a.png").write_bytes(b"png")

    migrate_legacy(tmp_path)

    assert ConfigStore.for_global().load().gateway_api_key == "k"
    project = project_dir(tmp_path)
    assert (project / "plan.md").read_text(encoding="utf-8") == "# plan\n"
    assert (project / "sessions.json").exists()
    assert (project / "attachments" / "a.png").read_bytes() == b"png"
    # a pasta legada não é apagada
    assert (tmp_path / ".b3code" / "config.json").exists()


def test_migrate_legacy_second_boot_keeps_central(tmp_path: Path):
    _write_legacy(
        tmp_path,
        {"gateway_api_key": "old", "gateway_api_endpoint": "https://x/v1/"},
    )
    (tmp_path / ".b3code" / "plan.md").write_text("# v1\n", encoding="utf-8")
    migrate_legacy(tmp_path)
    # legado muda depois do 1º boot
    (tmp_path / ".b3code" / "config.json").write_text(
        json.dumps({"gateway_api_key": "new"}), encoding="utf-8"
    )
    (tmp_path / ".b3code" / "plan.md").write_text("# v2\n", encoding="utf-8")
    migrate_legacy(tmp_path)
    assert ConfigStore.for_global().load().gateway_api_key == "old"
    assert (project_dir(tmp_path) / "plan.md").read_text() == "# v1\n"


def test_migrate_legacy_invalid_config_does_not_break(tmp_path: Path):
    legacy = tmp_path / ".b3code"
    legacy.mkdir()
    (legacy / "config.json").write_text("{not json", encoding="utf-8")
    migrate_legacy(tmp_path)
    assert ConfigStore.for_global().load().gateway_api_key == ""


def test_build_migrates_legacy_on_first_boot(tmp_path: Path):
    _write_legacy(
        tmp_path,
        {"gateway_api_key": "k", "gateway_api_endpoint": "https://x/v1/"},
    )
    (tmp_path / ".b3code" / "plan.md").write_text("# plan\n", encoding="utf-8")
    container = AppContainer.build(tmp_path)
    assert container.config.gateway_api_key == "k"
    assert (project_dir(tmp_path) / "plan.md").exists()
    # a pasta legada fica intacta
    assert (tmp_path / ".b3code" / "config.json").exists()
    # 2º boot: usa só o central
    container2 = AppContainer.build(tmp_path)
    assert container2.config.gateway_api_key == "k"
