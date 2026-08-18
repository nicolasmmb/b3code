"""Helpers de texto sem dependência de UI ou services."""


def truncate_chars(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[truncated]", True
