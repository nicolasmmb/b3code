"""Escolhe o backend: Azure JSON (gateway) ou id nativo do Pydantic AI."""

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from b3code.config.schema import AppConfig


def build_model(cfg: AppConfig) -> Model | str:
    if cfg.use_provider_gateway:
        if not cfg.api_key or not cfg.api_endpoint:
            raise RuntimeError("set api_key and api_endpoint in .b3code/config.json")
        return OpenAIChatModel(
            cfg.selected_model,
            provider=AzureProvider(
                azure_endpoint=cfg.api_endpoint,
                api_key=cfg.api_key,
            ),
        )
    # "openai:gpt-5.2" — infer_model lê OPENAI_API_KEY (e o resto) do ambiente.
    return cfg.selected_model
