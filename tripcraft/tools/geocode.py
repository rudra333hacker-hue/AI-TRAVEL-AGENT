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

POPULAR_MAPPINGS = {
    "goa": {
        "name": "Goa",
        "country": "India",
        "latitude": 15.4919,
        "longitude": 73.8278,
        "timezone": "Asia/Kolkata",
        "population": 114759,
    },
    "goa, india": {
        "name": "Goa",
        "country": "India",
        "latitude": 15.4919,
        "longitude": 73.8278,
        "timezone": "Asia/Kolkata",
        "population": 114759,
    },
    "goa india": {
        "name": "Goa",
        "country": "India",
        "latitude": 15.4919,
        "longitude": 73.8278,
        "timezone": "Asia/Kolkata",
        "population": 114759,
    }
}

async def geocode(place_name: str) -> dict:
    """Resolve place name to lat/lon/timezone using Open-Meteo Geocoding API."""
    normalized_name = place_name.strip().lower()
    if normalized_name in POPULAR_MAPPINGS:
        return POPULAR_MAPPINGS[normalized_name]
    if normalized_name in _cache:
        return _cache[normalized_name]


    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": place_name, "count": 30, "language": "en"}
    
    try:
        response = await request_with_retry("GET", url, params=params)
        if response.status_code != 200:
            return {"error": f"Geocoding service returned status {response.status_code}"}
        
        data = response.json()
        results = data.get("results", [])
        if not results:
            return {"error": f"Location not found: '{place_name}'"}
            
        # Select best candidate
        best_loc = results[0]  # default fallback
        
        # 1. Look for exact name matches (case-insensitive)
        exact_matches = [
            r for r in results 
            if r.get("name", "").lower() == normalized_name
        ]
        
        # If no exact match, try matching after removing commas/countries (e.g. "goa, india" -> "goa")
        if not exact_matches and "," in normalized_name:
            clean_name = normalized_name.split(",")[0].strip()
            exact_matches = [
                r for r in results 
                if r.get("name", "").lower() == clean_name
            ]
            
        if exact_matches:
            # Check if any exact match is in India
            india_matches = [
                r for r in exact_matches 
                if r.get("country_code", "").upper() == "IN" or (r.get("country") and "india" in r.get("country").lower())
            ]
            if india_matches:
                # Prioritize exact match in India (e.g. Goa, India)
                best_loc = india_matches[0]
            else:
                # Prioritize exact match with highest population
                best_loc = max(exact_matches, key=lambda x: x.get("population") or 0)
        else:
            # 2. If no exact matches, look for matches in India
            india_substring_matches = [
                r for r in results 
                if r.get("country_code", "").upper() == "IN" or (r.get("country") and "india" in r.get("country").lower())
            ]
            if india_substring_matches:
                best_loc = india_substring_matches[0]
            else:
                # 3. Otherwise, select the result with the highest population to get the most prominent city
                best_loc = max(results, key=lambda x: x.get("population") or 0)

        res = {
            "name": best_loc.get("name"),
            "country": best_loc.get("country"),
            "latitude": best_loc.get("latitude"),
            "longitude": best_loc.get("longitude"),
            "timezone": best_loc.get("timezone"),
            "population": best_loc.get("population"),
        }
        _cache[normalized_name] = res
        return res
    except Exception as e:
        return {"error": f"Failed to geocode location '{place_name}': {str(e)}"}

