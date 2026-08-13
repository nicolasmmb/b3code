import asyncio
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Static

from b3code.container import AppContainer
from b3code.services.chat import ChatEvent
from b3code.ui.app import B3App
from b3code.ui.coalesce import count_markdown_updates
from b3code.ui.screens.chat import ChatScreen, Welcome
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.messages import (
    DiffBlock,
    DiffFold,
    SystemNote,
    ToolRow,
    render_diff,
)
from b3code.utils.diffview import diff_texts
from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.planbar import PlanBar
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


async def test_enter_on_help_executes(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        notes = [str(n.render()) for n in screen.query(SystemNote)]
        assert any("/help" in n for n in notes)


async def test_resume_lists_sessions_in_autocomplete(tmp_path: Path):
    container = AppContainer.build(tmp_path)
    sid = container.session_store.current_id
    app = B3App(container)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        for ch in "/resume":
            await pilot.press(ch)
        await pilot.pause()
        ac = screen.query_one(Autocomplete)
        assert ac.display
        ids = [item.value for item in ac._items]
        assert sid in ids


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
        # delta só agenda o flush (~30fps); o spinner some no timer
        screen._apply_event(ChatEvent(kind="text_delta", text="Olá"))
        await pilot.pause(0.05)
        assert screen._thinking is None
        with pytest.raises(Exception):
            screen.query_one(Spinner)


async def test_text_deltas_schedule_one_ui_callback(tmp_path: Path, monkeypatch):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        scheduled = []
        monkeypatch.setattr(
            screen,
            "call_later",
            lambda callback, *args: scheduled.append((callback, args)),
        )
        screen._on_event(ChatEvent(kind="text_delta", text="one"))
        screen._on_event(ChatEvent(kind="text_delta", text="two"))
        screen._on_event(ChatEvent(kind="text_delta", text="three"))
        assert len(scheduled) == 1
        assert screen._pending_text == ["one", "two", "three"]


def test_delta_burst_coalesces():
    assert count_markdown_updates(200) == 1
    assert count_markdown_updates(200, duration_s=1.0) < 100


async def test_at_complete_empty_index_does_not_crash(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        await pilot.press("@")
        await pilot.pause()
        ac = screen.query_one(Autocomplete)
        # índice ainda pode estar vazio; não pode explodir
        assert ac is not None


async def test_new_refused_while_busy(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.c.chat.busy = True
        screen._run_command("/new")
        await pilot.pause()
        notes = [str(n.render()) for n in screen.query(SystemNote)]
        assert any("busy" in n for n in notes)


async def test_plan_badge_and_bar(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._run_command("/plan")
        await pilot.pause()
        flag = screen.query_one("#mode-flag", Static)
        assert flag.display
        assert "plan" in str(flag.render())
        bar = screen.query_one(PlanBar)
        screen.awaiting_plan = True
        bar.show("# Context\nhello")
        await pilot.pause()
        assert bar.display
        screen.confirm_plan("quit")
        await pilot.pause()
        assert screen.c.chat.plan.active is False
        assert flag.display is False


async def test_tool_events_reuse_the_same_row(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(ChatEvent(kind="tool_start", tool="grep", detail="one"))
        screen._apply_event(ChatEvent(kind="tool_end", tool="grep", detail="two"))
        rows = list(screen.query(ToolRow))
        assert len(rows) == 1
        assert rows[0].detail == "two"


async def test_diff_event_mounts_block(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        change = diff_texts("a.py", "x = 1\n", "x = 2\n")
        screen._apply_event(
            ChatEvent(kind="diff", tool="write_file", detail="a.py  +1 −1", change=change)
        )
        await pilot.pause()
        block = screen.query_one(DiffBlock)
        painted = render_diff(change, width=40)
        assert "Edit" in painted.plain
        assert "a.py" in painted.plain
        assert "x = 2" in painted.plain
        assert "+x = 2" not in painted.plain
        assert not list(block.query(DiffFold))


def test_render_diff_uses_line_numbers_and_bands():
    change = diff_texts("a.py", "x = 1\n", "x = 2\n")
    painted = render_diff(change, width=40)
    assert "Edit" in painted.plain
    assert any(span.style and "on #" in str(span.style) for span in painted.spans)


async def test_diff_fold_toggles_omitted_lines(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        change = diff_texts("big.py", "", "\n".join(f"line {i}" for i in range(60)))
        screen._apply_event(
            ChatEvent(kind="diff", tool="write_file", detail="big.py", change=change)
        )
        await pilot.pause()
        block = screen.query_one(DiffBlock)
        fold = block.query_one(DiffFold)
        assert "omitidas" in str(fold.render())
        assert block.expanded is False
        block.toggle()
        await pilot.pause()
        assert block.expanded is True
        assert "recolher" in str(fold.render())
