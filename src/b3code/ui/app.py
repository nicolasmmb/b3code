"""App Textual. Só UI — o container traz os services."""

from textual.app import App

from b3code.container import AppContainer
from b3code.ui.palette import to_textual
from b3code.ui.screens.chat import ChatScreen


class B3App(App):
    CSS_PATH = "theme.tcss"
    TITLE = "b3code"

    def __init__(self, container: AppContainer) -> None:
        super().__init__()
        self.container = container
        self._install_themes()

    def _install_themes(self) -> None:
        for item in self.container.config.themes:
            self.register_theme(to_textual(item))
        self.theme = self.container.config.theme.name

    def apply_theme(self) -> None:
        previous = self.theme
        self._install_themes()
        if self.theme == previous and self.is_running:
            self._invalidate_css()
            self.refresh_css(animate=False)

    def on_mount(self) -> None:
        self.push_screen(ChatScreen(self.container.screen_deps()))
