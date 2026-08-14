"""Paleta do JSON → Theme do Textual e estilos Rich."""

from __future__ import annotations

from dataclasses import dataclass

from textual.color import Color
from textual.theme import Theme
from textual.widget import Widget

from b3code.config.schema import ThemeColors


@dataclass(frozen=True)
class RichPalette:
    add: str
    delete: str
    number: str
    context: str
    head: str
    file: str
    fold: str
    error: str
    error_msg: str
    muted: str


def to_textual(theme: ThemeColors) -> Theme:
    return Theme(
        name=theme.name,
        primary=theme.accent,
        secondary=theme.muted,
        accent=theme.accent,
        foreground=theme.foreground,
        background=theme.background,
        surface=theme.surface,
        panel=theme.surface,
        error=theme.error,
        success=theme.success,
        warning=theme.accent,
        dark=True,
        variables={
            "primary": theme.accent,
            "accent": theme.accent,
            "background": theme.background,
            "foreground": theme.foreground,
            "surface": theme.surface,
            "panel": theme.surface,
            "error": theme.error,
            "success": theme.success,
            "muted": theme.muted,
            "border": theme.border,
            "border-blurred": theme.border,
            "text-muted": theme.muted,
        },
    )


def rich_palette(theme: ThemeColors | None = None) -> RichPalette:
    theme = theme or ThemeColors()
    add_bg = Color.parse(theme.success).darken(0.55).hex
    del_fg = Color.parse(theme.error).lighten(0.25).hex
    del_bg = Color.parse(theme.error).darken(0.55).hex
    return RichPalette(
        add=f"{theme.success} on {add_bg}",
        delete=f"{del_fg} on {del_bg}",
        number=theme.muted,
        context=theme.foreground,
        head=theme.muted,
        file=theme.accent,
        fold=theme.muted,
        error=theme.error,
        error_msg=del_fg,
        muted=theme.muted,
    )


def theme_of(widget: Widget) -> ThemeColors:
    try:
        container = getattr(widget.app, "container", None)
    except Exception:
        return ThemeColors()
    if container is None:
        return ThemeColors()
    return container.config.theme
