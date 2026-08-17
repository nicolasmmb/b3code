import asyncio

import pytest
from pydantic_ai.exceptions import ModelRetry

from b3code.utils.retry import model_retry


def _raises_os():
    raise OSError("boom")


def _raises_value():
    raise ValueError("boom")


def _raises_model_retry():
    raise ModelRetry("already handled")


def _raises_cancelled():
    raise asyncio.CancelledError()


async def _async_raises_os():
    raise OSError("disk full")


def test_sync_exception_becomes_model_retry():
    with pytest.raises(ModelRetry) as exc:
        model_retry(_raises_os)()
    assert "OSError" in str(exc.value)
    assert "boom" in str(exc.value)


def test_value_error_passes_through():
    # Guarda defensiva de segurança (ex.: path escape) não vira retry.
    with pytest.raises(ValueError, match="boom"):
        model_retry(_raises_value)()


def test_model_retry_passes_through():
    with pytest.raises(ModelRetry) as exc:
        model_retry(_raises_model_retry)()
    assert str(exc.value) == "already handled"


def test_cancelled_error_passes_through():
    with pytest.raises(asyncio.CancelledError):
        model_retry(_raises_cancelled)()


async def test_async_exception_becomes_model_retry():
    with pytest.raises(ModelRetry) as exc:
        await model_retry(_async_raises_os)()
    assert "OSError" in str(exc.value)
    assert "disk full" in str(exc.value)


def test_wraps_docstring():
    @model_retry
    def docced() -> str:
        """my tool doc"""
        return "ok"

    assert docced.__doc__ == "my tool doc"


def test_wraps_success_return():
    @model_retry
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
