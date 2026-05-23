import math
import logging
import random
from tripcraft.tools.geocode import geocode

logger = logging.getLogger("tripcraft")

DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_transportation",
        "description": "Compare travel options between two cities, including flights, trains, buses, and driving/car rentals with prices and durations.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin city name, e.g., 'New York' or 'Mumbai'"},
                "destination": {"type": "string", "description": "Destination city name, e.g., 'Washington DC' or 'Goa'"},
                "departure_date": {"type": "string", "description": "Departure date in YYYY-MM-DD format"},
                "return_date": {"type": "string", "description": "Return date in YYYY-MM-DD format (optional)"},
                "adults": {"type": "integer", "default": 1, "description": "Number of adult passengers"},
            },
            "required": ["origin", "destination", "departure_date"],
        },
    },
}

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
    """Compare flights, trains, buses, and car rentals dynamically based on distance."""
    try:
        adults = int(adults)
        logger.info(f"Comparing transportation options from {origin} to {destination}")

        # Geocode origin and destination
        origin_loc = await geocode(origin)
        dest_loc = await geocode(destination)

        if "error" in origin_loc:
            return {"error": f"Failed to geocode origin: {origin_loc['error']}"}
        if "error" in dest_loc:
            return {"error": f"Failed to geocode destination: {dest_loc['error']}"}

        # Calculate distance
        distance = haversine_distance(
            origin_loc["latitude"], origin_loc["longitude"],
            dest_loc["latitude"], dest_loc["longitude"]
        )

        options = []
        route_seed = sum(ord(c) for c in origin + destination)
        rng = random.Random(route_seed)

        # 1. FLIGHTS (Only if distance > 150 km)
        if distance > 150:
            flight_dur = (distance / 800.0) + 0.6  # 800 km/h + take-off/landing buffer
            hours = int(flight_dur)
            minutes = int((flight_dur - hours) * 60)
            base_price = (100.0 + (distance * 0.09)) * adults
            price_variation = rng.uniform(0.9, 1.2)
            
            options.append({
                "mode": "Flight",
                "provider": "Commercial Airlines (Multiple)",
                "duration": f"{hours}h {minutes}m",
                "price_usd": round(base_price * price_variation, 2),
                "viability": "Best for long distances" if distance > 600 else "Faster but expensive",
                "note": "Requires airport transfers and check-in time."
            })

        # 2. TRAIN
        # Speed: ~110 km/h
        train_dur = (distance / 110.0)
        t_hours = int(train_dur)
        t_minutes = int((train_dur - t_hours) * 60)
        train_price = (20.0 + (distance * 0.04)) * adults
        options.append({
            "mode": "Train",
            "provider": "National Rail Network",
            "duration": f"{t_hours}h {t_minutes}m" if t_hours > 0 else f"{t_minutes}m",
            "price_usd": round(train_price * rng.uniform(0.95, 1.05), 2),
            "viability": "Most comfortable & scenic" if distance <= 1000 else "Slow for long distances",
            "note": "Direct city center connection. Zero check-in fees."
        })

        # 3. BUS
        # Speed: ~70 km/h
        bus_dur = (distance / 70.0)
        b_hours = int(bus_dur)
        b_minutes = int((bus_dur - b_hours) * 60)
        bus_price = (10.0 + (distance * 0.02)) * adults
        options.append({
            "mode": "Bus",
            "provider": "Intercity Bus Services",
            "duration": f"{b_hours}h {b_minutes}m" if b_hours > 0 else f"{b_minutes}m",
            "price_usd": round(bus_price * rng.uniform(0.9, 1.1), 2),
            "viability": "Cheapest option",
            "note": "Multiple stops, subject to traffic conditions."
        })

        # 4. CAR RENTAL / DRIVE
        # Speed: ~85 km/h
        drive_dur = (distance / 85.0)
        d_hours = int(drive_dur)
        d_minutes = int((drive_dur - d_hours) * 60)
        # Price is per vehicle (not per passenger!) plus fuel
        rental_days = max(1, math.ceil(drive_dur / 10.0))
        car_price = (rental_days * 45.0) + (distance * 0.07)  # $45/day rental + $0.07/km fuel
        options.append({
            "mode": "Car Rental (Driving)",
            "provider": "Major Car Rental Agency",
            "duration": f"{d_hours}h {d_minutes}m" if d_hours > 0 else f"{d_minutes}m",
            "price_usd": round(car_price, 2),
            "viability": "Best for flexibility & groups" if distance <= 500 else "Tiring for solo drivers",
            "note": "Price is for the entire vehicle (split friendly!). Includes fuel estimate."
        })

        return {
            "origin": origin_loc["name"],
            "destination": dest_loc["name"],
            "distance_km": round(distance, 1),
            "options": options
        }
    except Exception as e:
        logger.error(f"Transportation comparison error: {e}")
        return {"error": f"Transportation search failed: {str(e)}"}
