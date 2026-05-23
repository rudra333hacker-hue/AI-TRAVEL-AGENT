import asyncio
import math
import logging
import random
import re
from tripcraft.tools.geocode import geocode
from tripcraft.tools.web_search import search_web

logger = logging.getLogger("tripcraft")

# Tool definition is now dynamically generated from type hints and docstring.

async def _fetch_real_transport_data(origin: str, destination: str, departure_date: str, adults: int, distance_km: float) -> dict:
    """Try to fetch real operator names and prices via web search.
    Returns a dict with optional 'flight', 'train', 'bus', 'car' keys + '_source'.
    Falls back gracefully to empty dict if search fails."""
    try:
        results = {"_source": "web"}
        prices_found = 0

        async def fetch_and_parse(query: str, mode: str):
            nonlocal prices_found
            logger.info(f"Web searching transport concurrent: {query}")
            try:
                web_data = await search_web(query, max_results=5)
            except Exception:
                return

            snippets = [r.get("snippet", "") for r in web_data.get("results", [])]
            combined = " ".join(snippets).lower()

            # Try to extract prices (e.g. ₹500, rs 500, INR 500)
            price_matches = re.findall(r'(?:₹|rs\s*|inr\s*|rupees\s*)(\d[\.\d]*)', combined, re.IGNORECASE)
            prices = [float(p) for p in price_matches if 50 < float(p) < 100000]

            # Look for operator names
            operators = []
            for r in web_data.get("results", []):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                # Extract proper nouns that look like transport operators
                words = (title + " " + snippet).split()
                for w in words:
                    if len(w) > 3 and w[0].isupper() and not w.startswith("Http") and not w.startswith("www"):
                        operators.append(w.strip(",.;:()[]\"'"))

            if prices:
                avg_price = sum(prices) / len(prices)
                op = list(dict.fromkeys(operators))[:3]
                if mode == "bus":
                    results["bus"] = {
                        "mode": "Bus",
                        "provider": ", ".join(op) if op else "Intercity Bus Services",
                        "duration": f"~{max(1, int(distance_km / 70))}h {int((distance_km / 70) % 1 * 60)}m",
                        "price_usd": round(avg_price / 83, 2),
                        "price_inr": round(avg_price),
                        "booking_link": f"https://www.google.com/search?q=bus+booking+from+{origin.replace(' ', '+')}+to+{destination.replace(' ', '+')}",
                        "viability": "Cheapest option — real prices from web",
                        "note": f"Live web result: ~₹{round(avg_price)} per person. Multiple operators available.",
                        "data_source": "web_search"
                    }
                    if op:
                        results["bus"]["provider"] = ", ".join(op[:3])
                    prices_found += 1
                elif mode == "train":
                    results["train"] = {
                        "mode": "Train",
                        "provider": ", ".join(op) if op else "Indian Railways / National Rail",
                        "duration": f"~{max(1, int(distance_km / 110))}h {int((distance_km / 110) % 1 * 60)}m",
                        "price_usd": round(avg_price / 83, 2),
                        "price_inr": round(avg_price),
                        "booking_link": f"https://www.google.com/search?q=train+booking+from+{origin.replace(' ', '+')}+to+{destination.replace(' ', '+')}",
                        "viability": "Most comfortable & scenic — real prices from web",
                        "note": f"Live web result: ~₹{round(avg_price)} per person.",
                        "data_source": "web_search"
                    }
                    if op:
                        results["train"]["provider"] = ", ".join(op[:3])
                    prices_found += 1

        # Launch searches concurrently
        queries = [
            (f"{origin} to {destination} bus fare price {departure_date[:4]}", "bus"),
            (f"{origin} to {destination} train fare schedule", "train")
        ]
        await asyncio.gather(*(fetch_and_parse(q, m) for q, m in queries))

        if prices_found > 0:
            logger.info(f"Found real transport data for {prices_found} modes")
            return results

        logger.info("No real transport prices found via web, using estimates")
        return {"_source": "estimated"}

    except Exception as e:
        logger.warning(f"Web search for transport data failed (using estimates): {e}")
        return {"_source": "estimated"}


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def search(origin: str, destination: str, departure_date: str,
                 return_date: str = None, adults: int = 1) -> dict:
    """Compare travel options between two cities, including flights, trains, buses, and driving/car rentals with prices and durations.

    Args:
        origin (str): Origin city name, e.g., 'New York' or 'Mumbai'.
        destination (str): Destination city name, e.g., 'Washington DC' or 'Goa'.
        departure_date (str): Departure date in YYYY-MM-DD format.
        return_date (str): Return date in YYYY-MM-DD format (optional).
        adults (int): Number of adult passengers. Default is 1.

    Returns:
        dict: A dictionary comparing different travel options with providers, prices, durations, and booking links.
    """
    try:
        adults = int(adults)
    except (ValueError, TypeError):
        adults = 1

    logger.info(f"Comparing transportation options from {origin} to {destination}")

    try:
        geo_warning = None
        try:
            # Geocode origin and destination concurrently
            origin_loc, dest_loc = await asyncio.gather(
                geocode(origin),
                geocode(destination)
            )

            if "error" in origin_loc or "error" in dest_loc:
                raise ValueError("Geocoding returned error")

            # Calculate distance
            distance = haversine_distance(
                origin_loc["latitude"], origin_loc["longitude"],
                dest_loc["latitude"], dest_loc["longitude"]
            )
        except Exception as geocode_err:
            logger.warning(f"Geocoding failed in transport search: {geocode_err}. Using default route coords.")
            origin_loc = {"name": origin, "latitude": 19.0760, "longitude": 72.8777}
            dest_loc = {"name": destination, "latitude": 15.4919, "longitude": 73.8278}
            distance = 500.0
            geo_warning = f"Could not geocode cities '{origin}' or '{destination}' to retrieve exact coordinates. Displaying estimates for a standard 500km route."

        options = []
        route_seed = sum(ord(c) for c in origin + destination)
        rng = random.Random(route_seed)

        # --- TRY WEB SEARCH FOR REAL OPERATOR & PRICE DATA ---
        real_data = await _fetch_real_transport_data(origin, destination, departure_date, adults, distance)

        # 1. FLIGHTS (Only if distance > 150 km)
        if distance > 150:
            flight_dur = (distance / 800.0) + 0.6
            hours = int(flight_dur)
            minutes = int((flight_dur - hours) * 60)
            base_price = (100.0 + (distance * 0.09)) * adults

            if real_data.get("flight"):
                options.append(real_data["flight"])
            else:
                p_usd = round(base_price * rng.uniform(0.9, 1.2), 2)
                options.append({
                    "mode": "Flight",
                    "provider": "Commercial Airlines (Multiple)",
                    "duration": f"{hours}h {minutes}m",
                    "price_usd": p_usd,
                    "price_inr": round(p_usd * 83.0),
                    "booking_link": f"https://www.google.com/travel/flights?q=Flights+from+{origin_loc['name'].replace(' ', '+')}+to+{dest_loc['name'].replace(' ', '+')}+on+{departure_date}",
                    "viability": "Best for long distances" if distance > 600 else "Faster but expensive",
                    "note": "Requires airport transfers and check-in time."
                })

        # 2. TRAIN
        train_dur = (distance / 110.0)
        t_hours = int(train_dur)
        t_minutes = int((train_dur - t_hours) * 60)
        train_price = (20.0 + (distance * 0.04)) * adults

        if real_data.get("train"):
            options.append(real_data["train"])
        else:
            p_usd = round(train_price * rng.uniform(0.95, 1.05), 2)
            options.append({
                "mode": "Train",
                "provider": "National Rail Network",
                "duration": f"{t_hours}h {t_minutes}m" if t_hours > 0 else f"{t_minutes}m",
                "price_usd": p_usd,
                "price_inr": round(p_usd * 83.0),
                "booking_link": f"https://www.google.com/search?q=train+booking+from+{origin_loc['name'].replace(' ', '+')}+to+{dest_loc['name'].replace(' ', '+')}",
                "viability": "Most comfortable & scenic" if distance <= 1000 else "Slow for long distances",
                "note": "Direct city center connection. Zero check-in fees."
            })

        # 3. BUS
        bus_dur = (distance / 70.0)
        b_hours = int(bus_dur)
        b_minutes = int((bus_dur - b_hours) * 60)
        bus_price = (10.0 + (distance * 0.02)) * adults

        if real_data.get("bus"):
            options.append(real_data["bus"])
        else:
            p_usd = round(bus_price * rng.uniform(0.9, 1.1), 2)
            options.append({
                "mode": "Bus",
                "provider": "Intercity Bus Services",
                "duration": f"{b_hours}h {b_minutes}m" if b_hours > 0 else f"{b_minutes}m",
                "price_usd": p_usd,
                "price_inr": round(p_usd * 83.0),
                "booking_link": f"https://www.google.com/search?q=bus+booking+from+{origin_loc['name'].replace(' ', '+')}+to+{dest_loc['name'].replace(' ', '+')}",
                "viability": "Cheapest option",
                "note": "Multiple stops, subject to traffic conditions."
            })

        # 4. CAR RENTAL / DRIVE
        drive_dur = (distance / 85.0)
        d_hours = int(drive_dur)
        d_minutes = int((drive_dur - d_hours) * 60)
        rental_days = max(1, math.ceil(drive_dur / 10.0))
        car_price = (rental_days * 45.0) + (distance * 0.07)

        if real_data.get("car"):
            options.append(real_data["car"])
        else:
            p_usd = round(car_price, 2)
            options.append({
                "mode": "Car Rental (Driving)",
                "provider": "Major Car Rental Agency",
                "duration": f"{d_hours}h {d_minutes}m" if d_hours > 0 else f"{d_minutes}m",
                "price_usd": p_usd,
                "price_inr": round(p_usd * 83.0),
                "booking_link": f"https://www.google.com/search?q=car+rental+from+{origin_loc['name'].replace(' ', '+')}+to+{dest_loc['name'].replace(' ', '+')}",
                "viability": "Best for flexibility & groups" if distance <= 500 else "Tiring for solo drivers",
                "note": "Price is for the entire vehicle (split friendly!). Includes fuel estimate."
            })

        result = {
            "origin": origin_loc["name"],
            "destination": dest_loc["name"],
            "distance_km": round(distance, 1),
            "options": options
        }

        if geo_warning:
            result["warning"] = geo_warning

        # Attach search source info
        if real_data.get("_source") == "web":
            result["data_source"] = "web_search"
        else:
            result["data_source"] = "estimated"

        return result
    except Exception as e:
        logger.error(f"Transportation comparison error: {e}")
        return {"error": f"Transportation search failed: {str(e)}"}
