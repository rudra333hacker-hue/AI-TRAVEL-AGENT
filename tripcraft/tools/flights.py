import math
import logging
import random
from datetime import datetime
from tripcraft.tools.geocode import geocode

logger = logging.getLogger("tripcraft")

DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_flights",
        "description": "Search for realistic flight options, prices, and durations between two cities.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin city name, e.g., 'New York' or 'Boston'"},
                "destination": {"type": "string", "description": "Destination city name, e.g., 'Paris' or 'Bali'"},
                "departure_date": {"type": "string", "description": "Departure date in YYYY-MM-DD format"},
                "return_date": {"type": "string", "description": "Return date in YYYY-MM-DD format (optional, omit for one-way)"},
                "adults": {"type": "integer", "default": 1, "description": "Number of adult passengers"},
                "max_results": {"type": "integer", "default": 3, "description": "Maximum number of flights to return"},
            },
            "required": ["origin", "destination", "departure_date"],
        },
    },
}

def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_airline_options(origin_country: str, dest_country: str) -> list[dict]:
    """Return appropriate airline names and codes based on countries."""
    us_airlines = [{"name": "Delta Air Lines", "code": "DL"}, {"name": "United Airlines", "code": "UA"}, {"name": "American Airlines", "code": "AA"}]
    eu_airlines = [{"name": "Lufthansa", "code": "LH"}, {"name": "British Airways", "code": "BA"}, {"name": "Air France", "code": "AF"}, {"name": "KLM", "code": "KL"}]
    asia_airlines = [{"name": "Singapore Airlines", "code": "SQ"}, {"name": "Cathay Pacific", "code": "CX"}, {"name": "Japan Airlines", "code": "JL"}, {"name": "AirAsia", "code": "AK"}]
    mideast_airlines = [{"name": "Emirates", "code": "EK"}, {"name": "Qatar Airways", "code": "QR"}]
    global_carriers = [{"name": "Turkish Airlines", "code": "TK"}, {"name": "ANA", "code": "NH"}]

    airlines = []
    
    # Simple matching based on country keywords
    oc = origin_country.lower()
    dc = dest_country.lower()

    if "united states" in oc or "united states" in dc:
        airlines.extend(us_airlines)
    if any(c in oc or c in dc for c in ["france", "germany", "united kingdom", "italy", "spain", "europe"]):
        airlines.extend(eu_airlines)
    if any(c in oc or c in dc for c in ["singapore", "china", "japan", "indonesia", "thailand", "malaysia", "asia"]):
        airlines.extend(asia_airlines)
    if any(c in oc or c in dc for c in ["united arab emirates", "qatar", "dubai"]):
        airlines.extend(mideast_airlines)

    # Fallback to general carriers if we don't have enough specific ones
    if len(airlines) < 3:
        airlines.extend(global_carriers)
        airlines.extend(us_airlines)

    return airlines[:5]

async def search(origin: str, destination: str, departure_date: str,
                 return_date: str = None, adults: int = 1, max_results: int = 3) -> dict:
    """Simulate realistic flight search using geocoded distance and real-world airline routes."""
    try:
        adults = int(adults)
        max_results = int(max_results)
        # Step 1: Geocode origin and destination
        logger.info(f"Geocoding flight origin: {origin} and destination: {destination}")
        origin_loc = await geocode(origin)
        dest_loc = await geocode(destination)

        if "error" in origin_loc:
            return {"error": f"Failed to geocode origin: {origin_loc['error']}", "flights": []}
        if "error" in dest_loc:
            return {"error": f"Failed to geocode destination: {dest_loc['error']}", "flights": []}

        # Calculate distance
        distance = haversine_distance(
            origin_loc["latitude"], origin_loc["longitude"],
            dest_loc["latitude"], dest_loc["longitude"]
        )

        # Step 2: Calculate duration and price base rates
        # Speed: ~800 km/h + 40 mins takeoff/landing buffer
        duration_hours = (distance / 800.0) + 0.6
        
        # Flight pricing model: $80 base + $0.08 per km per passenger
        base_price = 80.0 + (distance * 0.08)
        
        # Select carriers
        carriers = get_airline_options(origin_loc.get("country", ""), dest_loc.get("country", ""))

        flights = []
        # Seed generator with cities to keep options stable per route
        route_seed = sum(ord(c) for c in origin + destination)
        rng = random.Random(route_seed)

        for i in range(min(max_results, len(carriers))):
            carrier = carriers[i]
            
            # Apply some carrier-specific pricing and duration variance
            price_multiplier = rng.uniform(0.85, 1.25)
            ticket_price = round(base_price * price_multiplier * adults, 2)
            
            # Direct flights vs stops depending on distance
            if distance < 1200:
                stops = 0
                flight_dur = duration_hours
            elif distance < 4500:
                stops = rng.choice([0, 1])
                flight_dur = duration_hours + (stops * rng.uniform(1.5, 3.0))
            else:
                stops = rng.choice([1, 2])
                flight_dur = duration_hours + (stops * rng.uniform(2.0, 4.5))

            # Format duration into ISO-like or friendly string e.g. "5h 15m"
            hours = int(flight_dur)
            minutes = int((flight_dur - hours) * 60)
            duration_str = f"{hours}h {minutes}m"

            # Create realistic departure/arrival times
            dep_hour = rng.randint(6, 21)
            dep_min = rng.choice([0, 15, 30, 45])
            dep_time = f"{departure_date}T{dep_hour:02d}:{dep_min:02d}:00"
            
            flights.append({
                "airline": carrier["name"],
                "airline_code": carrier["code"],
                "origin_city": origin_loc["name"],
                "destination_city": dest_loc["name"],
                "departure_time": dep_time,
                "stops": stops,
                "duration": duration_str,
                "price": ticket_price,
                "currency": "USD",
                "note": "Estimated price based on distance (Amadeus deactivated)"
            })

        return {"flights": flights}
    except Exception as e:
        logger.error(f"Flight search error: {e}")
        return {"error": f"Flight search failed: {str(e)}", "flights": []}
