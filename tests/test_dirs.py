"""Resolvedor do diretório central (`~/.b3code`) + chave de projeto.

Os testes rodam em qualquer host via monkeypatch da env `B3CODE_HOME`
(fixture autouse) ou de `HOME`/`USERPROFILE`.
"""

from pathlib import Path

from b3code.config import dirs as dirs_mod
from b3code.config.dirs import b3code_home, project_dir, project_key
from b3code.config.store import ConfigStore
from b3code.container import AppContainer
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


def test_b3code_home_default_is_dot_b3code(tmp_path: Path, monkeypatch):
    home = tmp_path / "fake-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    assert b3code_home() == (home / ".b3code").resolve()


def test_b3code_home_ignores_platform_specific_dirs(tmp_path: Path, monkeypatch):
    """Mesmo resultado em Linux/macOS/Windows: `~/.b3code`."""
    home = tmp_path / "fake-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("B3CODE_HOME", raising=False)
    monkeypatch.setattr(dirs_mod, "_windows", lambda: True)
    assert b3code_home() == (home / ".b3code").resolve()
    monkeypatch.setattr(dirs_mod, "_windows", lambda: False)
    assert b3code_home() == (home / ".b3code").resolve()


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
    monkeypatch.setattr(dirs_mod, "_windows", lambda: True)
    upper = tmp_path / "MyProj"
    lower = tmp_path / "myproj"
    assert project_key(upper) == project_key(lower)


def test_project_dir_lives_under_home(tmp_path: Path):
    assert project_dir(tmp_path).is_relative_to(b3code_home())


def test_plan_path_and_session_store_centralized(tmp_path: Path):
    assert PlanMode(tmp_path).plan_path == project_dir(tmp_path) / "plan.md"
    assert SessionStore.for_project(tmp_path).path == (
        project_dir(tmp_path) / "sessions.json"
    )


# --- sem fallback legado --------------------------------------------------


def test_build_never_creates_local_b3code(tmp_path: Path):
    """1º boot grava tudo no central; `.b3code` nunca nasce no cwd."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    AppContainer.build(cwd)
    assert not (cwd / ".b3code").exists()
    assert ConfigStore.for_global().path.exists()
    assert project_dir(cwd).is_relative_to(b3code_home())
