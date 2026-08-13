"""Formatar exceções para o chat — resumo de uma linha + dump completo."""

from __future__ import annotations

import traceback

_SUMMARY_LIMIT = 160


def format_error(exc: BaseException) -> tuple[str, str]:
    """Retorna `(resumo, dump)`. O dump não omite causa nem traceback."""
    return error_summary(exc), error_detail(exc)


def error_summary(exc: BaseException) -> str:
    leaf = root_cause(exc)
    name = type(leaf).__name__
    msg = " ".join(str(leaf).split())
    if not msg:
        return name
    if len(msg) > _SUMMARY_LIMIT:
        msg = msg[: _SUMMARY_LIMIT - 1] + "…"
    return f"{name}: {msg}"


def error_detail(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)).rstrip() + "\n"


def split_error_summary(summary: str) -> tuple[str, str]:
    """Separa `Type: message` para o header no estilo ◆ Edit."""
    kind, sep, rest = summary.partition(": ")
    if sep and kind.isidentifier() and kind[:1].isupper():
        return kind, rest
    return "", summary


def root_cause(exc: BaseException) -> BaseException:
    seen: set[int] = set()
    current = exc
    while True:
        nxt = (
            current.__cause__ if current.__cause__ is not None else current.__context__
        )
        if nxt is None or id(nxt) in seen:
            return current
        seen.add(id(current))
        current = nxt
