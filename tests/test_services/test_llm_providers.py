from backend.config import LLMSettings
from backend.services import llm_providers


def test_frontier_models_are_registered():
    assert llm_providers.OpenAIProvider.MODELS["gpt-5.5"] == "gpt-5.5-2026-04-23"
    assert (
        llm_providers.OpenAIProvider.MODELS["gpt-5.5-pro"]
        == "gpt-5.5-pro-2026-04-23"
    )
    assert llm_providers.AnthropicProvider.MODELS["claude-opus-4-7"] == "claude-opus-4-7"

    assert llm_providers.PROVIDER_MAP["gpt-5.5"] is llm_providers.OpenAIProvider
    assert llm_providers.PROVIDER_MAP["gpt-5.5-pro"] is llm_providers.OpenAIProvider
    assert llm_providers.PROVIDER_MAP["claude-opus-4-7"] is llm_providers.AnthropicProvider


def test_dashboard_frontier_defaults_and_picker_order():
    assert LLMSettings.model_fields["dashboard_model"].default == "gpt-5.5"
    assert LLMSettings.model_fields["dashboard_fallback_models"].default == [
        "claude-opus-4-7",
        "gemini-2.5-pro",
        "gpt-4o",
    ]
    assert LLMSettings.available_dashboard_models() == [
        "gpt-5.5",
        "gpt-5.5-pro",
        "claude-opus-4-7",
        "gemini-2.5-pro",
    ]


def test_list_available_models_includes_frontier_keys():
    models = llm_providers.list_available_models()

    assert "gpt-5.5" in models
    assert "gpt-5.5-pro" in models
    assert "claude-opus-4-7" in models
