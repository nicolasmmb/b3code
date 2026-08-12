"""Load/save de `.b3code/config.json` no cwd do projeto."""

from pathlib import Path

from b3code.config.schema import AppConfig


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
        return AppConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, cfg: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(cfg.model_dump_json(indent=2) + "\n", encoding="utf-8")
