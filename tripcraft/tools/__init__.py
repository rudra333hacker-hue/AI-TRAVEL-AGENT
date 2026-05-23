import logging
from typing import Any
from tripcraft.tools import flights, hotels, weather, places, transportation, web_search

logger = logging.getLogger("tripcraft")

class ToolRegistry:
    def __init__(self, config):
        self._tools = {}
        self._definitions = []
        self._config = config

        # Always available (transportation and weather have fallback/keyless options)
        self._register("get_weather_forecast", weather.get_weather_forecast, weather.DEFINITION)
        self._register("search_transportation", transportation.search, transportation.DEFINITION)
        self._register("search_web", web_search.search_web, web_search.DEFINITION)

        flights_tool = flights.FlightSearch(config)
        self._register("search_flights", flights_tool.search, flights.DEFINITION)
        
        hotels_tool = hotels.HotelSearch(config)
        self._register("search_hotels", hotels_tool.search, hotels.DEFINITION)

        # Conditional on API keys
        if config.has_foursquare:
            places_tool = places.PlaceSearch(config)
            self._register("search_places", places_tool.search, places.DEFINITION)
        else:
            logger.warning("Foursquare API key missing. Places search tool is disabled.")

    def _register(self, name: str, func, definition: dict):
        self._tools[name] = func
        self._definitions.append(definition)

    @property
    def definitions(self) -> list:
        return self._definitions

    @property
    def available_names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, name: str, args: dict) -> dict:
        if name not in self._tools:
            return {"error": f"Tool '{name}' is not available. API key may be missing or not configured."}
        try:
            return await self._tools[name](**args)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            return {"error": f"Tool '{name}' failed: {str(e)}"}

    def status(self) -> dict:
        return {
            "get_weather_forecast": {
                "status": "available",
                "provider": "open-meteo"
            },
            "search_flights": {
                "status": "available",
                "provider": "amadeus" if self._config.has_amadeus else "simulated"
            },
            "search_transportation": {
                "status": "available",
                "provider": "simulated + web enhancement"
            },
            "search_web": {
                "status": "available",
                "provider": "duckduckgo"
            },
            "search_hotels": {
                "status": "available",
                "provider": "foursquare" if self._config.has_foursquare else "simulated"
            },
            "search_places": {
                "status": "available" if self._config.has_foursquare else "unavailable",
                "provider": "foursquare"
            }
        }
