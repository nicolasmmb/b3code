"""Load/save de `.b3code/config.json` no cwd do projeto."""

import asyncio
import json
from pathlib import Path

from b3code.config.schema import AppConfig
from b3code.utils.paths import atomic_write_text

SCHEMA_REF = "./schema.json"


def config_schema() -> str:
    """JSON Schema do AppConfig, para o editor validar/autocompletar config.json."""
    schema = AppConfig.model_json_schema()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_REF,
        "title": "b3code configuration",
        **schema,
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


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
        self._ensure_schema()

    async def save_async(self, cfg: AppConfig) -> None:
        await asyncio.to_thread(atomic_write_text, self.path, self._dump(cfg))
        await asyncio.to_thread(self._ensure_schema)

    def _ensure_schema(self) -> None:
        if not self._schema_path().exists():
            atomic_write_text(self._schema_path(), config_schema())

    def _schema_path(self) -> Path:
        return self.path.parent / "schema.json"

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
        data = json.loads(cfg.model_dump_json())
        data["$schema"] = SCHEMA_REF
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
