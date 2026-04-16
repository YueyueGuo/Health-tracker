from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.config import settings


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_used: int | None = None


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    name: str

    @abstractmethod
    async def query(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def close(self):
        ...


class AnthropicProvider(LLMProvider):
    """Claude models via Anthropic SDK."""

    MODELS = {
        "claude-sonnet": "claude-sonnet-4-20250514",
        "claude-opus": "claude-opus-4-20250514",
        "claude-haiku": "claude-haiku-4-5-20251001",
    }

    def __init__(self, model_key: str = "claude-sonnet"):
        import anthropic

        self.name = model_key
        self._model_id = self.MODELS.get(model_key, model_key)
        self._client = anthropic.AsyncAnthropic(api_key=settings.llm.anthropic_api_key)

    async def query(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model_id,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        text_parts = []
        tool_results = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_results.append({"tool": block.name, "input": block.input})

        # If there are tool calls, we return them as structured info
        # The analysis engine will handle tool execution and re-query
        text = "\n".join(text_parts)
        if tool_results and not text:
            text = f"__TOOL_CALLS__:{__import__('json').dumps(tool_results)}"

        tokens = (
            (response.usage.input_tokens + response.usage.output_tokens)
            if response.usage
            else None
        )
        return LLMResponse(text=text, model=self._model_id, tokens_used=tokens)

    async def close(self):
        await self._client.close()


class OpenAIProvider(LLMProvider):
    """GPT models via OpenAI SDK."""

    MODELS = {
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-4-turbo": "gpt-4-turbo",
    }

    def __init__(self, model_key: str = "gpt-4o"):
        import openai

        self.name = model_key
        self._model_id = self.MODELS.get(model_key, model_key)
        self._client = openai.AsyncOpenAI(api_key=settings.llm.openai_api_key)

    async def query(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        kwargs: dict = {
            "model": self._model_id,
            "messages": messages,
            "max_tokens": 4096,
        }
        if tools:
            # Convert Anthropic tool format to OpenAI function format
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = choice.message.content or ""
        tokens = (
            (response.usage.prompt_tokens + response.usage.completion_tokens)
            if response.usage
            else None
        )
        return LLMResponse(text=text, model=self._model_id, tokens_used=tokens)

    async def close(self):
        await self._client.close()


class GoogleProvider(LLMProvider):
    """Gemini models via Google Generative AI SDK."""

    MODELS = {
        "gemini-pro": "gemini-1.5-pro",
        "gemini-flash": "gemini-1.5-flash",
        "gemini-2-flash": "gemini-2.0-flash",
    }

    def __init__(self, model_key: str = "gemini-pro"):
        import google.generativeai as genai

        self.name = model_key
        self._model_id = self.MODELS.get(model_key, model_key)
        genai.configure(api_key=settings.llm.google_ai_api_key)
        self._model = genai.GenerativeModel(
            self._model_id,
            system_instruction=None,  # Set per query
        )

    async def query(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        import google.generativeai as genai

        model = genai.GenerativeModel(
            self._model_id,
            system_instruction=system_prompt,
        )
        response = await model.generate_content_async(user_message)
        text = response.text if response.text else ""
        tokens = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens = (
                response.usage_metadata.prompt_token_count
                + response.usage_metadata.candidates_token_count
            )
        return LLMResponse(text=text, model=self._model_id, tokens_used=tokens)

    async def close(self):
        pass  # No persistent connection to close


# ── Provider registry ────────────────────────────────────────────────

PROVIDER_MAP: dict[str, type[LLMProvider]] = {}

# Register Anthropic models
for key in AnthropicProvider.MODELS:
    PROVIDER_MAP[key] = AnthropicProvider

# Register OpenAI models
for key in OpenAIProvider.MODELS:
    PROVIDER_MAP[key] = OpenAIProvider

# Register Google models
for key in GoogleProvider.MODELS:
    PROVIDER_MAP[key] = GoogleProvider


def get_provider(model_key: str | None = None) -> LLMProvider:
    """Get an LLM provider instance by model key."""
    key = model_key or settings.llm.default_llm_provider
    provider_class = PROVIDER_MAP.get(key)
    if not provider_class:
        raise ValueError(
            f"Unknown model: {key}. Available: {', '.join(sorted(PROVIDER_MAP.keys()))}"
        )
    return provider_class(model_key=key)


def list_available_models() -> list[str]:
    """List all available model keys."""
    return sorted(PROVIDER_MAP.keys())
