"""Prompt + autocomplete. Workers de arquivo ficam aqui (Textual @work)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Input

from b3code.commands.apply import Decision, decide_submit
from b3code.commands.registry import CommandRegistry
from b3code.commands.types import Suggestion
from b3code.services.files import FileIndex
from b3code.ui.widgets.autocomplete import Autocomplete
from b3code.utils.prompt import current_token


class PromptBar(Vertical):
    def __init__(
        self,
        commands: CommandRegistry,
        files: FileIndex,
        on_command: Callable[[str], None],
        on_chat: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._commands = commands
        self._files = files
        self._on_command = on_command
        self._on_chat = on_chat
        self._ac_query: str | None = None

    def compose(self) -> ComposeResult:
        yield Autocomplete()
        with Horizontal(id="prompt-row"):
            yield Input(placeholder="send a message  (@ file  / command)", id="prompt")

    def disable_input(self) -> None:
        self.query_one("#prompt", Input).disabled = True

    def enable_input(self) -> None:
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = False
        prompt_input.focus()

    def focus_input(self) -> None:
        self.query_one("#prompt", Input).focus()

    def refresh_suggestions(self) -> None:
        prompt_input = self.query_one("#prompt", Input)
        self._refresh_autocomplete(prompt_input.value, prompt_input.cursor_position)

    @work(exclusive=True, group="files-scan")
    async def refresh_index(self) -> None:
        await self._files.ensure_scanned()
        self.refresh_suggestions()

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
        item = autocomplete.current()
        if item is None:
            return False
        prompt_input = self.query_one("#prompt", Input)
        decision = decide_submit(prompt_input.value, prompt_input.cursor_position, item)
        self.apply_submit_decision(decision, prompt_input, autocomplete, execute=False)
        event.stop()
        event.prevent_default()
        return True

    @on(Input.Changed, "#prompt")
    def on_prompt_changed(self, event: Input.Changed) -> None:
        self._refresh_autocomplete(event.value, event.input.cursor_position)

    @on(Input.Submitted, "#prompt")
    def on_prompt_submitted(self, event: Input.Submitted) -> None:
        autocomplete = self.query_one(Autocomplete)
        suggestion = autocomplete.current() if autocomplete.display else None
        decision = decide_submit(event.value, event.input.cursor_position, suggestion)
        self.apply_submit_decision(decision, event.input, autocomplete, execute=True)

    def apply_submit_decision(
        self,
        decision: Decision,
        prompt_input: Input,
        autocomplete: Autocomplete,
        *,
        execute: bool,
    ) -> None:
        if decision.kind == "apply":
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
        prompt_input.clear()
        autocomplete.set_suggestions([])
        if decision.kind == "execute":
            self._on_command(decision.line)
            return
        if decision.kind == "chat":
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
        hits = await asyncio.to_thread(self._files.search, query)
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
