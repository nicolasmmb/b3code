"""Barra superior: cwd, modelo, badge de plan."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class TopBar(Horizontal):
    def __init__(self, cwd: Path, model: str, **kwargs) -> None:
        super().__init__(id="top-bar", **kwargs)
        self._cwd = _short_cwd(cwd)
        self._model = model

    def compose(self) -> ComposeResult:
        yield Static("▸", id="cwd-icon")
        yield Static(self._cwd, id="cwd")
        yield Static("◆", id="model-icon")
        yield Static(self._model, id="model-label")
        yield Static("", id="mode-flag")

    def set_model(self, name: str) -> None:
        self.query_one("#model-label", Static).update(name)

    def set_plan_badge(self, active: bool) -> None:
        flag = self.query_one("#mode-flag", Static)
        if not active:
            flag.update("")
            flag.display = False
            return
        flag.update("plan")
        flag.display = True


def _short_cwd(cwd: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(cwd.relative_to(home))
    except ValueError:
        return str(cwd)
