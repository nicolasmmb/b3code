"""Factory do modelo Azure. Sem abstração de provider — Azure é o v1."""

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from b3code.config.schema import AppConfig


def build_model(cfg: AppConfig) -> OpenAIChatModel:
    if not cfg.api_key or not cfg.api_endpoint:
        raise RuntimeError("set api_key and api_endpoint in .b3code/config.json")
    return OpenAIChatModel(
        cfg.model,
        provider=AzureProvider(
            azure_endpoint=cfg.api_endpoint,
            api_key=cfg.api_key,
        ),
    )
