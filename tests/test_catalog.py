from b3code.config.schema import AppConfig
from b3code.services.catalog import complete_models, list_models


def test_gateway_lists_json_models():
    cfg = AppConfig(use_provider_gateway=True, gateway_api_models=["a", "b"])
    assert list_models(cfg) == ["a", "b"]


def test_catalog_includes_known_openai():
    cfg = AppConfig(use_provider_gateway=False)
    names = list_models(cfg)
    assert any(n.startswith("openai:") for n in names)
    assert any(n.startswith("anthropic:") for n in names)


def test_complete_filters_substring():
    cfg = AppConfig(use_provider_gateway=False)
    hits = complete_models(cfg, "claude-sonnet")
    assert hits
    assert all("claude-sonnet" in h for h in hits)


def test_complete_prefers_provider_prefix():
    cfg = AppConfig(use_provider_gateway=False)
    hits = complete_models(cfg, "openai:")
    assert hits
    assert hits[0].startswith("openai:")
