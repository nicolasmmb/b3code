"""Converte exceção genérica de tool em `ModelRetry`.

`ModelRetry`, `ValueError` (guarda defensiva de segurança) e
`asyncio.CancelledError` passam intactos.


O PydanticAI re-invoca o modelo com o histórico completo (thinking/texto/tool
calls/returns já gerados) mais a nota de retry. Assim a LLM corrige só o passo
que falhou e segue — o raciocínio já emitido não é perdido nem reprocessado.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, cast

from pydantic_ai.exceptions import ModelRetry

_MAX_NOTE = 200



def _note(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = " ".join(str(exc).split())
    if not msg:
        return f"{name} — retry with a different approach"
    if len(msg) > _MAX_NOTE:
        msg = msg[: _MAX_NOTE - 1] + "…"
    return f"{name}: {msg} — retry with a different approach"

def model_retry[F: Callable[..., Any]](fn: F) -> F:
    """Re-levanta `ModelRetry`/cancelamento intactos; converte o resto em retry."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except (ModelRetry, ValueError, asyncio.CancelledError):
                raise
            except Exception as exc:
                raise ModelRetry(_note(exc)) from exc

        _async_wrapper.__doc__ = fn.__doc__
        return cast(F, _async_wrapper)

    @functools.wraps(fn)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ModelRetry, ValueError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise ModelRetry(_note(exc)) from exc

    _sync_wrapper.__doc__ = fn.__doc__
    return cast(F, _sync_wrapper)
