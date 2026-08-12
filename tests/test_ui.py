from pathlib import Path

from b3code.container import AppContainer
from b3code.ui.app import B3App
from b3code.ui.screens.chat import ChatScreen, Welcome
from b3code.ui.widgets.autocomplete import Autocomplete


async def test_app_opens_welcome(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        assert screen.query_one(Welcome).display
        assert screen.query_one("#prompt")
        await pilot.press("/")
        await pilot.pause()
        ac = screen.query_one(Autocomplete)
        assert ac.display
        labels = [item.label for item in ac._items]
        assert "/help" in labels
