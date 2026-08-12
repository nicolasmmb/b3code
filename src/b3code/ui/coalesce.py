"""Coalesce de text_delta: um Markdown.update por frame, não por token."""

from __future__ import annotations

FLUSH_INTERVAL = 1 / 30


def count_markdown_updates(n_deltas: int, duration_s: float = 0.0) -> int:
    """Quantos `update()` um burst de `n_deltas` gera com o timer de 30fps.

    Deltas que chegam no mesmo turno do loop (burst instantâneo) viram 1 flush.
    Se o stream se espalha em `duration_s`, há no máximo um flush por frame.
    """
    if n_deltas <= 0:
        return 0
    if duration_s <= 0:
        return 1
    return min(n_deltas, max(1, int(duration_s / FLUSH_INTERVAL) + 1))
