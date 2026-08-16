"""Escolhe o backend: Azure JSON (gateway) ou id nativo do Pydantic AI."""

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from b3code.config.schema import AppConfig


def build_model(cfg: AppConfig) -> Model | str:
    if not cfg.use_provider_gateway:
        # "openai:gpt-5.2" — infer_model lê OPENAI_API_KEY (e o resto) do ambiente.
        return cfg.selected_model
    if not cfg.gateway_api_key or not cfg.gateway_api_endpoint:
        raise RuntimeError(
            "set gateway_api_key and gateway_api_endpoint in .b3code/config.json"
        )
    return OpenAIChatModel(
        cfg.selected_model,
        provider=AzureProvider(
            azure_endpoint=cfg.gateway_api_endpoint,
            api_key=cfg.gateway_api_key,
        ),
    )
