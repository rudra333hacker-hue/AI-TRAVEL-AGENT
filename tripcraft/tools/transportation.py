import asyncio
import math
import logging
import random
import re
from tripcraft.tools.geocode import geocode
from tripcraft.tools.web_search import search_web

logger = logging.getLogger("tripcraft")

# ── Region detection ──────────────────────────────────────────────────────────

SOUTH_ASIA_COUNTRIES = {
    "india", "pakistan", "bangladesh", "nepal", "sri lanka", "bhutan", "myanmar",
}
SOUTHEAST_ASIA_COUNTRIES = {
    "thailand", "indonesia", "malaysia", "singapore", "vietnam", "philippines",
    "cambodia", "laos",
}
EUROPE_COUNTRIES = {
    "france", "germany", "united kingdom", "italy", "spain", "netherlands",
    "switzerland", "austria", "czech republic", "hungary", "portugal", "greece",
    "sweden", "norway", "denmark", "finland", "ireland", "iceland", "belgium",
    "poland", "romania", "croatia", "turkey", "russia",
}
NORTH_AMERICA_COUNTRIES = {
    "united states", "canada", "mexico",
}
MIDDLE_EAST_COUNTRIES = {
    "uae", "united arab emirates", "qatar", "saudi arabia", "oman", "bahrain",
    "kuwait", "israel", "lebanon", "jordan",
}

def _detect_region(country: str) -> str:
    """Detect pricing region from country name."""
    c = (country or "").lower().strip()
    if c in SOUTH_ASIA_COUNTRIES:
        return "south_asia"
    if c in SOUTHEAST_ASIA_COUNTRIES:
        return "southeast_asia"
    if c in EUROPE_COUNTRIES:
        return "europe"
    if c in NORTH_AMERICA_COUNTRIES:
        return "north_america"
    if c in MIDDLE_EAST_COUNTRIES:
        return "middle_east"
    # Fallback: check substrings
    if any(x in c for x in ["india", "pakistan", "nepal", "bangladesh", "sri lanka"]):
        return "south_asia"
    if any(x in c for x in ["united states", "america", "canada"]):
        return "north_america"
    return "international"


def _is_same_country(country1: str, country2: str) -> bool:
    """Check if two country strings refer to the same country."""
    c1 = (country1 or "").lower().strip()
    c2 = (country2 or "").lower().strip()
    if not c1 or not c2:
        return False
    return c1 == c2


# ── Realistic price estimators per region ─────────────────────────────────────
# All prices are returned in local currency (INR for India, USD for US/intl, EUR for Europe)
# and then converted to both INR and USD for consistency.

# Exchange rates (approximate)
USD_TO_INR = 83.0
EUR_TO_INR = 90.0
THB_TO_INR = 2.3

