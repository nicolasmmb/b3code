from textual.app import App

from b3code.ui.widgets.permission import PermissionPicker
from b3code.ui.widgets.planbar import PlanBar


async def test_permission_picker_paint_and_move():
    class Mini(App):
        def compose(self):
            yield PermissionPicker(id="permission")

    app = Mini()
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.query_one(PermissionPicker)
        picker.show("ls /tmp", "/tmp")
        assert picker.display
        assert picker.current() == "once"
        picker.move(1)
        assert picker.current() == "always"
        picker.move(1)
        assert picker.current() == "deny"
        picker.hide()
        assert picker.display is False


async def test_plan_bar_paint_and_move():
    class Mini(App):
        def compose(self):
            yield PlanBar(id="plan-bar")

    app = Mini()
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(PlanBar)
        bar.show("# Add auth\n\n## Context\nx\n")
        assert bar.display
        assert bar.current() == "approve"
        bar.move(1)
        assert bar.current() == "revise"
        bar.move(1)
        assert bar.current() == "quit"
        bar.hide()
        assert bar.display is False


async def test_choicebar_set_choices_and_wrap():
    from b3code.ui.widgets.choicebar import ChoiceBar

    class Dynamic(ChoiceBar):
        CHOICES = (("a", "a", ""),)
        SUMMARY_ID = "dyn-summary"
        OPTIONS_ID = "dyn-options"
        FALLBACK = "a"

    class Mini(App):
        def compose(self):
            yield Dynamic(id="dyn")

    app = Mini()
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(Dynamic)
        bar.set_choices((("a", "a", ""), ("b", "b", ""), ("c", "c", "")))
        bar.set_summary("pick")
        assert bar.current() == "a"
        bar.move(1, wrap=True)
        assert bar.current() == "b"
        bar.move(-1, wrap=True)
        assert bar.current() == "a"
        bar.move(-1, wrap=True)
        assert bar.current() == "c"
