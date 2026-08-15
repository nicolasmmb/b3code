"""Barra superior: cwd no estilo Grok, modelo, badge de plan."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from b3code.config.schema import thinking_badge

_HEADS = "refs/heads/"
_POWERLINE_BRANCH = "\ue0a0"


@dataclass(frozen=True)
class GitLabel:
    branch: str
    worktree: bool


class TopBar(Horizontal):
    def __init__(self, cwd: Path, model: str, thinking: str = "off", **kwargs) -> None:
        super().__init__(id="top-bar", **kwargs)
        self._cwd = short_cwd(cwd)
        self._git = git_label(cwd)
        self._model = model
        self._thinking = thinking

    def compose(self) -> ComposeResult:
        if self._git is not None:
            yield Static(f"{branch_icon()} {self._git.branch}", id="git-branch")
        if self._git is not None and self._git.worktree:
            yield Static("worktree", id="worktree-flag")
        yield Static(self._cwd, id="cwd")
        yield Static(self._model, id="model-label")
        yield Static("", id="think-flag")
        yield Static("", id="mode-flag")

    def on_mount(self) -> None:
        self.set_thinking(self._thinking)

    def set_model(self, name: str) -> None:
        self.query_one("#model-label", Static).update(name)

    def set_thinking(self, level: str) -> None:
        self._thinking = level
        _set_flag(self.query_one("#think-flag", Static), thinking_badge(level))

    def set_plan_badge(self, active: bool) -> None:
        _set_flag(self.query_one("#mode-flag", Static), "plan" if active else "")


def _set_flag(flag: Static, text: str) -> None:
    if not text:
        flag.update("")
        flag.display = False
        return
    flag.update(text)
    flag.display = True


def short_cwd(cwd: Path, home: Path | None = None) -> str:
    """Encurta `$HOME/...` para `~/...`, como o Grok Build."""
    home = (home or Path.home()).resolve()
    try:
        rel = cwd.resolve().relative_to(home)
    except ValueError:
        return str(cwd)
    if str(rel) == ".":
        return "~"
    return f"~/{rel}"


def branch_icon() -> str:
    """Powerline ``; `B3CODE_NERD_FONTS=0` força o fallback ASCII."""
    if os.environ.get("B3CODE_NERD_FONTS") == "0":
        return "git"
    return _POWERLINE_BRANCH


def git_label(cwd: Path) -> GitLabel | None:
    """Branch e worktree lidos do filesystem — sem subprocess."""
    git = _find_git(cwd)
    if git is None:
        return None
    path, worktree = git
    return GitLabel(branch=_branch_from_gitdir(path), worktree=worktree)


def _find_git(cwd: Path) -> tuple[Path, bool] | None:
    current = cwd.resolve()
    for directory in (current, *current.parents):
        marker = directory / ".git"
        if marker.is_file():
            gitdir = _gitdir_from_file(marker)
            return (gitdir or marker, True)
        if marker.is_dir():
            return marker, False
    return None


def _gitdir_from_file(gitfile: Path) -> Path | None:
    try:
        text = gitfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.lower().startswith("gitdir:"):
        return None
    raw = Path(text.split(":", 1)[1].strip())
    if not raw.is_absolute():
        raw = (gitfile.parent / raw).resolve()
    return raw


def _branch_from_gitdir(gitdir: Path) -> str:
    try:
        text = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "detached"
    if not text.startswith("ref:"):
        return "detached"
    ref = text[4:].strip()
    if ref.startswith(_HEADS):
        name = ref[len(_HEADS) :]
        return name or "detached"
    return ref.rsplit("/", 1)[-1] or "detached"