def _estimate_prices(region: str, distance_km: float, adults: int, rng: random.Random) -> dict:
    """Return realistic price estimates for each mode based on region and distance.
    
    Returns dict with keys: flight, train, bus, car — each containing price_inr and price_usd.
    """
    d = distance_km
    a = adults
    jitter = lambda lo, hi: rng.uniform(lo, hi)

    if region == "south_asia":
        # ── India / South Asia pricing (INR-native) ──
        # Flight: ₹2,500 base + ₹3.5-5/km (Mumbai-Goa 580km ≈ ₹4,500-5,000)
        flight_inr = (2500 + d * jitter(3.5, 5.0)) * a
        # Train: ₹150 base + ₹0.6-1.5/km for AC class (580km ≈ ₹500-1,020)
        train_inr = (150 + d * jitter(0.6, 1.5)) * a
        # Bus: ₹100 base + ₹0.8-1.8/km (580km ≈ ₹560-1,140)
        bus_inr = (100 + d * jitter(0.8, 1.8)) * a
        # Car: ₹1,500-2,500/day rental + ₹6-9/km for fuel (580km ≈ ₹5,480-7,720)
        drive_hours = d / 50.0  # Indian road speed ~50km/h average
        rental_days = max(1, math.ceil(drive_hours / 10.0))
        car_inr = rental_days * jitter(1500, 2500) + d * jitter(6, 9)

        return {
            "flight": {"price_inr": round(flight_inr), "price_usd": round(flight_inr / USD_TO_INR, 2)},
            "train":  {"price_inr": round(train_inr),  "price_usd": round(train_inr / USD_TO_INR, 2)},
            "bus":    {"price_inr": round(bus_inr),    "price_usd": round(bus_inr / USD_TO_INR, 2)},
            "car":    {"price_inr": round(car_inr),    "price_usd": round(car_inr / USD_TO_INR, 2)},
        }

    elif region == "southeast_asia":
        # Affordable but higher than India
        flight_inr = (3500 + d * jitter(4, 6)) * a
        train_inr = (300 + d * jitter(1.0, 2.0)) * a
        bus_inr = (200 + d * jitter(1.0, 2.5)) * a
        drive_hours = d / 55.0
        rental_days = max(1, math.ceil(drive_hours / 10.0))
        car_inr = rental_days * jitter(2000, 3500) + d * jitter(7, 11)

        return {
            "flight": {"price_inr": round(flight_inr), "price_usd": round(flight_inr / USD_TO_INR, 2)},
            "train":  {"price_inr": round(train_inr),  "price_usd": round(train_inr / USD_TO_INR, 2)},
            "bus":    {"price_inr": round(bus_inr),    "price_usd": round(bus_inr / USD_TO_INR, 2)},
            "car":    {"price_inr": round(car_inr),    "price_usd": round(car_inr / USD_TO_INR, 2)},
        }

    elif region == "europe":
        # Europe: EUR-based, trains are great but pricey, budget airlines cheap
        flight_usd = (30 + d * jitter(0.05, 0.10)) * a  # Budget airlines very cheap
        train_usd = (15 + d * jitter(0.08, 0.18)) * a   # Rail Europe pricing
        bus_usd = (8 + d * jitter(0.03, 0.07)) * a      # FlixBus etc.
        drive_hours = d / 90.0
        rental_days = max(1, math.ceil(drive_hours / 8.0))
        car_usd = rental_days * jitter(40, 70) + d * jitter(0.08, 0.14)  # Fuel + rental

        return {
            "flight": {"price_usd": round(flight_usd, 2), "price_inr": round(flight_usd * USD_TO_INR)},
            "train":  {"price_usd": round(train_usd, 2),  "price_inr": round(train_usd * USD_TO_INR)},
            "bus":    {"price_usd": round(bus_usd, 2),    "price_inr": round(bus_usd * USD_TO_INR)},
            "car":    {"price_usd": round(car_usd, 2),    "price_inr": round(car_usd * USD_TO_INR)},
        }

    elif region == "north_america":
        flight_usd = (50 + d * jitter(0.04, 0.08)) * a
        train_usd = (20 + d * jitter(0.05, 0.12)) * a   # Amtrak pricing
        bus_usd = (12 + d * jitter(0.02, 0.05)) * a      # Greyhound / FlixBus
        drive_hours = d / 95.0
        rental_days = max(1, math.ceil(drive_hours / 8.0))
        car_usd = rental_days * jitter(45, 70) + d * jitter(0.08, 0.14)

        return {
            "flight": {"price_usd": round(flight_usd, 2), "price_inr": round(flight_usd * USD_TO_INR)},
            "train":  {"price_usd": round(train_usd, 2),  "price_inr": round(train_usd * USD_TO_INR)},
            "bus":    {"price_usd": round(bus_usd, 2),    "price_inr": round(bus_usd * USD_TO_INR)},
            "car":    {"price_usd": round(car_usd, 2),    "price_inr": round(car_usd * USD_TO_INR)},
        }

    else:
        # Generic international fallback
        flight_usd = (80 + d * jitter(0.07, 0.13)) * a
        train_usd = (20 + d * jitter(0.06, 0.15)) * a
        bus_usd = (10 + d * jitter(0.03, 0.08)) * a
        drive_hours = d / 80.0
        rental_days = max(1, math.ceil(drive_hours / 8.0))
        car_usd = rental_days * jitter(45, 75) + d * jitter(0.09, 0.15)

        return {
            "flight": {"price_usd": round(flight_usd, 2), "price_inr": round(flight_usd * USD_TO_INR)},
            "train":  {"price_usd": round(train_usd, 2),  "price_inr": round(train_usd * USD_TO_INR)},
            "bus":    {"price_usd": round(bus_usd, 2),    "price_inr": round(bus_usd * USD_TO_INR)},
            "car":    {"price_usd": round(car_usd, 2),    "price_inr": round(car_usd * USD_TO_INR)},
        }


