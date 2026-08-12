"""Única config persistida: 3 campos, de propósito."""

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    api_key: str = ""
    api_endpoint: str = ""
    # Primeiro item = modelo em uso. /model reordena e salva.
    api_models: list[str] = Field(default_factory=lambda: ["gpt-4o"])

    @property
    def model(self) -> str:
        return self.api_models[0] if self.api_models else "gpt-4o"

    def select_model(self, name: str) -> None:
        """Move `name` para o índice 0. Erro se não estiver na lista."""
        if name not in self.api_models:
            raise ValueError(f"model {name!r} not in api_models")
        self.api_models.remove(name)
        self.api_models.insert(0, name)
