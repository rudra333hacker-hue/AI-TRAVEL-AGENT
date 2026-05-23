import asyncio
import math
import logging
import random
import re
from amadeus import Client
from tripcraft.tools.geocode import geocode
from tripcraft.tools.web_search import search_web

logger = logging.getLogger("tripcraft")

DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_flights",
        "description": "Search for realistic flight options, prices, and durations between two cities using live data (Amadeus) or distance-based simulation.",
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

class FlightSearch:
    def __init__(self, config):
        self._config = config
        self._amadeus = None
        if config.has_amadeus:
            try:
                self._amadeus = Client(
                    client_id=config.amadeus_client_id,
                    client_secret=config.amadeus_client_secret,
                )
                logger.info("Amadeus client initialized for flight search")
            except Exception as e:
                logger.warning(f"Failed to initialize Amadeus client: {e}. Will use simulated data.")

    async def search(self, origin: str, destination: str, departure_date: str,
                     return_date: str = None, adults: int = 1, max_results: int = 3) -> dict:
        """Search for flights using Amadeus API, falling back to simulated data."""
        try:
            adults = int(adults)
            max_results = int(max_results)

            # Try Amadeus first if configured
            if self._amadeus:
                try:
                    result = await self._search_amadeus(origin, destination, departure_date, return_date, adults, max_results)
                    if result and result.get("flights"):
                        return result
                except Exception as e:
                    logger.warning(f"Amadeus flight search failed: {e}. Falling back to simulated data.")

            # Fallback to simulated data
            return await self._search_simulated(origin, destination, departure_date, return_date, adults, max_results)

        except Exception as e:
            logger.error(f"Flight search error: {e}")
            return {"error": f"Flight search failed: {str(e)}", "flights": []}

    async def _resolve_airport_code(self, city_name: str) -> str | None:
        """Use Amadeus location search to resolve a city name to an IATA airport code.

        Runs in a thread to avoid blocking the event loop (Amadeus SDK is synchronous).
        """
        try:
            response = await asyncio.to_thread(
                self._amadeus.reference_data.locations.get,
                keyword=city_name,
                subType="AIRPORT",
            )
            data = response.data if hasattr(response, 'data') else (response.result.get('data', []) if isinstance(response.result, dict) else [])
            if data:
                for loc in data:
                    if loc.get('subType') == 'AIRPORT' and loc.get('iataCode'):
                        return loc['iataCode']
                if data[0].get('iataCode'):
                    return data[0]['iataCode']
            return None
        except Exception as e:
            logger.warning(f"Amadeus airport code resolution failed for '{city_name}': {e}")
            return None

    async def _search_amadeus(self, origin: str, destination: str, departure_date: str,
                               return_date: str = None, adults: int = 1, max_results: int = 3) -> dict:
        """Search flights using the Amadeus Flight Offers Search API.

        Runs in a thread to avoid blocking the event loop (Amadeus SDK is synchronous).
        """
        # Resolve city names to IATA airport codes
        origin_code = await self._resolve_airport_code(origin)
        dest_code = await self._resolve_airport_code(destination)

        if not origin_code:
            return {"error": f"Could not resolve origin '{origin}' to an airport code", "flights": []}
        if not dest_code:
            return {"error": f"Could not resolve destination '{destination}' to an airport code", "flights": []}

        logger.info(f"Amadeus flight search: {origin_code} -> {dest_code} on {departure_date}")

        # Build request parameters
        params = {
            "originLocationCode": origin_code,
            "destinationLocationCode": dest_code,
            "departureDate": departure_date,
            "adults": adults,
            "max": min(max_results, 10),
        }
        if return_date:
            params["returnDate"] = return_date

        # Execute the API call in a thread (Amadeus SDK is synchronous)
        response = await asyncio.to_thread(
            self._amadeus.shopping.flight_offers_search.get,
            **params,
        )
        offers = response.data if hasattr(response, 'data') else (response.result.get('data', []) if isinstance(response.result, dict) else [])

        if not offers:
            logger.info(f"No Amadeus flight offers found for {origin_code} -> {dest_code}")
            return {"flights": []}

        flights = []
        for offer in offers[:max_results]:
            try:
                itineraries = offer.get("itineraries", [])
                first_itinerary = itineraries[0] if itineraries else {}
                segments = first_itinerary.get("segments", [])

                price_info = offer.get("price", {})
                grand_total = price_info.get("grandTotal", "N/A")
                currency = price_info.get("currency", "USD")

                first_segment = segments[0] if segments else {}
                last_segment = segments[-1] if segments else {}

                dep_time = first_segment.get("departure", {}).get("at", departure_date + "T00:00:00")
                arr_time = last_segment.get("arrival", {}).get("at", "")

                stops = len(segments) - 1 if segments else 0

                duration_iso = first_itinerary.get("duration", "")
                duration_str = _format_duration(duration_iso)

                airline_code = first_segment.get("carrierCode", "")
                airline_name = _get_airline_name(airline_code)
                flight_number = first_segment.get("number", "")

                flights.append({
                    "airline": airline_name or f"Airline {airline_code}",
                    "airline_code": airline_code,
                    "flight_number": flight_number,
                    "origin_city": origin,
                    "destination_city": destination,
                    "origin_airport": origin_code,
                    "destination_airport": dest_code,
                    "departure_time": dep_time,
                    "arrival_time": arr_time,
                    "stops": stops,
                    "duration": duration_str,
                    "price": float(grand_total) if grand_total != "N/A" else 0,
                    "price_usd": float(grand_total) if grand_total != "N/A" else 0,
                    "price_inr": round(float(grand_total) * 83.0, 2) if grand_total != "N/A" else 0,
                    "currency": currency,
                    "booking_link": f"https://www.google.com/travel/flights?q=Flights%20to%20{dest_code}%20from%20{origin_code}%20on%20{departure_date}",
                    "note": "Live pricing via Amadeus API",
                })
            except Exception as e:
                logger.warning(f"Skipping Amadeus offer due to parse error: {e}")
                continue

        return {"flights": flights}

    async def _search_simulated(self, origin: str, destination: str, departure_date: str,
                                return_date: str = None, adults: int = 1, max_results: int = 3) -> dict:
        """Fallback: simulate realistic flight search using geocoded distance, real-world airline routes, and web-searched fare data."""
        logger.info(f"Geocoding flight origin: {origin} and destination: {destination}")
        origin_loc = await geocode(origin)
        dest_loc = await geocode(destination)

        if "error" in origin_loc:
            return {"error": f"Failed to geocode origin: {origin_loc['error']}", "flights": []}
        if "error" in dest_loc:
            return {"error": f"Failed to geocode destination: {dest_loc['error']}", "flights": []}

        distance = haversine_distance(
            origin_loc["latitude"], origin_loc["longitude"],
            dest_loc["latitude"], dest_loc["longitude"]
        )

        duration_hours = (distance / 800.0) + 0.6
        
        # --- WEB SEARCH FOR REAL FLIGHT PRICING (Google Web Scraper Fallback) ---
        web_prices = []
        found_carriers = []
        try:
            query = f"flights from {origin_loc['name']} to {dest_loc['name']} price {departure_date[:7]}"
            logger.info(f"Web searching flights: {query}")
            web_data = await search_web(query, max_results=5)
            
            snippets = [r.get("snippet", "") for r in web_data.get("results", [])]
            combined = " ".join(snippets).lower()
            
            # Extract prices (e.g. ₹4500, Rs. 5000, 12000 INR)
            price_matches = re.findall(r'(?:₹|rs\s*|inr\s*|rupees\s*|\$)(\d[\.\d]*)', combined, re.IGNORECASE)
            # Filter matches to look like valid flight fares
            web_prices = [float(p) for p in price_matches if 1500 < float(p) < 200000]
            # Convert dollars if found as small numbers
            dollar_prices = [float(p) for p in re.findall(r'\$(\d[\.\d]*)', combined) if 40 < float(p) < 2500]
            for dp in dollar_prices:
                web_prices.append(dp * 83)
                
            # Scan for airline names in snippets
            known_airlines = {
                "indigo": "IndiGo", "air india": "Air India", "spicejet": "SpiceJet",
                "akasa": "Akasa Air", "vistara": "Vistara", "airasia": "AirAsia",
                "delta": "Delta Air Lines", "united": "United Airlines", "american": "American Airlines",
                "emirates": "Emirates", "qatar": "Qatar Airways", "singapore": "Singapore Airlines",
                "lufthansa": "Lufthansa", "british": "British Airways", "air france": "Air France",
                "ryanair": "Ryanair", "easyjet": "easyJet"
            }
            for key, val in known_airlines.items():
                if key in combined:
                    found_carriers.append({"name": val, "code": key[:2].upper()})
        except Exception as e:
            logger.warning(f"Web search for flight data failed: {e}")

        # Compute base price using web price references if found, else default to distance estimate
        if web_prices:
            avg_price_inr = sum(web_prices) / len(web_prices)
            # Make sure it's per passenger in USD
            base_price = (avg_price_inr / 83.0) / adults
            logger.info(f"Using web-discovered base flight price: ₹{avg_price_inr/adults:.0f} per person (~${base_price:.2f})")
            note_str = "Price range sourced from live web search"
        else:
            base_price = 80.0 + (distance * 0.08)
            note_str = "Estimated price based on distance (Amadeus not configured)"

        # Use found carriers if available, else get defaults
        carriers = found_carriers if found_carriers else get_airline_options(origin_loc.get("country", ""), dest_loc.get("country", ""))
        if len(carriers) < 3:
            default_options = get_airline_options(origin_loc.get("country", ""), dest_loc.get("country", ""))
            for d in default_options:
                if d["name"] not in [c["name"] for c in carriers]:
                    carriers.append(d)

        flights = []
        route_seed = sum(ord(c) for c in origin + destination)
        rng = random.Random(route_seed)

        for i in range(min(max_results, len(carriers))):
            carrier = carriers[i]
            price_multiplier = rng.uniform(0.85, 1.25)
            ticket_price = round(base_price * price_multiplier * adults, 2)

            if distance < 1200:
                stops = 0
                flight_dur = duration_hours
            elif distance < 4500:
                stops = rng.choice([0, 1])
                flight_dur = duration_hours + (stops * rng.uniform(1.5, 3.0))
            else:
                stops = rng.choice([1, 2])
                flight_dur = duration_hours + (stops * rng.uniform(2.0, 4.5))

            hours = int(flight_dur)
            minutes = int((flight_dur - hours) * 60)
            duration_str = f"{hours}h {minutes}m"

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
                "price_usd": ticket_price,
                "price_inr": round(ticket_price * 83.0, 2),
                "currency": "USD",
                "booking_link": f"https://www.google.com/travel/flights?q=Flights%20to%20{dest_loc['name'].replace(' ', '%20')}%20from%20{origin_loc['name'].replace(' ', '%20')}%20on%20{departure_date}",
                "note": note_str,
            })

        return {"flights": flights}


