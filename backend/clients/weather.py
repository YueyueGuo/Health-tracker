from __future__ import annotations

from datetime import datetime

import httpx

from backend.config import settings


class WeatherClient:
    """OpenWeatherMap API client for historical weather data."""

    BASE_URL = "https://api.openweathermap.org/data/3.0"

    def __init__(self):
        self._api_key = settings.weather.api_key
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self._http.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def get_historical_weather(
        self, lat: float, lng: float, dt: datetime
    ) -> dict | None:
        """Fetch historical weather for a location and timestamp.

        Uses the One Call API 3.0 timemachine endpoint.
        """
        if not self.is_configured:
            return None

        resp = await self._http.get(
            f"{self.BASE_URL}/onecall/timemachine",
            params={
                "lat": lat,
                "lon": lng,
                "dt": int(dt.timestamp()),
                "appid": self._api_key,
                "units": "metric",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # The timemachine endpoint returns data in a list
        weather_data = data.get("data", [{}])
        if not weather_data:
            return None

        w = weather_data[0] if isinstance(weather_data, list) else weather_data
        weather_info = w.get("weather", [{}])
        conditions = weather_info[0] if weather_info else {}

        return {
            "temp_c": w.get("temp"),
            "feels_like_c": w.get("feels_like"),
            "humidity": w.get("humidity"),
            "wind_speed": w.get("wind_speed"),
            "wind_gust": w.get("wind_gust"),
            "wind_deg": w.get("wind_deg"),
            "conditions": conditions.get("main"),
            "description": conditions.get("description"),
            "pressure": w.get("pressure"),
            "uv_index": w.get("uvi"),
            "raw_data": data,
        }
