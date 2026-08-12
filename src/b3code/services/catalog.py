"""Catálogo de modelos do modo atual (gateway JSON vs known_model_names)."""

from __future__ import annotations

from pydantic_ai.models import known_model_names

from b3code.config.schema import AppConfig


def list_models(cfg: AppConfig) -> list[str]:
    if cfg.use_provider_gateway:
        return list(cfg.api_models)
    return list(known_model_names())


def complete_models(cfg: AppConfig, prefix: str, limit: int = 40) -> list[str]:
    """Prefixo no começo do id primeiro; senão substring. Catálogo é grande."""
    needle = prefix.lower()
    names = list_models(cfg)
    starts = [name for name in names if name.lower().startswith(needle)]
    rest = [name for name in names if needle in name.lower() and name not in starts]
    return (starts + rest)[:limit]
