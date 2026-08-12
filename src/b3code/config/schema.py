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

    def select_model(self, name: str) -> None:
        """Valida contra o catálogo do modo atual e grava selected_model."""
        from b3code.services.catalog import list_models

        allowed = list_models(self)
        if name not in allowed:
            raise ValueError(f"model {name!r} not in catalog")
        self.selected_model = name
        # No gateway, o primeiro de api_models continua sendo o ativo.
        if self.use_provider_gateway and name in self.api_models:
            self.api_models.remove(name)
            self.api_models.insert(0, name)
