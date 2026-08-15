"""Card de pergunta. Other é uma linha do card, não o PromptBar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Input, Static

from b3code.services.questions import OTHER_LABEL, Question
from b3code.ui.widgets.choicebar import ChoiceBar, QuietOptions


class QuestionBar(ChoiceBar):
    SUMMARY_ID = "question-summary"
    OPTIONS_ID = "question-options"
    FALLBACK = OTHER_LABEL

    def compose(self) -> ComposeResult:
        yield Static("", id=self.SUMMARY_ID)
        yield QuietOptions(id=self.OPTIONS_ID)
        other = Input(placeholder="your answer", id="question-other")
        other.display = False
        yield other

    def show_question(self, item: Question, index: int, total: int, accent: str) -> None:
        prefix = f"({index + 1}/{total}) " if total > 1 else ""
        choices = tuple((opt.label, opt.label, opt.description) for opt in item.options)
        self.set_choices(choices)
        self.hide_other()
        self.set_summary(f"▸  {prefix}{item.question}", accent)

    def show_other(self) -> None:
        field = self.query_one("#question-other", Input)
        field.display = True
        field.value = ""
        field.focus()

    def hide_other(self) -> None:
        field = self.query_one("#question-other", Input)
        field.display = False
        field.value = ""

    def other_text(self) -> str:
        return self.query_one("#question-other", Input).value.strip()

    def other_visible(self) -> bool:
        return bool(self.query_one("#question-other", Input).display)
