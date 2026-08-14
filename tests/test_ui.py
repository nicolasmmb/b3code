import asyncio
from pathlib import Path

import pytest
from test_attachments import make_png
from textual.app import App
from textual.events import Paste
from textual.widgets import Static

from b3code.config.schema import AppConfig, ThemeColors
from b3code.config.store import ConfigStore
from b3code.container import AppContainer
from b3code.services.chat import ChatEvent
from b3code.ui.app import B3App
from b3code.ui.coalesce import count_markdown_updates
from b3code.ui.prompt_bar import PromptBar, PromptInput
from b3code.ui.screens.chat import ChatScreen, Welcome
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.ui.widgets.messages import (
    AssistantMessage,
    DiffBlock,
    DiffFold,
    ErrorBlock,
    ErrorFold,
    FenceCopy,
    FileChip,
    PlanDoc,
    SystemNote,
    ToolRow,
    UserMessage,
    fence_lang,
    render_diff,
)
from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.planbar import PlanBar
from b3code.ui.widgets.spinner import FRAMES, Spinner
from b3code.utils.diffview import diff_texts


async def test_app_opens_welcome(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        assert screen.query_one(Welcome).display
        assert screen.query_one("#prompt")
        cwd = screen.query_one("#cwd", Static)
        model = screen.query_one("#model-label", Static)
        assert cwd.content
        assert model.content
        assert not screen.query("#cwd-icon")
        assert not screen.query("#model-icon")
        await pilot.press("/")
        await pilot.pause()
        ac = screen.query_one(Autocomplete)
        assert ac.display
        labels = [item.label for item in ac.suggestions]
        assert "/help" in labels


async def test_app_applies_saved_theme(tmp_path: Path):
    ConfigStore.for_cwd(tmp_path).save(
        AppConfig(
            themes=[
                ThemeColors(name="crimson", background="#111111", accent="#DC143C")
            ],
            selected_theme="crimson",
        )
    )
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "crimson"
        assert app.theme_variables["background"].lower() == "#111111"
        assert app.theme_variables["accent"].lower() == "#dc143c"


async def test_theme_command_updates_css(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._run_command("/theme update background #101010")
        await pilot.pause()
        assert app.container.config.theme.background == "#101010"
        assert app.theme_variables["background"].lower() == "#101010"


async def test_paste_preserves_newlines(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste("linha 1\nlinha 2"))
        await pilot.pause()
        assert prompt.text == "linha 1\nlinha 2"


async def test_shift_enter_inserts_newline(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a", "shift+enter", "b")
        await pilot.pause()
        prompt = app.screen.query_one("#prompt", PromptInput)
        assert prompt.text == "a\nb"


async def test_enter_submits_multiline_chat(tmp_path: Path):
    sent: list[str] = []
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.query_one(PromptBar)._on_chat = sent.append
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.text = "linha 1\nlinha 2"
        await pilot.press("enter")
        await pilot.pause()
        assert sent == ["linha 1\nlinha 2"]
        assert prompt.text == ""


async def test_multiline_off_paste_drops_newlines(tmp_path: Path):
    container = AppContainer.build(tmp_path)
    container.config.multiline = False
    app = B3App(container)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste("linha 1\nlinha 2"))
        await pilot.pause()
        assert "\n" not in prompt.text
        assert "linha 1" in prompt.text
        assert "linha 2" in prompt.text


async def test_prompt_grows_then_caps(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste("\n".join(f"l{i}" for i in range(12))))
        await pilot.pause()
        assert prompt.text.count("\n") == 11
        assert prompt.size.height <= 8
        assert prompt.size.height >= 1


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
        ids = [item.value for item in ac.suggestions]
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
        screen.deps.chat.enqueue = noop
        screen._send_chat("hi")
        await pilot.pause()
        spinner = screen.query_one(Spinner)
        assert screen.chat_view.thinking is spinner
        # texto no meio do run não tira o spinner — só done/error/plan_ready
        screen._apply_event(ChatEvent(kind="text_delta", text="Olá"))
        await pilot.pause(0.05)
        assert screen.chat_view.thinking is spinner
        screen._apply_event(ChatEvent(kind="done", text="Olá"))
        await pilot.pause()
        assert screen.chat_view.thinking is None
        with pytest.raises(Exception):
            screen.query_one(Spinner)


async def test_plan_mode_spinner_survives_tools_until_ready(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.deps.chat.enter_plan()

        async def noop(prompt: str, on_event) -> None:
            await asyncio.sleep(0)

        screen.deps.chat.enqueue = noop
        screen._send_chat("desenha um plano")
        await pilot.pause()
        assert screen.chat_view.thinking is not None
        assert "planning" in str(screen.chat_view.thinking.render())
        screen._apply_event(ChatEvent(kind="tool_start", tool="grep", detail="x"))
        await pilot.pause()
        assert screen.chat_view.thinking is not None
        screen._apply_event(ChatEvent(kind="plan_draft", text="# Title\n"))
        await pilot.pause()
        assert screen.chat_view.thinking is not None
        screen._apply_event(ChatEvent(kind="plan_ready", text="# Title\n"))
        await pilot.pause()
        assert screen.chat_view.thinking is None


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
        assert screen.text_buffer.pending == ["one", "two", "three"]


def test_delta_burst_coalesces():
    assert count_markdown_updates(200) == 1
    assert count_markdown_updates(200, duration_s=1.0) < 100


async def test_mcp_command_lists_and_toggles(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._run_command("/mcp add github -- npx -y demo")
        await pilot.pause()
        screen._run_command("/mcp")
        await pilot.pause()
        notes = [str(n.render()) for n in screen.query(SystemNote)]
        assert any("github  on  stdio" in n for n in notes)
        screen._run_command("/mcp disable github")
        await pilot.pause()
        assert app.container.config.mcp_servers["github"].enabled is False
        assert screen.deps.chat.mcp.connects == 0


async def test_mcp_tool_event_burst_does_not_break_host(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        for i in range(12):
            cid = f"c{i}"
            screen._apply_event(
                ChatEvent(
                    kind="tool_start",
                    tool="use_tool",
                    detail="Use github__create_issue",
                    call_id=cid,
                )
            )
            screen._apply_event(
                ChatEvent(
                    kind="tool_end",
                    tool="use_tool",
                    output="ok",
                    call_id=cid,
                )
            )
        rows = screen.query(ToolRow)
        assert len(rows) == 12


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
        screen.deps.chat.busy = True
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
        assert screen.deps.chat.plan.active is False
        assert flag.display is False


async def test_plan_ready_shows_full_doc(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        body = "# Add auth\n\n## Context\nwhy we need it\n"
        screen._apply_event(ChatEvent(kind="plan_draft", text=body))
        await pilot.pause()
        doc = screen.query_one(PlanDoc)
        assert "Add auth" in str(doc.source) or "auth" in str(doc.render())
        screen._apply_event(ChatEvent(kind="plan_ready", text=body))
        await pilot.pause()
        bar = screen.query_one(PlanBar)
        assert bar.display
        summary = str(screen.query_one("#plan-summary", Static).render())
        assert "Add auth" in summary
        assert "sections" in summary


async def test_plan_bar_arrows_and_keys(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.deps.chat.enter_plan()
        screen._apply_event(
            ChatEvent(kind="plan_ready", text="# Add auth\n\n## Context\nx\n")
        )
        await pilot.pause()
        bar = screen.query_one(PlanBar)
        assert bar.display
        assert bar.current() == "approve"
        await pilot.press("down")
        await pilot.pause()
        assert bar.current() == "revise"
        await pilot.press("s")
        await pilot.pause()
        assert screen.awaiting_plan is False
        assert screen.deps.chat.plan.active is True


async def test_tool_events_reuse_the_same_row(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(
            ChatEvent(
                kind="tool_start", tool="grep", detail='Searched "one"', call_id="g1"
            )
        )
        screen._apply_event(
            ChatEvent(kind="tool_end", tool="grep", output="a.py:1:one", call_id="g1")
        )
        rows = list(screen.query(ToolRow))
        assert len(rows) == 1
        assert rows[0].detail == 'Searched "one"'
        assert rows[0].output == "a.py:1:one"
        assert rows[0].expandable
        assert rows[0].expanded is False


async def test_two_commands_get_two_rows(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(
            ChatEvent(
                kind="tool_start",
                tool="run_command",
                detail="$ git status",
                call_id="a",
            )
        )
        screen._apply_event(
            ChatEvent(
                kind="tool_start",
                tool="run_command",
                detail="$ git log",
                call_id="b",
            )
        )
        rows = list(screen.query(ToolRow))
        assert len(rows) == 2
        assert rows[0].detail == "$ git status"
        assert rows[1].detail == "$ git log"


async def test_tool_row_fold_reveals_output(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(
            ChatEvent(
                kind="tool_start",
                tool="run_command",
                detail="$ pwd",
                call_id="p1",
            )
        )
        screen._apply_event(
            ChatEvent(
                kind="tool_end",
                tool="run_command",
                output="/tmp/proj",
                call_id="p1",
            )
        )
        await pilot.pause()
        row = screen.query_one(ToolRow)
        assert row.expanded is False
        assert row.query_one(".tool-body").display is False
        row.toggle()
        await pilot.pause()
        assert row.expanded is True
        assert row.query_one(".tool-body").display is True


async def test_diff_event_mounts_block(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        change = diff_texts("a.py", "x = 1\n", "x = 2\n")
        screen._apply_event(
            ChatEvent(
                kind="diff", tool="write_file", detail="a.py  +1 −1", change=change
            )
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


async def test_error_block_expands_and_copies(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        detail = (
            "Traceback (most recent call last):\n"
            '  File "chat.py", line 1, in _run_turn\n'
            "    await self._dispatch_turn(...)\n"
            "httpx.ConnectError: [Errno 8] nodename nor servname provided\n"
        )
        screen._apply_event(
            ChatEvent(
                kind="error",
                text="ConnectError: [Errno 8] nodename nor servname provided",
                detail=detail,
            )
        )
        await pilot.pause()
        block = screen.query_one(ErrorBlock)
        fold = block.query_one(ErrorFold)
        assert block.expanded is False
        assert "Error" in str(block._header.render())
        assert "ConnectError" in str(block._header.render())
        assert "Lines" in str(fold.render())
        assert "nodename" not in str(block._body.render()) or not block._body.display
        block.toggle()
        await pilot.pause()
        assert block.expanded is True
        assert "nodename" in str(block._body.render())
        assert "chat.py" in str(block._body.render())
        fold.focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == detail


async def test_short_error_has_no_fold(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(
            ChatEvent(
                kind="error",
                text="missing api_key or api_endpoint in .b3code/config.json",
            )
        )
        await pilot.pause()
        block = screen.query_one(ErrorBlock)
        assert "Error" in str(block._header.render())
        assert "missing api_key" in str(block._message.render())
        assert block._fold.display is False


async def test_cancelled_stays_a_system_note(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen._apply_event(ChatEvent(kind="error", text="cancelled"))
        await pilot.pause()
        notes = [str(n.render()) for n in screen.query(SystemNote)]
        assert any("cancelled" in n for n in notes)
        assert list(screen.query(ErrorBlock)) == []


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


async def test_drop_on_chat_area_imports_chip(tmp_path: Path):
    folder = tmp_path / "My Documents"
    folder.mkdir()
    png = folder / "Captura de Tela.png"
    png.write_bytes(make_png(8, 8))
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.query_one("#chat").focus()
        screen.post_message(Paste(str(png)))
        await pilot.pause()
        prompt = screen.query_one("#prompt", PromptInput)
        assert "[IMG - Captura de Tela.png]" in prompt.text
        assert prompt.has_focus


async def test_paste_png_inserts_image_chip(tmp_path: Path):
    png = tmp_path / "casa.jpg"
    png.write_bytes(make_png(8, 8))
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(str(png)))
        await pilot.pause()
        assert "[IMG - casa.jpg]" in prompt.text
        assert str(png) not in prompt.text


async def test_paste_pdf_and_py_chips(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    py = tmp_path / "app.py"
    py.write_text("print(1)\n")
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(str(pdf)))
        await pilot.pause()
        assert "[PDF - report.pdf]" in prompt.text
        prompt.clear()
        app.post_message(Paste(str(py)))
        await pilot.pause()
        assert "[PY - app.py]" in prompt.text


async def test_paste_bin_is_path_not_chip(tmp_path: Path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x00\x01\x02\xff")
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(str(blob)))
        await pilot.pause()
        assert "[" not in prompt.text
        assert str(blob) in prompt.text


async def test_paste_mixed_file_urls(tmp_path: Path):
    png = tmp_path / "casa.jpg"
    png.write_bytes(make_png(8, 8))
    txt = tmp_path / "notes.txt"
    txt.write_text("hi\n")
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(f"file://{png}\nfile://{txt}"))
        await pilot.pause()
        assert "[IMG - casa.jpg]" in prompt.text
        assert "[TXT - notes.txt]" in prompt.text
        assert prompt.text.index("[IMG - casa.jpg]") < prompt.text.index(
            "[TXT - notes.txt]"
        )


async def test_backspace_deletes_whole_chip(tmp_path: Path):
    png = tmp_path / "casa.jpg"
    png.write_bytes(make_png(8, 8))
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(str(png)))
        await pilot.pause()
        assert "[IMG - casa.jpg]" in prompt.text
        await pilot.press("backspace")
        await pilot.pause()
        assert "[IMG - casa.jpg]" not in prompt.text


async def test_at_complete_file_inserts_chip(tmp_path: Path):
    (tmp_path / "app.py").write_text("print(1)\n")
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        bar = screen.query_one(PromptBar)
        await bar._files.ensure_scanned()
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        prompt.text = "@ap"
        prompt.cursor_position = len(prompt.text)
        bar.refresh_suggestions()
        await asyncio.sleep(0.2)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert "[PY - app.py]" in prompt.text
        assert "@app.py" not in prompt.text


async def test_submit_chip_shows_in_chat(tmp_path: Path):
    png = tmp_path / "casa.jpg"
    png.write_bytes(make_png(8, 8))
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        prompt = screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste(str(png)))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.text == ""
        chips = list(screen.query(FileChip))
        assert chips
        user = screen.query_one(UserMessage)
        assert user.query(FileChip)


async def test_plain_paste_still_not_a_chip(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one("#prompt", PromptInput)
        prompt.focus()
        app.post_message(Paste("linha 1\nlinha 2"))
        await pilot.pause()
        assert prompt.text == "linha 1\nlinha 2"


def test_fence_lang_uses_first_word_or_code():
    assert fence_lang("python") == "python"
    assert fence_lang("python hl_lines=1") == "python"
    assert fence_lang("") == "code"


async def test_assistant_fence_copy_button(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.chat_view.start_assistant()
        await pilot.pause()
        screen.chat_view.append_assistant("```python\nprint(1)\n```\n")
        await pilot.pause()
        button = screen.query_one(FenceCopy)
        assert "⧉" in str(button.render())
        assert "copy" not in str(button.render())
        screen.chat_view.hide_welcome()
        button.scroll_visible(animate=False)
        await pilot.pause()
        assert await pilot.click(button, offset=(0, 0))
        await pilot.pause()
        assert app.clipboard == "print(1)\n"


async def test_two_fences_copy_independently(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.chat_view.start_assistant()
        await pilot.pause()
        screen.chat_view.append_assistant(
            "```python\nprint(1)\n```\n\n```bash\necho hi\n```\n"
        )
        await pilot.pause()
        buttons = list(screen.query(FenceCopy))
        assert len(buttons) == 2
        buttons[0].focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "print(1)\n"
        buttons[1].focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "echo hi\n"


async def test_unlabeled_fence_still_has_copy(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.chat_view.start_assistant()
        await pilot.pause()
        screen.chat_view.append_assistant("```\nplain\n```\n")
        await pilot.pause()
        msg = screen.query_one(AssistantMessage)
        header = str(msg.query_one(".fence-lang", Static).render())
        assert "code" in header
        button = screen.query_one(FenceCopy)
        button.focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "plain\n"


async def test_user_message_fence_has_copy(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.chat_view.mount_user("```python\nprint(2)\n```\n")
        await pilot.pause()
        user = screen.query_one(UserMessage)
        assert user.query(FenceCopy)
        button = user.query_one(FenceCopy)
        button.focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "print(2)\n"


async def test_fence_copy_survives_markdown_update(tmp_path: Path):
    app = B3App(AppContainer.build(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        screen.chat_view.start_assistant()
        await pilot.pause()
        screen.chat_view.append_assistant("```python\nprint(1)\n```\n")
        await pilot.pause()
        screen.chat_view.append_assistant("depois\n")
        await pilot.pause()
        assert screen.query_one(FenceCopy)
        button = screen.query_one(FenceCopy)
        button.focus()
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "print(1)\n"