# ── Module-level helper functions ──

def _format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (e.g., PT5H30M) to readable '5h 30m'."""
    if not iso_duration:
        return "N/A"
    match = re.match(r'PT?(?:(\d+)H)?(?:(\d+)M)?', iso_duration)
    if match:
        hours = match.group(1) or "0"
        minutes = match.group(2) or "0"
        return f"{int(hours)}h {int(minutes)}m"
    return iso_duration


def _get_airline_name(code: str) -> str:
    """Map IATA airline codes to names (common ones)."""
    airlines = {
        "AA": "American Airlines", "DL": "Delta Air Lines", "UA": "United Airlines",
        "BA": "British Airways", "LH": "Lufthansa", "AF": "Air France",
        "KL": "KLM", "EK": "Emirates", "QR": "Qatar Airways",
        "SQ": "Singapore Airlines", "CX": "Cathay Pacific", "JL": "Japan Airlines",
        "TK": "Turkish Airlines", "EY": "Etihad Airways", "NH": "ANA",
        "QF": "Qantas", "AZ": "ITA Airways", "IB": "Iberia",
        "VS": "Virgin Atlantic", "FR": "Ryanair", "U2": "easyJet",
        "AK": "AirAsia", "TR": "Scoot", "BI": "Royal Brunei",
        "CA": "Air China", "MU": "China Eastern", "CZ": "China Southern",
        "KE": "Korean Air", "OZ": "Asiana Airlines", "VN": "Vietnam Airlines",
        "TG": "Thai Airways", "MH": "Malaysia Airlines", "GA": "Garuda Indonesia",
        "AI": "Air India", "6E": "IndiGo", "SG": "SpiceJet",
        "AC": "Air Canada", "WS": "WestJet", "AM": "Aeromexico",
        "LA": "LATAM", "CM": "Copa Airlines", "AV": "Avianca",
    }
    return airlines.get(code, "")


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371.0
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

    if len(airlines) < 3:
        airlines.extend(global_carriers)
        airlines.extend(us_airlines)

    return airlines[:5]
