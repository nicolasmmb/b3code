"""Lista de permissão do Shell: setas + Enter."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

CHOICES = (
    ("once", "once", "run this command once"),
    ("always", "always", "save path and always allow"),
    ("deny", "deny", "do not run"),
)


class PermissionPicker(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("", id="permission-summary")
        yield OptionList(id="permission-options")

    def show(self, command: str, outside: str) -> None:
        extra = f"\noutside: {outside}" if outside else ""
        self.query_one("#permission-summary", Static).update(
            f"allow this command?\n{command}{extra}"
        )
        options = self.query_one("#permission-options", OptionList)
        options.clear_options()
        options.add_options(
            [Option(f"{label}    {hint}") for _value, label, hint in CHOICES]
        )
        options.highlighted = 0
        self.display = True

    def hide(self) -> None:
        self.display = False

    def move(self, delta: int) -> None:
        options = self.query_one("#permission-options", OptionList)
        if delta > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()

    def current(self) -> str:
        idx = self.query_one("#permission-options", OptionList).highlighted
        if idx is None:
            return "deny"
        return CHOICES[idx][0]