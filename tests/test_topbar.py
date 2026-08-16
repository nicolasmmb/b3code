from pathlib import Path

from textual.widgets import Static

from b3code.config.schema import thinking_badge
from b3code.container import AppContainer
from b3code.ui.app import B3App
from b3code.ui.widgets.topbar import branch_icon, git_label, short_cwd


def test_short_cwd_home_and_child(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert short_cwd(home, home) == "~"
    assert short_cwd(home / "proj" / "src", home) == "~/proj/src"


def test_short_cwd_outside_home(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert short_cwd(other, home) == str(other.resolve())


def test_short_cwd_does_not_prefix_sibling_name(tmp_path: Path):
    home = tmp_path / "foo"
    home.mkdir()
    sibling = tmp_path / "foobar"
    sibling.mkdir()
    assert short_cwd(sibling, home) == str(sibling.resolve())


def test_git_label_none_outside_repo(tmp_path: Path):
    assert git_label(tmp_path) is None


def test_git_label_reads_branch(tmp_path: Path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    label = git_label(tmp_path)
    assert label is not None
    assert label.branch == "main"
    assert label.worktree is False


def test_git_label_detached(tmp_path: Path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("deadbeef" + "0" * 32 + "\n", encoding="utf-8")
    label = git_label(tmp_path)
    assert label is not None
    assert label.branch == "detached"


def test_git_label_walks_parents(tmp_path: Path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/feature/x\n", encoding="utf-8")
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    label = git_label(nested)
    assert label is not None
    assert label.branch == "feature/x"


def test_git_label_worktree_file(tmp_path: Path):
    real = tmp_path / "main" / ".git" / "worktrees" / "wt"
    real.mkdir(parents=True)
    (real / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")
    label = git_label(linked)
    assert label is not None
    assert label.branch == "topic"
    assert label.worktree is True


def test_thinking_badge_labels():
    assert thinking_badge("off") == ""
    assert thinking_badge("auto") == "think"
    assert thinking_badge("high") == "think high"


def test_branch_icon_ascii_fallback(monkeypatch):
    monkeypatch.setenv("B3CODE_NERD_FONTS", "0")
    assert branch_icon() == "git"
    monkeypatch.delenv("B3CODE_NERD_FONTS")
    assert branch_icon() == "\ue0a0"


async def test_topbar_renders_branch_without_icons(tmp_path: Path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        branch = app.screen.query_one("#git-branch", Static)
        assert "main" in str(branch.render())
        assert not app.screen.query("#worktree-flag")
        assert not app.screen.query("#cwd-icon")
        assert not app.screen.query("#model-icon")


async def test_topbar_renders_worktree_flag(tmp_path: Path):
    real = tmp_path / "main" / ".git" / "worktrees" / "wt"
    real.mkdir(parents=True)
    (real / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {real}\n", encoding="utf-8")
    app = B3App(AppContainer.build(linked))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "topic" in str(app.screen.query_one("#git-branch", Static).render())
        assert app.screen.query_one("#worktree-flag", Static).content == "worktree"
