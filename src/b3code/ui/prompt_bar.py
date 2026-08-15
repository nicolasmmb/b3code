"""Prompt + autocomplete. Workers de arquivo ficam aqui (Textual @work)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key, Paste
from textual.geometry import Size
from textual.message import Message
from textual.widgets import Static, TextArea

from b3code.commands.apply import Decision, apply_suggestion, decide_submit
from b3code.commands.registry import CommandRegistry
from b3code.commands.types import Suggestion
from b3code.config.schema import AppConfig
from b3code.services.files import FileIndex
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.utils.attachments import (
    AttachKind,
    Attachment,
    attachment_from_bytes,
    chip_span,
    classify_path,
    mime_suffix,
    next_paste_name,
    read_clipboard_image,
    try_read_dropped_paths,
    uniquify,
)
from b3code.utils.prompt import current_token

MAX_PROMPT_LINES = 8
_NEWLINE_KEYS = frozenset({"shift+enter", "alt+enter"})


class PromptInput(TextArea):
    """Composer estilo grok: 1 linha em repouso, cresce até MAX, depois scroll."""

    class Submitted(Message):
        def __init__(self, text_area: PromptInput, value: str) -> None:
            super().__init__()
            self.text_area = text_area
            self.value = value

        @property
        def control(self) -> PromptInput:
            return self.text_area

        @property
        def input(self) -> PromptInput:
            return self.text_area

    def __init__(self, config: AppConfig, **kwargs) -> None:
        super().__init__(
            "",
            soft_wrap=True,
            tab_behavior="focus",
            show_line_numbers=False,
            compact=True,
            highlight_cursor_line=False,
            placeholder="send a message  (@ file  / command)",
            **kwargs,
        )
        self._config = config

    @property
    def multiline(self) -> bool:
        return self._config.multiline

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self.text = text

    @property
    def cursor_position(self) -> int:
        return self.document.get_index_from_location(self.cursor_location)

    @cursor_position.setter
    def cursor_position(self, index: int) -> None:
        index = max(0, min(index, len(self.text)))
        self.move_cursor(self.document.get_location_from_index(index))

    def clear(self) -> None:
        self.text = ""

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return max(1, min(MAX_PROMPT_LINES, self.wrapped_document.height or 1))

    def action_cursor_up(self, select: bool = False) -> None:
        if _nav_autocomplete(self, "up"):
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False) -> None:
        if _nav_autocomplete(self, "down"):
            return
        super().action_cursor_down(select)

    async def _on_key(self, event: Key) -> None:
        if event.key == "backspace" and _delete_chip(self):
            event.stop()
            event.prevent_default()
            return
        if event.key == "tab" and _apply_autocomplete(self):
            event.stop()
            event.prevent_default()
            return
        if event.key in _NEWLINE_KEYS:
            event.stop()
            event.prevent_default()
            if self.multiline:
                self.insert("\n")
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        await super()._on_key(event)

    async def _on_paste(self, event: Paste) -> None:
        event.stop()
        event.prevent_default()
        if self.read_only:
            return
        text = event.text.replace("\r\n", "\n").replace("\r", "\n")
        for node in self.ancestors:
            if isinstance(node, PromptBar) and node.handle_paste(text):
                return
        if not self.multiline:
            text = " ".join(text.split("\n"))
        if result := self._replace_via_keyboard(text, *self.selection):
            self.move_cursor(result.end_location)
            self.focus()


def _nav_autocomplete(widget: PromptInput, direction: str) -> bool:
    for node in widget.ancestors:
        if isinstance(node, PromptBar):
            return node.nav_autocomplete(direction)
    return False


def _delete_chip(widget: PromptInput) -> bool:
    for node in widget.ancestors:
        if isinstance(node, PromptBar):
            return node.delete_chip_at_cursor()
    return False


def _apply_autocomplete(widget: PromptInput) -> bool:
    for node in widget.ancestors:
        if isinstance(node, PromptBar):
            return node.accept_autocomplete()
    return False


class PromptBar(Vertical):
    def __init__(
        self,
        commands: CommandRegistry,
        files: FileIndex,
        config: AppConfig,
        on_command: Callable[[str], None],
        on_chat: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._commands = commands
        self._files = files
        self._config = config
        self._on_command = on_command
        self._on_chat = on_chat
        self._ac_query: str | None = None
        self._attachments: dict[str, Attachment] = {}
        self._pending_attachments: dict[str, Attachment] = {}

    def compose(self) -> ComposeResult:
        yield Autocomplete()
        with Horizontal(id="prompt-row"):
            yield Static("❯", id="prompt-prefix")
            yield PromptInput(self._config, id="prompt")

    def _prompt(self) -> PromptInput:
        return self.query_one("#prompt", PromptInput)

    def pop_attachments(self, text: str) -> dict[str, Attachment]:
        pending = {
            token: item
            for token, item in self._pending_attachments.items()
            if token in text
        }
        leftover = {
            token: item for token, item in self._attachments.items() if token in text
        }
        self._pending_attachments.clear()
        for token in leftover:
            self._attachments.pop(token, None)
        return {**leftover, **pending}

    def handle_paste(self, text: str, *, allow_clipboard: bool = True) -> bool:
        dropped = try_read_dropped_paths(text, self._files.cwd)
        if dropped is not None:
            self._insert_dropped(dropped)
            return True
        if text.strip() or not allow_clipboard:
            return False
        image = read_clipboard_image()
        if image is None:
            return False
        name = next_paste_name(self._attachments, mime_suffix("image/png"))
        item = attachment_from_bytes(self._files.cwd, image, name)
        if item is None:
            return False
        self._insert_attachment(item)
        return True

    def delete_chip_at_cursor(self) -> bool:
        prompt_input = self._prompt()
        span = chip_span(
            prompt_input.value,
            prompt_input.cursor_position,
            list(self._attachments),
        )
        if span is None:
            return False
        start, end = span
        token = prompt_input.value[start:end].rstrip()
        prompt_input.value = prompt_input.value[:start] + prompt_input.value[end:]
        prompt_input.cursor_position = start
        self._attachments.pop(token, None)
        return True

    def _insert_dropped(self, paths: list[Path]) -> None:
        chunks: list[str] = []
        for path in paths:
            item = classify_path(path)
            if item is None or item.kind == AttachKind.UNSUPPORTED:
                chunks.append(f"{path} ")
                continue
            chunks.append(self._register(item) + " ")
        if chunks:
            self._insert_at_cursor("".join(chunks))

    def _insert_attachment(self, item: Attachment) -> None:
        self._insert_at_cursor(self._register(item) + " ")

    def _register(self, item: Attachment) -> str:
        item = uniquify(item, self._attachments)
        self._attachments[item.token] = item
        return item.token

    def _apply_file_chip(
        self, prompt_input: PromptInput, suggestion: Suggestion
    ) -> None:
        rel = suggestion.value.lstrip("@")
        path = (self._files.cwd / rel).resolve()
        item = classify_path(path)
        if item is None or item.kind == AttachKind.UNSUPPORTED:
            line, cursor = apply_suggestion(
                prompt_input.value, prompt_input.cursor_position, suggestion
            )
            prompt_input.value = line
            prompt_input.cursor_position = cursor
            return
        token = self._register(item)
        start, end, _ = current_token(prompt_input.value, prompt_input.cursor_position)
        prompt_input.value = (
            prompt_input.value[:start] + token + " " + prompt_input.value[end:]
        )
        prompt_input.cursor_position = start + len(token) + 1

    def _insert_at_cursor(self, text: str) -> None:
        prompt_input = self._prompt()
        index = prompt_input.cursor_position
        prompt_input.value = (
            prompt_input.value[:index] + text + prompt_input.value[index:]
        )
        prompt_input.cursor_position = index + len(text)
        prompt_input.focus()

    def disable_input(self) -> None:
        self._prompt().disabled = True

    def enable_input(self) -> None:
        prompt_input = self._prompt()
        prompt_input.disabled = False
        prompt_input.focus()

    def focus_input(self) -> None:
        self._prompt().focus()

    def refresh_suggestions(self) -> None:
        prompt_input = self._prompt()
        self._refresh_autocomplete(prompt_input.value, prompt_input.cursor_position)

    def nav_autocomplete(self, direction: str) -> bool:
        autocomplete = self.query_one(Autocomplete)
        if not autocomplete.display:
            return False
        if direction == "down":
            autocomplete.action_cursor_down()
            return True
        if direction == "up":
            autocomplete.action_cursor_up()
            return True
        return False

    @work(exclusive=True, group="files-scan")
    async def refresh_index(self) -> None:
        await self._files.refresh()
        self.call_later(self.refresh_suggestions)

    def consume_key(self, event: Key) -> bool:
        autocomplete = self.query_one(Autocomplete)
        if not autocomplete.display:
            return False
        if event.key == "down":
            autocomplete.action_cursor_down()
            event.stop()
            return True
        if event.key == "up":
            autocomplete.action_cursor_up()
            event.stop()
            return True
        if event.key != "tab":
            return False
        if not self.accept_autocomplete():
            return False
        event.stop()
        event.prevent_default()
        return True

    def accept_autocomplete(self) -> bool:
        autocomplete = self.query_one(Autocomplete)
        if not autocomplete.display:
            return False
        item = autocomplete.current()
        if item is None:
            return False
        prompt_input = self._prompt()
        decision = decide_submit(prompt_input.value, prompt_input.cursor_position, item)
        self.apply_submit_decision(decision, prompt_input, autocomplete, execute=False)
        return True

    @on(TextArea.Changed, "#prompt")
    def on_prompt_changed(self, event: TextArea.Changed) -> None:
        prompt_input = event.control
        if not isinstance(prompt_input, PromptInput):
            prompt_input = self._prompt()
        self._refresh_autocomplete(prompt_input.value, prompt_input.cursor_position)

    @on(PromptInput.Submitted, "#prompt")
    def on_prompt_submitted(self, event: PromptInput.Submitted) -> None:
        autocomplete = self.query_one(Autocomplete)
        suggestion = autocomplete.current() if autocomplete.display else None
        prompt_input = event.text_area
        decision = decide_submit(event.value, prompt_input.cursor_position, suggestion)
        self.apply_submit_decision(decision, prompt_input, autocomplete, execute=True)

    def apply_submit_decision(
        self,
        decision: Decision,
        prompt_input: PromptInput,
        autocomplete: Autocomplete,
        *,
        execute: bool,
    ) -> None:
        if decision.kind == "apply":
            if decision.suggestion and decision.suggestion.kind == "file":
                self._apply_file_chip(prompt_input, decision.suggestion)
                autocomplete.set_suggestions([])
                return
            prompt_input.value = decision.line
            prompt_input.cursor_position = decision.cursor
            consume = bool(decision.suggestion and decision.suggestion.consume)
            if execute and consume:
                autocomplete.set_suggestions([])
                prompt_input.clear()
                self._on_command(decision.line.strip())
                return
            self._refresh_autocomplete(decision.line, decision.cursor)
            return
        if not execute or decision.kind == "empty":
            return
        sent = prompt_input.value
        atts = {
            token: item for token, item in self._attachments.items() if token in sent
        }
        self._attachments.clear()
        prompt_input.clear()
        autocomplete.set_suggestions([])
        if decision.kind == "execute":
            self._on_command(decision.line)
            return
        if decision.kind == "chat":
            self._pending_attachments = atts
            self._on_chat(decision.line)

    def _refresh_autocomplete(self, value: str, cursor: int) -> None:
        _, _, token = current_token(value, cursor)
        autocomplete = self.query_one(Autocomplete)
        if value.startswith("/"):
            self._ac_query = None
            autocomplete.set_suggestions(self._commands.complete(value[:cursor] or "/"))
            return
        if token.startswith("@"):
            query = token[1:]
            self._ac_query = query
            self._search_files(query)
            return
        self._ac_query = None
        autocomplete.set_suggestions([])

    @work(exclusive=True, group="files-search")
    async def _search_files(self, query: str) -> None:
        await asyncio.sleep(0.05)
        if query != self._ac_query:
            return
        hits = await self._files.search_async(query)
        if query != self._ac_query:
            return
        self.call_later(self._show_file_hits, query, hits)

    def _show_file_hits(self, query: str, hits: list[Path]) -> None:
        if query != self._ac_query:
            return
        self.query_one(Autocomplete).set_suggestions(
            [
                Suggestion(value=str(p), label=str(p), hint="file", kind="file")
                for p in hits
            ]
        )
