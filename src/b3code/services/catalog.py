"""Catálogo de modelos do modo atual (gateway JSON vs known_model_names)."""

from __future__ import annotations

from pydantic_ai.models import known_model_names

from b3code.config.schema import AppConfig


class ModelCatalog:
    def __init__(self) -> None:
        self._known: list[str] | None = None

    def available(self, cfg: AppConfig) -> list[str]:
        if cfg.use_provider_gateway:
            return list(cfg.gateway_api_models)
        if self._known is None:
            self._known = list(known_model_names())
        return self._known

    def complete(self, cfg: AppConfig, prefix: str, limit: int = 40) -> list[str]:
        """Prefixo no começo do id primeiro; senão substring. Catálogo é grande."""
        needle = prefix.lower()
        names = self.available(cfg)
        starts = [name for name in names if name.lower().startswith(needle)]
        rest = [name for name in names if needle in name.lower() and name not in starts]
        return (starts + rest)[:limit]


_DEFAULT = ModelCatalog()


def list_models(cfg: AppConfig) -> list[str]:
    return _DEFAULT.available(cfg)


def complete_models(cfg: AppConfig, prefix: str, limit: int = 40) -> list[str]:
    return _DEFAULT.complete(cfg, prefix, limit)