# ── Smart mode availability ──────────────────────────────────────────────────

def _get_available_modes(distance_km: float, region: str, same_country: bool, origin_country: str, dest_country: str) -> dict:
    """Determine which transport modes are viable for this route.
    
    Returns dict of mode -> {"available": bool, "reason": str}
    """
    d = distance_km
    modes = {}

    # FLIGHT: Available for distances > 200km domestic, > 100km international
    # Not available for very short distances
    if same_country:
        if d >= 200:
            modes["flight"] = {"available": True, "reason": ""}
        else:
            modes["flight"] = {"available": False, "reason": f"Distance too short for flights ({round(d)}km). Consider ground transport."}
    else:
        # International — almost always has flights
        modes["flight"] = {"available": True, "reason": ""}

    # TRAIN: Available for domestic routes within rail-connected countries
    # Not available for international routes (unless neighboring countries in Europe/Asia)
    if same_country:
        if d <= 2500:
            modes["train"] = {"available": True, "reason": ""}
        else:
            modes["train"] = {"available": False, "reason": f"Route too long for practical train travel ({round(d)}km)."}
    else:
        # International trains exist in Europe and some parts of Asia
        o_region = _detect_region(origin_country)
        d_region = _detect_region(dest_country)
        if o_region == "europe" and d_region == "europe" and d <= 1500:
            modes["train"] = {"available": True, "reason": "Cross-border European rail available."}
        elif o_region == "south_asia" and d_region == "south_asia" and d <= 500:
            modes["train"] = {"available": True, "reason": ""}
        else:
            modes["train"] = {"available": False, "reason": "No direct train connectivity between these countries."}

    # BUS: Available for domestic routes up to ~1500km, and some cross-border routes
    if same_country:
        if d <= 1500:
            modes["bus"] = {"available": True, "reason": ""}
        else:
            modes["bus"] = {"available": False, "reason": f"Route too long for practical bus travel ({round(d)}km). Consider flights."}
    else:
        # International bus: only for neighboring countries with land border
        if d <= 800:
            modes["bus"] = {"available": True, "reason": "Cross-border bus service may be available."}
        else:
            modes["bus"] = {"available": False, "reason": "No direct bus connectivity between these countries."}

    # CAR: Available for domestic and some cross-border overland routes
    if same_country:
        if d <= 2000:
            modes["car"] = {"available": True, "reason": ""}
        else:
            modes["car"] = {"available": False, "reason": f"Route too long for driving ({round(d)}km). Consider flying."}
    else:
        if d <= 1200:
            modes["car"] = {"available": True, "reason": "Cross-border driving — check visa and permit requirements."}
        else:
            modes["car"] = {"available": False, "reason": "Not practical to drive between these countries."}

    return modes


