import httpx
from tripcraft.utils import request_with_retry

DEFINITION = {
    "type": "function",
    "function": {
        "name": "geocode",
        "description": "Resolve a city or place name into geographic coordinates (latitude/longitude), country, and timezone.",
        "parameters": {
            "type": "object",
            "properties": {
                "place_name": {"type": "string", "description": "City or region name, e.g., 'Paris' or 'Bali'"},
            },
            "required": ["place_name"],
        },
    },
}

# Simple module-level cache for geocode results
_cache = {}

async def geocode(place_name: str) -> dict:
    """Resolve place name to lat/lon/timezone using Open-Meteo Geocoding API."""
    normalized_name = place_name.strip().lower()
    if normalized_name in _cache:
        return _cache[normalized_name]

    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": place_name, "count": 1, "language": "en"}
    
    try:
        response = await request_with_retry("GET", url, params=params)
        if response.status_code != 200:
            return {"error": f"Geocoding service returned status {response.status_code}"}
        
        data = response.json()
        results = data.get("results", [])
        if not results:
            return {"error": f"Location not found: '{place_name}'"}
            
        loc = results[0]
        res = {
            "name": loc.get("name"),
            "country": loc.get("country"),
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "timezone": loc.get("timezone"),
            "population": loc.get("population"),
        }
        _cache[normalized_name] = res
        return res
    except Exception as e:
        return {"error": f"Failed to geocode location '{place_name}': {str(e)}"}
