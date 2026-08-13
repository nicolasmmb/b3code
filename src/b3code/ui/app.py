"""App Textual. Só UI — o container traz os services."""

from textual.app import App

from b3code.container import AppContainer
from b3code.ui.screens.chat import ChatScreen


class B3App(App):
    CSS_PATH = "theme.tcss"
    TITLE = "b3code"

    def __init__(self, container: AppContainer) -> None:
        super().__init__()
        self.container = container

    def on_mount(self) -> None:
        self.push_screen(ChatScreen(self.container.screen_deps()))