# ── Web search for real transport data ────────────────────────────────────────

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

            # Try to extract prices (e.g. ₹500, rs 500, INR 500, $50)
            inr_matches = re.findall(r'(?:₹|rs\.?\s*|inr\s*|rupees\s*)([\d,]+)', combined, re.IGNORECASE)
            prices_inr = [float(p.replace(",", "")) for p in inr_matches if 50 < float(p.replace(",", "")) < 100000]

            usd_matches = re.findall(r'\$\s*([\d,]+)', combined)
            for p in usd_matches:
                val = float(p.replace(",", ""))
                if 5 < val < 2000:
                    prices_inr.append(val * USD_TO_INR)

            # Look for operator names
            operators = []
            for r in web_data.get("results", []):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                words = (title + " " + snippet).split()
                for w in words:
                    if len(w) > 3 and w[0].isupper() and not w.startswith("Http") and not w.startswith("www"):
                        operators.append(w.strip(",.;:()[]\"'"))

            if prices_inr:
                avg_price = sum(prices_inr) / len(prices_inr)
                op = list(dict.fromkeys(operators))[:3]

                speed_map = {"bus": 60, "train": 80}
                speed = speed_map.get(mode, 70)
                dur_hours = distance_km / speed
                h = int(dur_hours)
                m = int((dur_hours - h) * 60)

                results[mode] = {
                    "mode": mode.title(),
                    "provider": ", ".join(op) if op else ("Indian Railways" if mode == "train" else "Intercity Bus"),
                    "duration": f"~{h}h {m}m" if h > 0 else f"~{m}m",
                    "price_usd": round(avg_price / USD_TO_INR, 2),
                    "price_inr": round(avg_price),
                    "booking_link": f"https://www.google.com/search?q={mode}+booking+from+{origin.replace(' ', '+')}+to+{destination.replace(' ', '+')}",
                    "viability": f"Real prices from web search",
                    "note": f"Web search result: approx. INR {round(avg_price)} per person.",
                    "data_source": "web_search"
                }
                if op:
                    results[mode]["provider"] = ", ".join(op[:3])
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


# ── Duration helpers ──────────────────────────────────────────────────────────

def _get_speed_km_per_h(mode: str, region: str) -> float:
    """Realistic average travel speed by mode and region."""
    speeds = {
        "south_asia":      {"flight": 700, "train": 55,  "bus": 45,  "car": 50},
        "southeast_asia":  {"flight": 750, "train": 60,  "bus": 50,  "car": 55},
        "europe":          {"flight": 800, "train": 150, "bus": 70,  "car": 90},
        "north_america":   {"flight": 800, "train": 100, "bus": 75,  "car": 95},
        "middle_east":     {"flight": 800, "train": 80,  "bus": 65,  "car": 100},
        "international":   {"flight": 800, "train": 80,  "bus": 60,  "car": 80},
    }
    return speeds.get(region, speeds["international"]).get(mode, 70)


def _format_duration(distance_km: float, mode: str, region: str) -> str:
    """Human-readable duration string."""
    speed = _get_speed_km_per_h(mode, region)
    hours = distance_km / speed
    if mode == "flight":
        hours += 0.5  # Add boarding/taxi time
    h = int(hours)
    m = int((hours - h) * 60)
    if h > 0:
        return f"~{h}h {m}m"
    return f"~{m}m"


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ── Provider names ────────────────────────────────────────────────────────────

def _get_providers(mode: str, region: str, origin_country: str) -> str:
    """Return realistic provider names based on mode and region."""
    providers = {
        "south_asia": {
            "flight": "IndiGo, Air India, SpiceJet, Vistara",
            "train": "Indian Railways (IRCTC)",
            "bus": "RedBus, KSRTC, MSRTC, VRL Travels",
            "car": "Zoomcar, Savaari, Self-Drive Rentals",
        },
        "europe": {
            "flight": "Ryanair, easyJet, Lufthansa, Air France",
            "train": "Eurostar, Deutsche Bahn, SNCF, Trenitalia",
            "bus": "FlixBus, BlaBlaBus, Eurolines",
            "car": "Europcar, Sixt, Hertz",
        },
        "north_america": {
            "flight": "Delta, United, American, Southwest",
            "train": "Amtrak, VIA Rail",
            "bus": "Greyhound, FlixBus, Megabus",
            "car": "Enterprise, Hertz, Budget, Turo",
        },
        "southeast_asia": {
            "flight": "AirAsia, Lion Air, Cebu Pacific, VietJet",
            "train": "National Railways",
            "bus": "Local Intercity Bus Operators",
            "car": "Local Car Rental Services",
        },
        "middle_east": {
            "flight": "Emirates, Qatar Airways, Etihad, FlyDubai",
            "train": "Metro / Rail Services",
            "bus": "SAPTCO, Intercity Bus Services",
            "car": "Hertz, Budget, Local Rental Agencies",
        },
    }
    region_providers = providers.get(region, {
        "flight": "Commercial Airlines",
        "train": "National Rail Network",
        "bus": "Intercity Bus Services",
        "car": "Car Rental Agencies",
    })
    return region_providers.get(mode, "Multiple Operators")


