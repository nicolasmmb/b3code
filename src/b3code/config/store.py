"""Load/save de `.b3code/config.json` no cwd do projeto."""

import asyncio
import json
from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.utils.paths import atomic_write_text

_LEGACY_GATEWAY_KEYS = frozenset({"api_key", "api_endpoint", "api_models"})


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_cwd(cls, cwd: Path) -> "ConfigStore":
        return cls(cwd / ".b3code" / "config.json")

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = AppConfig()
            self.save(cfg)
            return cfg

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        cfg = AppConfig.model_validate(raw)
        needs_save = (
            "exclude_directories" not in raw
            or "exclude_extensions" not in raw
            or any(key in raw for key in _LEGACY_GATEWAY_KEYS)
        )
        if needs_save:
            self.save(cfg)
        return cfg

    def save(self, cfg: AppConfig) -> None:
        atomic_write_text(self.path, cfg.model_dump_json(indent=2) + "\n")

    async def save_async(self, cfg: AppConfig) -> None:
        text = cfg.model_dump_json(indent=2) + "\n"
        await asyncio.to_thread(atomic_write_text, self.path, text)
