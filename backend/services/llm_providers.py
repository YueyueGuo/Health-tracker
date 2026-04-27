from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)


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
    async def query_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict,
        schema_name: str = "response",
        max_tokens: int = 1024,
    ) -> dict:
        """Query the model and return a parsed JSON dict matching `schema`."""
        ...

    @abstractmethod
    async def close(self):
        ...


class AnthropicProvider(LLMProvider):
    """Claude models via Anthropic SDK."""

    MODELS = {
        "claude-sonnet": "claude-sonnet-4-20250514",
        "claude-opus": "claude-opus-4-20250514",
        "claude-opus-4-7": "claude-opus-4-7",
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

    async def query_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict,
        schema_name: str = "response",
        max_tokens: int = 1024,
    ) -> dict:
        """Use Anthropic tool-use to coerce the model into schema-compliant JSON."""
        import json as _json

        tool_def = {
            "name": schema_name,
            "description": f"Emit a {schema_name} object that strictly matches the schema.",
            "input_schema": schema,
        }
        response = await self._client.messages.create(
            model=self._model_id,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": schema_name},
            messages=[{"role": "user", "content": user_message}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        # Fallback: if text returned, try to parse.
        text_parts = [
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ]
        text = "\n".join(text_parts).strip()
        if text:
            return _json.loads(text)
        raise ValueError("Anthropic returned no usable structured content")

    async def close(self):
        await self._client.close()


class OpenAIProvider(LLMProvider):
    """GPT models via OpenAI SDK."""

    MODELS = {
        "gpt-5.5": "gpt-5.5-2026-04-23",
        "gpt-5.5-pro": "gpt-5.5-pro-2026-04-23",
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

    async def query_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict,
        schema_name: str = "response",
        max_tokens: int = 1024,
    ) -> dict:
        import json as _json

        expected_keys = list((schema.get("properties") or {}).keys())
        augmented_system = (
            system_prompt
            + "\n\nRespond with a single JSON object that matches this schema EXACTLY.\n"
            + f"Top-level keys MUST be exactly: {expected_keys}\n"
            + "Do NOT wrap fields in sub-objects. String fields must be plain strings, "
            + "array fields must be JSON arrays of strings.\n"
            + f"Schema:\n{_json.dumps(schema, indent=2)}\n"
        )
        strict_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": schema,
                "strict": True,
            },
        }
        messages = [
            {"role": "system", "content": augmented_system},
            {"role": "user", "content": user_message},
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=max_tokens,
                response_format=strict_schema,
            )
        except Exception as e:
            # Older models (or models whose schema OpenAI rejects in
            # strict mode) fall back to json_object. Log so a persistent
            # fallback is visible rather than silently costing 2 RTTs.
            logger.warning(
                "OpenAI json_schema strict failed on %s, falling back to json_object: %s",
                self._model_id, e,
            )
            response = await self._client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        text = response.choices[0].message.content or ""
        return _json.loads(text)

    async def close(self):
        await self._client.close()


def _sanitize_for_gemini(schema: dict) -> dict:
    """Strip JSON-Schema keys Gemini doesn't understand."""
    UNSUPPORTED = {"title", "default", "additionalProperties", "$defs", "$ref", "allOf", "oneOf", "anyOf"}
    def _walk(node):
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items() if k not in UNSUPPORTED}
        if isinstance(node, list):
            return [_walk(x) for x in node]
        return node
    return _walk(schema)


def _build_gemini_example(schema: dict) -> dict:
    """Build a minimal JSON example that matches the schema for few-shot prompting."""
    def _example(node):
        if not isinstance(node, dict):
            return None
        t = node.get("type")
        if "enum" in node and node["enum"]:
            return node["enum"][0]
        if t == "string":
            return "..."
        if t == "integer":
            return 0
        if t == "number":
            return 0.0
        if t == "boolean":
            return False
        if t == "array":
            return [_example(node.get("items", {}))]
        if t == "object":
            return {k: _example(v) for k, v in (node.get("properties") or {}).items()}
        return None
    return _example(schema) or {}


class GoogleProvider(LLMProvider):
    """Gemini models via Google Generative AI SDK."""

    MODELS = {
        # Legacy aliases (kept for backward compat).
        "gemini-pro": "gemini-2.5-pro",
        "gemini-flash": "gemini-2.5-flash",
        "gemini-2-flash": "gemini-2.0-flash",
        # Current canonical names.
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
        "gemini-2.0-flash": "gemini-2.0-flash",
    }

    def __init__(self, model_key: str = "gemini-pro"):
        import google.generativeai as genai

        self.name = model_key
        self._model_id = self.MODELS.get(model_key, model_key)
        genai.configure(api_key=settings.llm.google_ai_api_key)
        # NOTE: we intentionally don't cache a GenerativeModel instance
        # here. Both ``query`` and ``query_structured`` create a fresh
        # model per call so the system_instruction is request-scoped.

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

    async def query_structured(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict,
        schema_name: str = "response",
        max_tokens: int = 1024,
    ) -> dict:
        """Gemini: inline schema + example in the system prompt (legacy SDK's
        ``response_schema`` is unreliable). Also pass response_schema as a
        best-effort hint to models that support it."""
        import google.generativeai as genai
        import json as _json

        cleaned = _sanitize_for_gemini(schema)
        example = _build_gemini_example(cleaned)
        expected_keys = list((schema.get("properties") or {}).keys())

        augmented_system = (
            system_prompt
            + "\n\nYou MUST respond with a single JSON object that matches this schema EXACTLY.\n"
            + f"Top-level keys MUST be exactly: {expected_keys}\n"
            + "Do NOT wrap the response in any outer key. Do NOT add commentary.\n"
            + f"Schema:\n{_json.dumps(cleaned, indent=2)}\n"
            + f"Example (replace values with yours):\n{_json.dumps(example, indent=2)}\n"
        )

        model = genai.GenerativeModel(
            self._model_id,
            system_instruction=augmented_system,
        )
        try:
            config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                response_schema=cleaned,
                max_output_tokens=max_tokens,
            )
            response = await model.generate_content_async(user_message, generation_config=config)
        except Exception as e:
            # Gemini's `response_schema` support is model-dependent; when
            # it's rejected we still get JSON via mime_type + inlined
            # schema in the system prompt. Log so the fallback isn't
            # silent.
            logger.warning(
                "Gemini response_schema failed on %s, falling back to mime-only: %s",
                self._model_id, e,
            )
            config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=max_tokens,
            )
            response = await model.generate_content_async(user_message, generation_config=config)
        text = response.text if response.text else ""
        return _json.loads(text)

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
