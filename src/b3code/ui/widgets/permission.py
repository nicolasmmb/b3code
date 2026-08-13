"""Lista de permissão do Shell: setas + Enter. Highlight usa accent do JSON."""

from b3code.ui.widgets.choicebar import ChoiceBar, QuietOptions

__all__ = ["PermissionPicker", "QuietOptions"]


class PermissionPicker(ChoiceBar):
    CHOICES = (
        ("once", "once", "this time"),
        ("always", "always", "remember"),
        ("deny", "deny", ""),
    )
    SUMMARY_ID = "permission-summary"
    OPTIONS_ID = "permission-options"
    FALLBACK = "deny"

    def show(self, command: str, outside: str, accent: str | None = None) -> None:
        line = command.replace("\n", " ")
        if len(line) > 72:
            line = line[:71] + "…"
        extra = f"\n   {outside}" if outside else ""
        self.set_summary(f"▸  {line}{extra}", accent)
