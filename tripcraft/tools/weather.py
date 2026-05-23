from tripcraft.tools.geocode import geocode
from tripcraft.utils import request_with_retry

DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_weather_forecast",
        "description": "Get weather forecast for a city. Returns daily temps, rain, humidity for up to 16 days.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "days": {"type": "integer", "default": 7, "description": "Forecast days (1-16)"},
            },
            "required": ["city"],
        },
    },
}

async def get_weather_forecast(city: str, days: int = 7) -> dict:
    """Get weather forecast for a city by first geocoding the city and then querying Open-Meteo forecast API."""
    try:
        days = int(days)
    except (ValueError, TypeError):
        days = 7
    loc = await geocode(city)
    if "error" in loc:
        return loc

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
        "timezone": loc.get("timezone", "auto") or "auto",
        "forecast_days": min(days, 16),
    }

    try:
        response = await request_with_retry("GET", url, params=params)
        if response.status_code != 200:
            return {"error": f"Weather service returned status {response.status_code}"}

        data = response.json()
        daily = data.get("daily", {})
        forecast = []
        for i, date in enumerate(daily.get("time", [])):
            forecast.append({
                "date": date,
                "temp_max": daily["temperature_2m_max"][i],
                "temp_min": daily["temperature_2m_min"][i],
                "precipitation_mm": daily["precipitation_sum"][i],
                "description": _weather_code(daily["weathercode"][i]),
            })

        avg_max = sum(d["temp_max"] for d in forecast) / len(forecast) if forecast else 0
        avg_min = sum(d["temp_min"] for d in forecast) / len(forecast) if forecast else 0

        return {
            "city": loc["name"],
            "country": loc.get("country", ""),
            "forecast": forecast,
            "summary": f"{avg_min:.0f}–{avg_max:.0f}°C, {forecast[0]['description'] if forecast else 'N/A'}",
        }
    except Exception as e:
        return {"error": f"Failed to retrieve weather for '{city}': {str(e)}"}

def _weather_code(code: int) -> str:
    codes = {
        0: "Clear sky", 
        1: "Mainly clear", 
        2: "Partly cloudy", 
        3: "Overcast",
        45: "Foggy", 
        51: "Light drizzle", 
        61: "Light rain", 
        63: "Moderate rain",
        65: "Heavy rain", 
        71: "Light snow", 
        73: "Moderate snow", 
        80: "Rain showers",
        95: "Thunderstorm"
    }
    return codes.get(code, "Mixed conditions")
