import asyncio
import pytest
from pathlib import Path

from b3code.container import AppContainer
from b3code.services.chat import ChatEvent
from b3code.ui.app import B3App
from b3code.ui.screens.chat import ChatScreen, Welcome
from textual.widgets import Static

from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.spinner import FRAMES, Spinner


async def test_app_opens_welcome(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        assert screen.query_one(Welcome).display
        assert screen.query_one("#prompt")
        assert screen.query_one("#cwd-icon")
        assert screen.query_one("#model-icon")
        cwd = screen.query_one("#cwd", Static)
        model = screen.query_one("#model-label", Static)
        assert cwd.content
        assert model.content
        await pilot.press("/")
        await pilot.pause()
        ac = screen.query_one(Autocomplete)
        assert ac.display
        labels = [item.label for item in ac._items]
        assert "/help" in labels


async def test_permission_picker_arrows(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        picker = screen.query_one(PermissionPicker)
        screen.awaiting_permission = True
        picker.show("ls /tmp", "/tmp")
        await pilot.pause()
        assert picker.display
        assert picker.current() == "once"
        await pilot.press("down")
        await pilot.pause()
        assert picker.current() == "always"


from textual.app import App


async def test_spinner_animates():
    class MiniApp(App):
        def compose(self):
            yield Spinner("thinking")

    app = MiniApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = app.query_one(Spinner)
        first = str(sp.render())
        assert "thinking" in first
        await pilot.pause(0.25)
        second = str(sp.render())
        assert second != first
        assert second in {f"{f} thinking" for f in FRAMES}


async def test_spinner_mounted_and_removed_on_event(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)

        async def noop(prompt: str, on_event) -> None:
            await asyncio.sleep(0)

        # enqueue nunca emite eventos -> spinner fica montado
        screen.c.chat.enqueue = noop
        screen._send_chat("hi")
        await pilot.pause()
        spinner = screen.query_one(Spinner)
        assert screen._thinking is spinner
        # primeiro delta de texto remove o spinner
        screen._apply_event(ChatEvent(kind="text_delta", text="Olá"))
        await pilot.pause()
        assert screen._thinking is None
        with pytest.raises(Exception):
            screen.query_one(Spinner)
