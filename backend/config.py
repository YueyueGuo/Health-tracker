from __future__ import annotations

import pathlib

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

_DEFAULT_DATA_DIR = pathlib.Path.home() / ".health-tracker"
_DEFAULT_DB_URL = f"sqlite+aiosqlite:///{_DEFAULT_DATA_DIR / 'health_tracker.db'}"


class StravaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRAVA_", **_env_file_config)

    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""


# Public client credentials shipped with the Eight Sleep consumer mobile app.
# Used as defaults if EIGHT_SLEEP_CLIENT_ID / _CLIENT_SECRET are unset or blank.
_EIGHT_SLEEP_DEFAULT_CLIENT_ID = "0894c7f33bb94800a03f1f4df13a4f38"
_EIGHT_SLEEP_DEFAULT_CLIENT_SECRET = (
    "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"
)


class EightSleepSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EIGHT_SLEEP_", **_env_file_config)

    email: str = ""
    password: str = ""
    timezone: str = "America/New_York"

    # OAuth-style tokens. The refresh token is persisted back to .env after
    # the first successful email+password exchange; subsequent runs use only
    # the refresh token.
    refresh_token: str = ""
    # Persisted from the password grant response. Refresh grants don't
    # return userId, so caching it here lets the client skip a /me call.
    user_id: str = ""
    client_id: str = _EIGHT_SLEEP_DEFAULT_CLIENT_ID
    client_secret: str = _EIGHT_SLEEP_DEFAULT_CLIENT_SECRET

    @field_validator("client_id", mode="before")
    @classmethod
    def _client_id_default(cls, v):
        return v or _EIGHT_SLEEP_DEFAULT_CLIENT_ID

    @field_validator("client_secret", mode="before")
    @classmethod
    def _client_secret_default(cls, v):
        return v or _EIGHT_SLEEP_DEFAULT_CLIENT_SECRET


class WhoopSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WHOOP_", **_env_file_config)

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""


class WeatherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENWEATHERMAP_", **_env_file_config)

    api_key: str = ""


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(**_env_file_config)

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_ai_api_key: str = ""
    default_llm_provider: str = "claude-sonnet"
    # Model used for the dashboard insights (daily recommendation +
    # latest-workout takeaway). gpt-4o is the primary because the user's
    # OpenAI key is set and Anthropic is empty; haiku/sonnet were falling
    # through silently to OpenAI anyway. Paying for the better model on
    # the primary call now that the prompt is richer (goals, RPE,
    # feedback, baselines).
    dashboard_model: str = "gpt-4o"
    # Ordered fallback chain if the primary model fails.
    dashboard_fallback_models: list[str] = ["claude-sonnet", "gpt-4o-mini"]

    @field_validator("dashboard_fallback_models", mode="before")
    @classmethod
    def _parse_fallbacks(cls, v):
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(**_env_file_config)

    # App
    database_url: str = _DEFAULT_DB_URL
    sync_interval_hours: float = 2
    host: str = "0.0.0.0"
    port: int = 8000
    tailscale_hostname: str = ""

    # Weather provider. Supported values:
    #   "openmeteo"       — Open-Meteo ERA5 archive (default, free, no key)
    #   "openweathermap"  — OpenWeatherMap One Call 3.0 (requires paid subscription)
    # Overridable via WEATHER_PROVIDER in .env.
    weather_provider: str = "openmeteo"

    # Sub-settings
    strava: StravaSettings = Field(default_factory=StravaSettings)
    eight_sleep: EightSleepSettings = Field(default_factory=EightSleepSettings)
    whoop: WhoopSettings = Field(default_factory=WhoopSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)


settings = Settings()