def _get_booking_link(mode: str, origin: str, destination: str, region: str) -> str:
    """Return an appropriate booking/search link."""
    o = origin.replace(" ", "+")
    d = destination.replace(" ", "+")

    if mode == "flight":
        return f"https://www.google.com/travel/flights?q=Flights+from+{o}+to+{d}"
    elif mode == "train":
        if region == "south_asia":
            return f"https://www.google.com/search?q=IRCTC+train+booking+{o}+to+{d}"
        elif region == "europe":
            return f"https://www.google.com/search?q=train+booking+{o}+to+{d}+Trainline+Omio"
        else:
            return f"https://www.google.com/search?q=train+booking+{o}+to+{d}"
    elif mode == "bus":
        if region == "south_asia":
            return f"https://www.google.com/search?q=RedBus+bus+booking+{o}+to+{d}"
        else:
            return f"https://www.google.com/search?q=bus+booking+{o}+to+{d}"
    else:
        return f"https://www.google.com/search?q=car+rental+{o}+to+{d}"


def _get_viability(mode: str, distance_km: float, region: str) -> str:
    """Return a context-aware viability note."""
    d = distance_km
    if mode == "flight":
        if d > 800:
            return "Fastest option for this distance"
        elif d > 400:
            return "Quick but factor in airport transfer time"
        else:
            return "Short-haul flight — ground transport may be comparable"
    elif mode == "train":
        if region == "europe":
            return "Excellent European rail network — comfortable & scenic"
        elif region == "south_asia" and d <= 800:
            return "Comfortable & affordable — book AC class for best experience"
        elif d <= 500:
            return "Great option — comfortable with city-center stations"
        else:
            return "Long journey — consider overnight sleeper trains"
    elif mode == "bus":
        if d <= 300:
            return "Most affordable option for short distances"
        elif d <= 700:
            return "Budget-friendly — book AC/Volvo for comfort"
        else:
            return "Long bus ride — consider overnight sleeper bus"
    else:  # car
        if d <= 300:
            return "Most flexible — great for sightseeing enroute"
        elif d <= 600:
            return "Scenic road trip option — split fuel costs with group"
        else:
            return "Long drive — plan rest stops and overnight stays"


# ── Main search function ─────────────────────────────────────────────────────

