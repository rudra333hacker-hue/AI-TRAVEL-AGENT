import logging
import re
import asyncio

logger = logging.getLogger("tripcraft")

# Module-level cache for geocode results
_cache = {}

# Hardcoded fallbacks for the most commonly searched cities (ensures reliability)
POPULAR_MAPPINGS = {
    "goa":      {"name": "Goa",      "country": "India",       "latitude": 15.4919,  "longitude": 73.8278,  "timezone": "Asia/Kolkata"},
    "paris":    {"name": "Paris",    "country": "France",      "latitude": 48.8566,  "longitude": 2.3522,    "timezone": "Europe/Paris"},
    "london":   {"name": "London",   "country": "United Kingdom","latitude": 51.5074, "longitude": -0.1278,   "timezone": "Europe/London"},
    "mumbai":   {"name": "Mumbai",   "country": "India",       "latitude": 19.0760,  "longitude": 72.8777,   "timezone": "Asia/Kolkata"},
    "delhi":    {"name": "Delhi",    "country": "India",       "latitude": 28.7041,  "longitude": 77.1025,   "timezone": "Asia/Kolkata"},
    "bangalore":{"name": "Bangalore","country": "India",       "latitude": 12.9716,  "longitude": 77.5946,   "timezone": "Asia/Kolkata"},
    "tokyo":    {"name": "Tokyo",    "country": "Japan",       "latitude": 35.6762,  "longitude": 139.6503,  "timezone": "Asia/Tokyo"},
    "dubai":    {"name": "Dubai",    "country": "UAE",         "latitude": 25.2048,  "longitude": 55.2708,   "timezone": "Asia/Dubai"},
    "bangkok":  {"name": "Bangkok",  "country": "Thailand",    "latitude": 13.7563,  "longitude": 100.5018,  "timezone": "Asia/Bangkok"},
    "new york": {"name": "New York", "country": "United States","latitude": 40.7128, "longitude": -74.0060,  "timezone": "America/New_York"},
    "sydney":   {"name": "Sydney",   "country": "Australia",   "latitude": -33.8688, "longitude": 151.2093,  "timezone": "Australia/Sydney"},
    "bali":     {"name": "Bali",     "country": "Indonesia",   "latitude": -8.3405,  "longitude": 115.0920,  "timezone": "Asia/Makassar"},
    "shimla":   {"name": "Shimla",   "country": "India",       "latitude": 31.1048,  "longitude": 77.1734,   "timezone": "Asia/Kolkata"},
    "manali":   {"name": "Manali",   "country": "India",       "latitude": 32.2396,  "longitude": 77.1887,   "timezone": "Asia/Kolkata"},
    "kerala":   {"name": "Kerala",   "country": "India",       "latitude": 10.8505,  "longitude": 76.2711,   "timezone": "Asia/Kolkata"},
    "jaipur":   {"name": "Jaipur",   "country": "India",       "latitude": 26.9124,  "longitude": 75.7873,   "timezone": "Asia/Kolkata"},
    "agra":     {"name": "Agra",     "country": "India",       "latitude": 27.1767,  "longitude": 78.0081,   "timezone": "Asia/Kolkata"},
    "chennai":  {"name": "Chennai",  "country": "India",       "latitude": 13.0827,  "longitude": 80.2707,   "timezone": "Asia/Kolkata"},
    "kolkata":  {"name": "Kolkata",  "country": "India",       "latitude": 22.5726,  "longitude": 88.3639,   "timezone": "Asia/Kolkata"},
    "hyderabad":{"name": "Hyderabad","country": "India",       "latitude": 17.3850,  "longitude": 78.4867,   "timezone": "Asia/Kolkata"},
    "pune":     {"name": "Pune",     "country": "India",       "latitude": 18.5204,  "longitude": 73.8567,   "timezone": "Asia/Kolkata"},
    "ahmedabad":{"name": "Ahmedabad","country": "India",       "latitude": 23.0225,  "longitude": 72.5714,   "timezone": "Asia/Kolkata"},
    "amsterdam":{"name": "Amsterdam","country": "Netherlands", "latitude": 52.3676,  "longitude": 4.9041,    "timezone": "Europe/Amsterdam"},
    "rome":     {"name": "Rome",     "country": "Italy",       "latitude": 41.9028,  "longitude": 12.4964,   "timezone": "Europe/Rome"},
    "barcelona":{"name": "Barcelona","country": "Spain",       "latitude": 41.3874,  "longitude": 2.1686,    "timezone": "Europe/Madrid"},
    "istanbul": {"name": "Istanbul", "country": "Turkey",      "latitude": 41.0082,  "longitude": 28.9784,   "timezone": "Europe/Istanbul"},
    "singapore":{"name": "Singapore","country": "Singapore",   "latitude": 1.3521,   "longitude": 103.8198,  "timezone": "Asia/Singapore"},
    "kuala lumpur":{"name":"Kuala Lumpur","country":"Malaysia","latitude":3.1390,    "longitude":101.6869,   "timezone":"Asia/Kuala_Lumpur"},
}


