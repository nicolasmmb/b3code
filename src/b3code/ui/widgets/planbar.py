"""Aprovação do plano: a / s / q. Resumo estruturado (título + seções)."""

from b3code.ui.widgets.choicebar import ChoiceBar
from b3code.utils.planmeta import plan_meta


class PlanBar(ChoiceBar):
    CHOICES = (
        ("approve", "approve", "implement"),
        ("revise", "revise", "keep planning"),
        ("quit", "quit", "leave plan mode"),
    )
    SUMMARY_ID = "plan-summary"
    OPTIONS_ID = "plan-options"
    FALLBACK = "quit"

    def show(self, preview: str, accent: str | None = None) -> None:
        if not preview.strip():
            summary = "▸  plan  (no plan written yet)\n   a approve   s revise   q quit"
            self.set_summary(summary, accent)
            return
        title, heads, nlines = plan_meta(preview)
        bits = " · ".join(heads) if heads else "no sections"
        if len(bits) > 64:
            bits = bits[:63] + "…"
        summary = f"▸  {title}\n   {len(heads)} sections · {nlines} lines\n   {bits}"
        self.set_summary(summary, accent)
