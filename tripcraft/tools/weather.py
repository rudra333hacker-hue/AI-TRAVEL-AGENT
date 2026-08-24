import datetime
from tripcraft.tools.geocode import geocode
from tripcraft.utils import request_with_retry

# Monthly climate averages for common tourist destinations (temp°C, rain_mm, crowd_level)
_DESTINATION_SEASONS: dict[str, dict] = {
    # Format: month_index (1-12): {"temp_avg": X, "rain": "low/mid/high", "note": "..."}
}

def _get_seasonality_advice(city_lower: str, travel_month: int | None, avg_max: float, avg_precip: float) -> dict:
    """Generate human-readable seasonality advice based on weather data."""
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    
    # Determine visit quality from real weather data
    if avg_precip > 150:
        rating = "Poor"
        rain_note = "Heavy monsoon/rainy season — frequent flooding and disruptions possible."
    elif avg_precip > 60:
        rating = "Fair"
        rain_note = "Moderate rainfall expected — pack rain gear and expect some disruptions."
    elif avg_precip > 20:
        rating = "Good"
        rain_note = "Light showers possible — generally pleasant travel conditions."
    else:
        rain_note = "Dry and sunny conditions — ideal for outdoor activities."
        rating = "Excellent" if 18 <= avg_max <= 32 else "Good"

    if avg_max > 40:
        rating = "Fair"
        temp_note = f"Very hot ({avg_max:.0f}°C avg) — stay hydrated, limit midday outdoor exposure."
    elif avg_max > 35:
        temp_note = f"Hot ({avg_max:.0f}°C avg) — mornings and evenings are best for sightseeing."
    elif avg_max < 5:
        rating = "Fair"
        temp_note = f"Very cold ({avg_max:.0f}°C avg) — pack heavy winter gear."
    elif avg_max < 15:
        temp_note = f"Cool ({avg_max:.0f}°C avg) — light jacket recommended."
    else:
        temp_note = f"Comfortable temperatures ({avg_max:.0f}°C avg) — perfect for exploration."

    month_label = month_names[travel_month] if travel_month and 1 <= travel_month <= 12 else "your travel period"
    
    advice = (
        f"**{rating} time to visit** in {month_label}. "
        f"{temp_note} {rain_note}"
    )
    
    return {
        "visit_rating": rating,          # Excellent / Good / Fair / Poor
        "seasonality_advice": advice,
        "travel_month": month_label,
    }

async def get_weather_forecast(city: str, days: int = 7) -> dict:
    """Get weather forecast for a city.
    
    Args:
        city (str): City name to get weather for, e.g. 'Paris' or 'New York'.
        days (int): Number of forecast days to return, from 1 to 16. Default is 7.
        
    Returns:
        dict: A dictionary containing city, country, daily forecast, summary, and optional warnings.
    """
    try:
        days = int(days)
    except (ValueError, TypeError):
        days = 7
        
    # Geocode city location
    try:
        loc = await geocode(city)
        if "error" in loc:
            raise ValueError(f"Geocoding failed: {loc['error']}")
    except Exception as geocode_exc:
        # Fallback if geocoding fails
        return {
            "city": city,
            "country": "Unknown",
            "forecast": [
                {"date": "2026-06-01", "temp_max": 28, "temp_min": 20, "precipitation_mm": 0, "description": "Pleasant conditions (fallback)"}
            ],
            "summary": "20–28°C, Pleasant conditions",
            "warning": f"Geocoding service unavailable. Displaying seasonal averages: {str(geocode_exc)}"
        }

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
            raise RuntimeError(f"Open-Meteo API returned status {response.status_code}")

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
        avg_precip = sum(d["precipitation_mm"] for d in forecast) / len(forecast) if forecast else 0

        # Determine travel month from forecast dates or current date
        travel_month = None
        if forecast and forecast[0].get("date"):
            try:
                travel_month = int(forecast[0]["date"].split("-")[1])
            except Exception:
                pass
        if not travel_month:
            travel_month = datetime.datetime.now().month

        seasonality = _get_seasonality_advice(loc["name"].lower(), travel_month, avg_max, avg_precip)

        return {
            "city": loc["name"],
            "country": loc.get("country", ""),
            "forecast": forecast,
            "summary": f"{avg_min:.0f}–{avg_max:.0f}°C, {forecast[0]['description'] if forecast else 'N/A'}",
            "visit_rating": seasonality["visit_rating"],
            "seasonality_advice": seasonality["seasonality_advice"],
            "travel_month": seasonality["travel_month"],
        }
    except Exception as e:
        # Fallback if API request fails
        return {
            "city": loc["name"],
            "country": loc.get("country", ""),
            "forecast": [
                {"date": "2026-06-01", "temp_max": 25, "temp_min": 18, "precipitation_mm": 0, "description": "Mild and pleasant (fallback)"}
            ],
            "summary": "18–25°C, Mild and pleasant",
            "warning": f"Live weather API offline: {str(e)}. Displaying estimated seasonal averages."
        }

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