async def search(origin: str, destination: str, departure_date: str,
                 return_date: str = None, adults: int = 1) -> dict:
    """Compare travel options between two cities, including flights, trains, buses, and driving/car rentals with realistic prices and durations.

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

            distance = haversine_distance(
                origin_loc["latitude"], origin_loc["longitude"],
                dest_loc["latitude"], dest_loc["longitude"]
            )
        except Exception as geocode_err:
            logger.warning(f"Geocoding failed in transport search: {geocode_err}. Using default route coords.")
            origin_loc = {"name": origin, "latitude": 19.0760, "longitude": 72.8777, "country": "India"}
            dest_loc = {"name": destination, "latitude": 15.4919, "longitude": 73.8278, "country": "India"}
            distance = 500.0
            geo_warning = f"Could not geocode cities '{origin}' or '{destination}'. Displaying estimates for a ~500km route."

        # Determine region and country context
        origin_country = origin_loc.get("country", "")
        dest_country = dest_loc.get("country", "")
        same_country = _is_same_country(origin_country, dest_country)

        # Use origin region for domestic, "international" for cross-country
        if same_country:
            region = _detect_region(origin_country)
        else:
            # For international, use the more specific region for pricing
            o_region = _detect_region(origin_country)
            d_region = _detect_region(dest_country)
            region = o_region if o_region != "international" else d_region

        # Determine which modes are available for this route
        available_modes = _get_available_modes(distance, region, same_country, origin_country, dest_country)

        # Seed RNG for consistent results per route
        route_seed = sum(ord(c) for c in origin + destination)
        rng = random.Random(route_seed)

        # Get realistic price estimates
        prices = _estimate_prices(region, distance, adults, rng)

        # Try web search for real prices (bus & train)
        real_data = await _fetch_real_transport_data(origin, destination, departure_date, adults, distance)

        options = []
        unavailable = []

        # ── 1. FLIGHT ──
        mode_info = available_modes.get("flight", {})
        if mode_info.get("available", False):
            if real_data.get("flight"):
                options.append(real_data["flight"])
            else:
                p = prices["flight"]
                options.append({
                    "mode": "Flight",
                    "provider": _get_providers("flight", region, origin_country),
                    "duration": _format_duration(distance, "flight", region),
                    "price_usd": p["price_usd"],
                    "price_inr": p["price_inr"],
                    "booking_link": _get_booking_link("flight", origin_loc["name"], dest_loc["name"], region),
                    "viability": _get_viability("flight", distance, region),
                    "note": "Estimated price — check airline websites for live fares.",
                    "data_source": "estimated"
                })
        else:
            unavailable.append({"mode": "Flight", "reason": mode_info.get("reason", "Not available for this route.")})

        # ── 2. TRAIN ──
        mode_info = available_modes.get("train", {})
        if mode_info.get("available", False):
            if real_data.get("train"):
                options.append(real_data["train"])
            else:
                p = prices["train"]
                options.append({
                    "mode": "Train",
                    "provider": _get_providers("train", region, origin_country),
                    "duration": _format_duration(distance, "train", region),
                    "price_usd": p["price_usd"],
                    "price_inr": p["price_inr"],
                    "booking_link": _get_booking_link("train", origin_loc["name"], dest_loc["name"], region),
                    "viability": _get_viability("train", distance, region),
                    "note": "Estimated price for AC/comfortable class.",
                    "data_source": "estimated"
                })
        else:
            unavailable.append({"mode": "Train", "reason": mode_info.get("reason", "Not available for this route.")})

        # ── 3. BUS ──
        mode_info = available_modes.get("bus", {})
        if mode_info.get("available", False):
            if real_data.get("bus"):
                options.append(real_data["bus"])
            else:
                p = prices["bus"]
                options.append({
                    "mode": "Bus",
                    "provider": _get_providers("bus", region, origin_country),
                    "duration": _format_duration(distance, "bus", region),
                    "price_usd": p["price_usd"],
                    "price_inr": p["price_inr"],
                    "booking_link": _get_booking_link("bus", origin_loc["name"], dest_loc["name"], region),
                    "viability": _get_viability("bus", distance, region),
                    "note": "Estimated price — book AC/Volvo for comfort.",
                    "data_source": "estimated"
                })
        else:
            unavailable.append({"mode": "Bus", "reason": mode_info.get("reason", "Not available for this route.")})

        # ── 4. CAR RENTAL / DRIVING ──
        mode_info = available_modes.get("car", {})
        if mode_info.get("available", False):
            if real_data.get("car"):
                options.append(real_data["car"])
            else:
                p = prices["car"]
                options.append({
                    "mode": "Car Rental / Self-Drive",
                    "provider": _get_providers("car", region, origin_country),
                    "duration": _format_duration(distance, "car", region),
                    "price_usd": p["price_usd"],
                    "price_inr": p["price_inr"],
                    "booking_link": _get_booking_link("car", origin_loc["name"], dest_loc["name"], region),
                    "viability": _get_viability("car", distance, region),
                    "note": "Total vehicle cost (rental + fuel estimate). Split-friendly for groups!",
                    "data_source": "estimated"
                })
        else:
            unavailable.append({"mode": "Car / Driving", "reason": mode_info.get("reason", "Not available for this route.")})

        result = {
            "origin": origin_loc["name"],
            "destination": dest_loc["name"],
            "distance_km": round(distance, 1),
            "region": region,
            "options": options,
        }

        if unavailable:
            result["unavailable_modes"] = unavailable

        if geo_warning:
            result["warning"] = geo_warning

        if real_data.get("_source") == "web":
            result["data_source"] = "web_search + estimated"
        else:
            result["data_source"] = "estimated"

        return result

    except Exception as e:
        logger.error(f"Transportation comparison error: {e}")
        return {"error": f"Transportation search failed: {str(e)}"}
