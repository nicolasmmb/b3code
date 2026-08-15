"""Único escritor de AppConfig."""

from __future__ import annotations

from pathlib import Path

from b3code.config.schema import (
    THEME_COLOR_DEFAULTS,
    THINKING_LEVELS,
    AppConfig,
    McpServerConfig,
    ThemeColors,
    parse_hex,
    parse_mcp_name,
    slugify_theme,
)
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

    def set_thinking(self, level: str) -> None:
        name = level.strip().lower()
        if name not in THINKING_LEVELS:
            raise ValueError(f"thinking {level!r} not in {', '.join(THINKING_LEVELS)}")
        self._config.thinking = name
        self.store.save(self._config)

    def find_theme(self, name: str) -> ThemeColors | None:
        slug = slugify_theme(name)
        needle = name.strip().lower()
        for item in self._config.themes:
            if item.name == slug or item.display.lower() == needle:
                return item
        return None

    def select_theme(self, name: str) -> None:
        theme = self.find_theme(name)
        if theme is None:
            raise ValueError(f"theme {name!r} not saved")
        self._config.selected_theme = theme.name
        self.store.save(self._config)

    def set_theme_color(self, token: str, value: str) -> None:
        if token not in THEME_COLOR_DEFAULTS:
            raise ValueError(f"unknown color {token!r}")
        parsed = parse_hex(value, "")
        if not parsed:
            raise ValueError(f"invalid hex {value!r}")
        setattr(self._config.theme, token, parsed)
        self.store.save(self._config)

    def get_mcp_server(self, name: str) -> McpServerConfig:
        spec = self._config.mcp_servers.get(name)
        if spec is None:
            raise ValueError(f"unknown mcp server {name!r}")
        return spec

    def upsert_mcp_server(self, name: str, spec: McpServerConfig) -> None:
        key = parse_mcp_name(name)
        self._config.mcp_servers[key] = spec
        self.store.save(self._config)

    def remove_mcp_server(self, name: str) -> None:
        self.get_mcp_server(name)
        del self._config.mcp_servers[name]
        self.store.save(self._config)

    def set_mcp_enabled(self, name: str, enabled: bool) -> None:
        spec = self.get_mcp_server(name)
        self._config.mcp_servers[name] = spec.model_copy(update={"enabled": enabled})
        self.store.save(self._config)

    def save_theme(self, name: str) -> None:
        slug = slugify_theme(name)
        if not slug:
            raise ValueError(f"invalid theme name {name!r}")

        pretty = name.strip()
        payload = self._config.theme.model_dump()
        payload["name"] = slug
        payload["label"] = pretty if pretty != slug else ""
        clone = ThemeColors.model_validate(payload)
        existing = self.find_theme(slug)
        if existing is None:
            self._config.themes.append(clone)
        else:
            self._config.themes[self._config.themes.index(existing)] = clone
        self._config.selected_theme = slug
        self.store.save(self._config)
