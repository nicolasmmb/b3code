"""Card de pergunta. Other abre um Input na mesma grelha das opções."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static

from b3code.services.questions import OTHER_HINT, OTHER_LABEL, Question
from b3code.ui.widgets.choicebar import ChoiceBar, QuietOptions


class QuestionBar(ChoiceBar):
    SUMMARY_ID = "question-summary"
    OPTIONS_ID = "question-options"
    FALLBACK = OTHER_LABEL

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._editing = False

    def compose(self) -> ComposeResult:
        yield Static("", id=self.SUMMARY_ID)
        yield QuietOptions(id=self.OPTIONS_ID)
        with Horizontal(id="question-other-row"):
            yield Static("", id="question-other-mark")
            yield Input(placeholder=OTHER_HINT, id="question-other")

    def on_mount(self) -> None:
        self.query_one("#question-other-row", Horizontal).display = False

    def show_question(self, item: Question, index: int, total: int, accent: str) -> None:
        prefix = f"({index + 1}/{total}) " if total > 1 else ""
        choices = tuple((opt.label, opt.label, opt.description) for opt in item.options)
        self.set_choices(choices)
        self.hide_other()
        self.set_summary(f"▸  {prefix}{item.question}", accent)

    def show_other(self) -> None:
        self._editing = True
        self.paint(self.highlighted())
        accent, _muted = self._active_colors()
        mark = f"›  {OTHER_LABEL:<8} "
        self.query_one("#question-other-mark", Static).update(Text(mark, style=accent))
        self.query_one("#question-other-row", Horizontal).display = True
        field = self.query_one("#question-other", Input)
        field.value = ""
        field.focus()

    def hide_other(self) -> None:
        was = self._editing
        self._editing = False
        self.query_one("#question-other-row", Horizontal).display = False
        self.query_one("#question-other", Input).value = ""
        if was and self.display:
            self._select_other()

    def other_text(self) -> str:
        return self.query_one("#question-other", Input).value.strip()

    def other_visible(self) -> bool:
        return self._editing

    def insert(self, text: str) -> None:
        field = self.query_one("#question-other", Input)
        field.value = field.value + text
        field.cursor_position = len(field.value)

    def paint(self, idx: int) -> None:
        if not self._editing:
            super().paint(idx)
            return
        saved = self._choices
        visible = tuple(row for row in saved if row[0] != OTHER_LABEL)
        self._choices = visible
        try:
            super().paint(0 if not visible else min(idx, len(visible) - 1))
        finally:
            self._choices = saved

    def _select_other(self) -> None:
        for i, (value, _label, _hint) in enumerate(self._choices):
            if value == OTHER_LABEL:
                self.paint(i)
                return
        self.paint(self.highlighted())
