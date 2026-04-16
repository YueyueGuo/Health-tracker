from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StravaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRAVA_")

    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""


class EightSleepSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EIGHT_SLEEP_")

    email: str = ""
    password: str = ""
    timezone: str = "America/New_York"


class WhoopSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WHOOP_")

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""


class WeatherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENWEATHERMAP_")

    api_key: str = ""


class LLMSettings(BaseSettings):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_ai_api_key: str = ""
    default_llm_provider: str = "claude-sonnet"


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: str = ""


class DiscordSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DISCORD_")

    bot_token: str = ""
    guild_id: int = 0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    database_url: str = "sqlite+aiosqlite:///./health_tracker.db"
    sync_interval_hours: int = 2
    host: str = "0.0.0.0"
    port: int = 8000

    # Sub-settings
    strava: StravaSettings = Field(default_factory=StravaSettings)
    eight_sleep: EightSleepSettings = Field(default_factory=EightSleepSettings)
    whoop: WhoopSettings = Field(default_factory=WhoopSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)


settings = Settings()
