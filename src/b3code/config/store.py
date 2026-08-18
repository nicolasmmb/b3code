"""Load/save do `config.json` global (único por usuário)."""

import json
from pathlib import Path

from b3code.config.dirs import b3code_home
from b3code.config.schema import AppConfig
from b3code.utils.paths import atomic_write_json

SCHEMA_REF = "./schema.json"


def config_schema() -> dict[str, object]:
    """JSON Schema do AppConfig, para o editor validar/autocompletar config.json."""
    schema = AppConfig.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_REF,
        "title": "b3code configuration",
        **schema,
    }


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_global(cls) -> "ConfigStore":
        return cls(b3code_home() / "config.json")

    def load(self) -> AppConfig:
        if not self.path.exists():
            return self._create_default()

        raw = self._read_json()
        cfg = AppConfig.model_validate(raw)
        if self._missing_exclude_fields(raw):
            self.save(cfg)
        return cfg

    def save(self, cfg: AppConfig) -> None:
        atomic_write_json(self.path, self._payload(cfg))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if not self._schema_path().exists():
            atomic_write_json(self._schema_path(), config_schema())

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
    def _payload(cfg: AppConfig) -> dict[str, object]:
        data = json.loads(cfg.model_dump_json())
        data["$schema"] = SCHEMA_REF
        return data
