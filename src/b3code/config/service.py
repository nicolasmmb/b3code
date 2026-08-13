"""Único escritor de AppConfig."""

from __future__ import annotations

from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.catalog import ModelCatalog


class ConfigService:
    def __init__(
        self,
        store: ConfigStore,
        config: AppConfig | None = None,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self.store = store
        self._config = config if config is not None else store.load()
        self.catalog = catalog or ModelCatalog()

    @property
    def config(self) -> AppConfig:
        return self._config

    def select_model(self, name: str) -> None:
        allowed = self.catalog.available(self._config)
        if name not in allowed:
            raise ValueError(f"model {name!r} not in catalog")
        self._config.selected_model = name
        if self._config.use_provider_gateway and name in self._config.api_models:
            self._config.api_models.remove(name)
            self._config.api_models.insert(0, name)
        self.store.save(self._config)

    def toggle_gateway(self, on: bool) -> None:
        self._config.use_provider_gateway = on
        if (
            on
            and self._config.api_models
            and self._config.selected_model not in self._config.api_models
        ):
            self._config.selected_model = self._config.api_models[0]
        self.store.save(self._config)

    def persist_allowed_path(self, path: Path) -> None:
        text = str(path.resolve())
        if text in self._config.shell_allowed_paths:
            return
        self._config.shell_allowed_paths.append(text)
        self.store.save(self._config)

    def set_multiline(self, on: bool) -> None:
        self._config.multiline = on
        self.store.save(self._config)
