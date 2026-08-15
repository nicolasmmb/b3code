"""Card de pergunta. Other é uma linha só: hint ou Input, nunca as duas."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static
from textual.widgets.option_list import Option

from b3code.services.questions import OTHER_HINT, OTHER_LABEL, Question
from b3code.ui.widgets.choicebar import ChoiceBar, QuietOptions


class QuestionBar(ChoiceBar):
    SUMMARY_ID = "question-summary"
    OPTIONS_ID = "question-options"
    FALLBACK = OTHER_LABEL

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._editing = False
        self._idx = 0

    def compose(self) -> ComposeResult:
        yield Static("", id=self.SUMMARY_ID)
        yield QuietOptions(id=self.OPTIONS_ID)
        with Horizontal(id="question-other-row"):
            yield Static("", id="question-other-mark")
            yield Static(OTHER_HINT, id="question-other-hint")
            yield Input(placeholder=OTHER_HINT, id="question-other")

    def show_question(self, item: Question, index: int, total: int, accent: str) -> None:
        prefix = f"({index + 1}/{total}) " if total > 1 else ""
        choices = tuple((opt.label, opt.label, opt.description) for opt in item.options)
        self.set_choices(choices)
        self._editing = False
        self._clear_field()
        self.set_summary(f"▸  {prefix}{item.question}", accent)

    def show_other(self) -> None:
        self._editing = True
        self._idx = self._other_index()
        self._clear_field()
        self.paint(self._idx)
        self.query_one("#question-other", Input).focus()

    def hide_other(self) -> None:
        was = self._editing
        self._editing = False
        self._clear_field()
        if was and self.display:
            self.paint(self._other_index())

    def other_text(self) -> str:
        return self.query_one("#question-other", Input).value.strip()

    def other_visible(self) -> bool:
        return self._editing

    def insert(self, text: str) -> None:
        field = self.query_one("#question-other", Input)
        field.value = field.value + text
        field.cursor_position = len(field.value)

    def current(self) -> str:
        if 0 <= self._idx < len(self._choices):
            return self._choices[self._idx][0]
        return self.FALLBACK

    def highlighted(self) -> int:
        return self._idx

    def move(self, delta: int, *, wrap: bool = False) -> None:
        last = max(len(self._choices) - 1, 0)
        if wrap and self._choices:
            self.paint((self._idx + delta) % len(self._choices))
            return
        self.paint(max(0, min(last, self._idx + delta)))

    def paint(self, idx: int) -> None:
        self._idx = idx
        accent, muted = self._active_colors()
        self._paint_options(accent, muted)
        self._paint_other(accent, muted)

    def _paint_options(self, accent: str, muted: str) -> None:
        options = self.query_one(f"#{self.OPTIONS_ID}", QuietOptions)
        options.clear_options()
        items = [row for row in self._choices if row[0] != OTHER_LABEL]
        rows = []
        for i, (_value, label, hint) in enumerate(items):
            on = i == self._idx and not self._on_other()
            mark = "›" if on else " "
            style = accent if on else muted
            body = f"{mark}  {label:<8} {hint}".rstrip()
            rows.append(Option(Text(body, style=style)))
        options.add_options(rows)
        if items:
            options.highlighted = 0 if self._on_other() else min(self._idx, len(items) - 1)

    def _paint_other(self, accent: str, muted: str) -> None:
        on = self._on_other()
        style = accent if on else muted
        mark = "›" if on else " "
        self.query_one("#question-other-mark", Static).update(
            Text(f"{mark}  {OTHER_LABEL:<8} ", style=style)
        )
        row = self.query_one("#question-other-row", Horizontal)
        hint = self.query_one("#question-other-hint", Static)
        field = self.query_one("#question-other", Input)
        row.display = True
        hint.display = not self._editing
        field.display = self._editing
        if not self._editing:
            hint.update(Text(OTHER_HINT, style=style))

    def _on_other(self) -> bool:
        return self._is_other(self._idx)

    def _is_other(self, idx: int) -> bool:
        return 0 <= idx < len(self._choices) and self._choices[idx][0] == OTHER_LABEL

    def _other_index(self) -> int:
        for i, (value, _label, _hint) in enumerate(self._choices):
            if value == OTHER_LABEL:
                return i
        return max(len(self._choices) - 1, 0)

    def _clear_field(self) -> None:
        self.query_one("#question-other", Input).value = ""
