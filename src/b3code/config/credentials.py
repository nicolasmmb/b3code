"""Checagens de credencial. Sem I/O — o caller decide o que fazer."""

from b3code.config.schema import AppConfig


def missing_gateway_credentials(config: AppConfig) -> str | None:
    if not config.use_provider_gateway:
        return None
    if config.gateway_api_key and config.gateway_api_endpoint:
        return None
    return "missing gateway_api_key or gateway_api_endpoint in .b3code/config.json"
