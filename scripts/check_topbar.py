import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.widgets import Static

from b3code.container import AppContainer
from b3code.ui.app import B3App
from b3code.ui.screens.chat import ChatScreen


async def main():
    app = B3App(AppContainer.build(Path(".").resolve()))
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        bar = screen.query_one("#top-bar")
        print("top-bar region:", bar.region)
        for widget in screen.query(Static):
            print(getattr(widget, "id", None), repr(widget.render()))
        try:
            svg = app.export_screenshot()
            print("screenshot ok, len", len(svg))
        except Exception as exc:
            print("screenshot falhou:", type(exc).__name__, exc)


asyncio.run(main())
