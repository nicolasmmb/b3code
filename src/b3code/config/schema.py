"""Config persistida. JSON antigo (sem os campos novos) continua válido."""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_ACCENT = "#c9a227"
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class AppConfig(BaseModel):
    # true = Azure do JSON é o gateway. false = catálogo pydantic-ai.
    use_provider_gateway: bool = True
    api_key: str = ""
    api_endpoint: str = ""
    api_models: list[str] = Field(default_factory=lambda: ["gpt-4o"])
    # Modelo ativo. No gateway é um item de api_models; no catálogo é provider:model.
    selected_model: str = ""
    # Paths absolutos que o Shell pode usar sem perguntar de novo.
    shell_allowed_paths: list[str] = Field(default_factory=list)
    accent: str = DEFAULT_ACCENT
    # true = paste preserva \\n; Shift+Enter / Alt+Enter inserem newline.
    # false = composer de uma linha (Enter envia; newline não entra).
    multiline: bool = True

    @field_validator("accent", mode="before")
    @classmethod
    def accent_hex(cls, value: object) -> str:
        if isinstance(value, str) and _HEX.match(value.strip()):
            return value.strip()
        return DEFAULT_ACCENT

    @model_validator(mode="after")
    def _default_selected(self) -> "AppConfig":
        if not self.selected_model:
            self.selected_model = self.api_models[0] if self.api_models else "gpt-4o"
        return self

    @property
    def model(self) -> str:
        return self.selected_model