async def geocode(place_name: str) -> dict:
    """Resolve place name to lat/lon/timezone using a web-search-first approach.

    Strategy:
    1. Check hardcoded POPULAR_MAPPINGS first (fast, reliable).
    2. Check module-level cache.
    3. Use DuckDuckGo web search to find coordinates of the location.
    4. Fallback to Open-Meteo Geocoding API as a last resort.
    """
    normalized_name = place_name.strip().lower()

    # 1. Check hardcoded popular mappings
    if normalized_name in POPULAR_MAPPINGS:
        return dict(POPULAR_MAPPINGS[normalized_name])  # return a copy

    # 2. Check cache
    if normalized_name in _cache:
        return _cache[normalized_name]

    # 3. Try web search to find coordinates
    coords = await _resolve_via_web_search(place_name)
    if coords:
        _cache[normalized_name] = coords
        return coords

    # 4. Fallback: try Open-Meteo Geocoding API (original approach)
    coords = await _resolve_via_openmeteo(place_name)
    if coords:
        _cache[normalized_name] = coords
        return coords

    return {"error": f"Location not found: '{place_name}'"}


async def _resolve_via_web_search(place_name: str) -> dict | None:
    """Use DuckDuckGo web search to find coordinates of a place."""
    try:
        from duckduckgo_search import DDGS

        query = f"{place_name} latitude longitude coordinates"
        logger.info(f"Geocoding via web search: {query}")

        def _do_search(q: str) -> list:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=5):
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
            return results

        results = await asyncio.to_thread(_do_search, query)
        if not results:
            return None

        # Combine all snippets for broader matching
        combined = " ".join(
            f"{r.get('title', '')} {r.get('snippet', '')}" for r in results
        )

        # Pattern 1: "XX.XXXX, YY.YYYY" or "XX.XXXX° N, YY.YYYY° E"
        coord_patterns = [
            r'(-?\d+\.\d+)[°\s]*[NnSs]?[,;\s]+(-?\d+\.\d+)[°\s]*[EeWw]?',
            r'(-?\d+\.\d+)[°\s]*[NnSs]?[,\s]+(-?\d+\.\d+)[°\s]*[EeWw]?',
            r'lat[itude]*[:\s]*(-?\d+\.\d+)[,\s]+l[o]*[ng]*[:\s]*(-?\d+\.\d+)',
        ]

        for pattern in coord_patterns:
            match = re.search(pattern, combined)
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                # Validate: lat between -90 and 90, lon between -180 and 180
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    logger.info(f"Web search resolved '{place_name}' -> ({lat}, {lon})")
                    return {
                        "name": place_name.title(),
                        "country": "",
                        "latitude": lat,
                        "longitude": lon,
                        "timezone": "UTC",
                    }

        # Pattern 2: Try a more specific search for locations like "Goa, India"
        query2 = f"{place_name} coordinates lat long"
        results2 = await asyncio.to_thread(_do_search, query2)
        if results2:
            combined2 = " ".join(
                f"{r.get('title', '')} {r.get('snippet', '')}" for r in results2
            )
            for pattern in coord_patterns:
                match = re.search(pattern, combined2)
                if match:
                    lat = float(match.group(1))
                    lon = float(match.group(2))
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        logger.info(f"Web search (retry) resolved '{place_name}' -> ({lat}, {lon})")
                        return {
                            "name": place_name.title(),
                            "country": "",
                            "latitude": lat,
                            "longitude": lon,
                            "timezone": "UTC",
                        }

        return None

    except ImportError:
        logger.warning("duckduckgo_search not installed for geocoding fallback")
        return None
    except Exception as e:
        logger.warning(f"Web search geocoding failed for '{place_name}': {e}")
        return None


async def _resolve_via_openmeteo(place_name: str) -> dict | None:
    """Fallback: resolve using Open-Meteo Geocoding API."""
    try:
        import httpx
        from tripcraft.utils import request_with_retry

        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": place_name, "count": 10, "language": "en"}

        response = await request_with_retry("GET", url, params=params)
        if response.status_code != 200:
            return None

        data = response.json()
        results = data.get("results", [])
        if not results:
            return None

        best = results[0]
        return {
            "name": best.get("name", place_name.title()),
            "country": best.get("country", ""),
            "latitude": best.get("latitude"),
            "longitude": best.get("longitude"),
            "timezone": best.get("timezone", "UTC"),
        }
    except Exception as e:
        logger.warning(f"Open-Meteo geocoding failed for '{place_name}': {e}")
        return None
