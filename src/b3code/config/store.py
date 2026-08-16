"""Load/save de `.b3code/config.json` no cwd do projeto."""

import asyncio
import json
from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.utils.paths import atomic_write_text


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_cwd(cls, cwd: Path) -> "ConfigStore":
        return cls(cwd / ".b3code" / "config.json")

    def load(self) -> AppConfig:
        if not self.path.exists():
            return self._create_default()

        raw = self._read_json()
        cfg = AppConfig.model_validate(raw)
        if self._missing_exclude_fields(raw):
            self.save(cfg)
        return cfg

    def save(self, cfg: AppConfig) -> None:
        atomic_write_text(self.path, self._dump(cfg))

    async def save_async(self, cfg: AppConfig) -> None:
        await asyncio.to_thread(atomic_write_text, self.path, self._dump(cfg))

    def _create_default(self) -> AppConfig:
        cfg = AppConfig()
        self.save(cfg)
        return cfg

    def _read_json(self) -> dict[str, object]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _missing_exclude_fields(raw: dict[str, object]) -> bool:
        return "exclude_directories" not in raw or "exclude_extensions" not in raw

    @staticmethod
    def _dump(cfg: AppConfig) -> str:
        return cfg.model_dump_json(indent=2) + "\n"
