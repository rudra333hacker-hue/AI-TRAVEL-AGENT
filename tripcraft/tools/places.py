import logging
import random
from typing import Dict, Any, List
from tripcraft.tools.geocode import geocode
from tripcraft.utils import request_with_retry

logger = logging.getLogger("tripcraft")

class PlaceSearch:
    SEARCH_URL = "https://api.foursquare.com/v3/places/search"

    def __init__(self, config):
        self._config = config
        self._key = config.foursquare_key

    async def search(self, city: str, query: str = None, limit: int = 5) -> dict:
        """Find places of interest, attractions, dining, or local hidden gems in a city.
        
        Args:
            city (str): City name to find places in, e.g. 'Paris' or 'Goa'.
            query (str): Optional search query or type of place, e.g. 'restaurants', 'museums', 'hidden gems'.
            limit (int): Maximum number of places to return. Default is 5.
            
        Returns:
            dict: A dictionary containing a list of places with details like name, categories, address, map links, images, and warnings.
        """
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 5

        warning_message = None
        try:
            # Step 1: Geocode city name to lat/lon
            loc = await geocode(city)
            if "error" in loc:
                raise ValueError(f"Geocoding failed: {loc['error']}")

            lat = loc["latitude"]
            lon = loc["longitude"]
            resolved_city_name = loc.get("name", city)
        except Exception as geocode_exc:
            logger.warning(f"Geocoding failed in places search: {geocode_exc}. Using default coordinates.")
            lat = 19.0760
            lon = 72.8777
            resolved_city_name = city
            warning_message = f"Could not geocode city '{city}'. Displaying fallback recommendations."

        places = []
        foursquare_success = False

        # Step 2: Query Foursquare if key is configured
        if self._config.has_foursquare and not warning_message:
            try:
                headers = {
                    "Accept": "application/json",
                    "Authorization": self._key
                }
                params = {
                    "ll": f"{lat},{lon}",
                    "limit": limit
                }
                if query:
                    params["query"] = query

                logger.info(f"Searching Foursquare places in {resolved_city_name} ({lat},{lon}) for query: {query}")
                response = await request_with_retry(
                    "GET",
                    self.SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=10.0
                )

                if response.status_code == 200:
                    raw = response.json().get("results", [])
                    for item in raw:
                        cats = [c.get("name") for c in item.get("categories", [])]
                        loc_info = item.get("location", {})
                        geocodes = item.get("geocodes", {}).get("main", {})
                        plat = geocodes.get("latitude")
                        plon = geocodes.get("longitude")
                        
                        if plat is not None and plon is not None:
                            maps_link = f"https://www.google.com/maps/search/?api=1&query={plat},{plon}"
                        else:
                            maps_link = f"https://www.google.com/maps/search/?api=1&query={item.get('name', 'Unknown Place').replace(' ', '+')}+{resolved_city_name.replace(' ', '+')}"

                        places.append({
                            "name": item.get("name", "Unknown Place"),
                            "categories": cats,
                            "address": loc_info.get("formatted_address") or loc_info.get("address") or "",
                            "distance_meters": item.get("distance"),
                            "latitude": plat,
                            "longitude": plon,
                            "maps_link": maps_link,
                            "image_url": f"https://source.unsplash.com/featured/600x400/?{item.get('name', 'place').replace(' ', '+')}+{resolved_city_name.replace(' ', '+')}",
                        })
                    foursquare_success = True
                else:
                    logger.warning(f"Foursquare API returned status {response.status_code}")
                    warning_message = "Live places API returned an error. Using simulated place recommendations."
            except Exception as ex:
                logger.warning(f"Foursquare places search failed: {ex}. Falling back to simulated places.")
                warning_message = f"Live places API timed out or failed: {str(ex)}. Using simulated place recommendations."

        # Step 3: Fallback to simulated places
        if not foursquare_success:
            logger.info(f"Generating simulated places list for {resolved_city_name}")
            seed_val = sum(ord(c) for c in resolved_city_name) + (sum(ord(c) for c in query) if query else 0)
            rng = random.Random(seed_val)

            attractions = [
                {"name": "Old Town Square", "categories": ["Historic Site", "Plaza"]},
                {"name": "Central Park & Gardens", "categories": ["Park", "Outdoors"]},
                {"name": "National History Museum", "categories": ["Museum", "Art"]},
                {"name": "Panorama Hill Observatory", "categories": ["Scenic Lookout", "Outdoors"]},
                {"name": "La Trattoria Local Kitchen", "categories": ["Restaurant", "Local Dining"]},
                {"name": "The Secret Garden Cafe", "categories": ["Cafe", "Coffee Shop"]},
                {"name": "Sunset Point Beach", "categories": ["Beach", "Scenic Lookout"]},
                {"name": "Grand Cathedral", "categories": ["Cathedral", "Historic Site"]},
                {"name": "Downtown Arts District", "categories": ["Arts & Entertainment", "Gallery"]},
                {"name": "The Rusty Anchor Tavern", "categories": ["Bar", "Nightlife"]}
            ]

            selected = rng.sample(attractions, min(limit, len(attractions)))
            for item in selected:
                name = item["name"]
                if rng.choice([True, False]):
                    name = name.replace("Central", resolved_city_name).replace("National", resolved_city_name).replace("Grand", resolved_city_name).replace("Old Town", f"{resolved_city_name} Old Town")
                
                offset_lat = lat + rng.uniform(-0.015, 0.015)
                offset_lon = lon + rng.uniform(-0.015, 0.015)
                places.append({
                    "name": name,
                    "categories": item["categories"],
                    "address": f"{rng.randint(1, 450)} Promenade Ave, {resolved_city_name}",
                    "distance_meters": rng.randint(200, 3500),
                    "latitude": offset_lat,
                    "longitude": offset_lon,
                    "maps_link": f"https://www.google.com/maps/search/?api=1&query={offset_lat},{offset_lon}",
                    "image_url": f"https://source.unsplash.com/featured/600x400/?{name.replace(' ', '+')}+{resolved_city_name.replace(' ', '+')}",
                })

        res_payload = {"places": places}
        if warning_message:
            res_payload["warning"] = warning_message
            
        return res_payload
