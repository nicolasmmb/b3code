import asyncio

import pytest
from pydantic_ai.exceptions import ModelRetry
from textual.app import App

from b3code.services.questions import QuestionGate, normalize_questions
from b3code.ui.widgets.question import QuestionBar


def test_normalize_adds_other():
    questions = normalize_questions(
        [{"question": "Pick", "options": [{"label": "A", "description": "one"}]}]
    )
    assert questions[0].options[-1].label == "Other"
    assert len(questions[0].options) == 2


def test_normalize_rejects_empty_and_multiselect():
    with pytest.raises(ModelRetry, match="at least one"):
        normalize_questions([])
    with pytest.raises(ModelRetry, match="multi_select"):
        normalize_questions(
            [
                {
                    "question": "Pick",
                    "options": [{"label": "A"}],
                    "multi_select": True,
                }
            ]
        )


async def test_gate_answer_and_dismiss():
    gate = QuestionGate()
    gate.on_ask = lambda qs: gate.answer("Pick: A")
    assert await gate.ask([{"question": "Pick", "options": [{"label": "A"}]}]) == "Pick: A"
    gate.on_ask = lambda qs: gate.dismiss()
    assert await gate.ask([{"question": "Pick", "options": [{"label": "A"}]}]) == "skipped"


async def test_gate_cancel_pending():
    gate = QuestionGate()
    gate.on_ask = lambda qs: None
    task = asyncio.create_task(gate.ask([{"question": "Pick", "options": [{"label": "A"}]}]))
    await asyncio.sleep(0)
    gate.cancel_pending()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_question_bar_paint_and_move():
    class Mini(App):
        def compose(self):
            yield QuestionBar(id="question")

    app = Mini()
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(QuestionBar)
        item = normalize_questions(
            [{"question": "Pick", "options": [{"label": "once"}, {"label": "always"}]}]
        )[0]
        bar.show_question(item, 0, 1, "#00b0e6")
        assert bar.display
        assert bar.current() == "once"
        bar.move(1)
        assert bar.current() == "always"
        bar.move(1, wrap=True)
        assert bar.current() == "Other"
        assert bar.query_one("#question-other-row").display
        assert bar.query_one("#question-other-hint").display
        assert not bar.query_one("#question-other").display
        bar.show_other()
        assert bar.other_visible()
        assert not bar.query_one("#question-other-hint").display
        assert bar.query_one("#question-other").display
        field = bar.query_one("#question-other")
        field.value = "hello"
        assert bar.other_text() == "hello"
        bar.insert("!")
        assert bar.other_text() == "hello!"
        bar.hide_other()
        assert bar.other_visible() is False
        assert bar.current() == "Other"
        assert bar.query_one("#question-other-hint").display
        bar.hide()
        assert bar.display is False
