import logging
import re
import asyncio

logger = logging.getLogger("tripcraft")

# Module-level cache for geocode results
_cache = {}

# Hardcoded fallbacks for commonly searched cities (zero-latency, zero-fail lookup)
POPULAR_MAPPINGS = {
    # ── India Metro / Tier-1 ──
    "mumbai":    {"name": "Mumbai",    "country": "India",       "latitude": 19.0760,  "longitude": 72.8777,   "timezone": "Asia/Kolkata"},
    "bombay":    {"name": "Mumbai",    "country": "India",       "latitude": 19.0760,  "longitude": 72.8777,   "timezone": "Asia/Kolkata"},
    "delhi":     {"name": "Delhi",     "country": "India",       "latitude": 28.7041,  "longitude": 77.1025,   "timezone": "Asia/Kolkata"},
    "new delhi": {"name": "New Delhi", "country": "India",       "latitude": 28.6139,  "longitude": 77.2090,   "timezone": "Asia/Kolkata"},
    "bangalore": {"name": "Bangalore", "country": "India",       "latitude": 12.9716,  "longitude": 77.5946,   "timezone": "Asia/Kolkata"},
    "bengaluru": {"name": "Bengaluru", "country": "India",       "latitude": 12.9716,  "longitude": 77.5946,   "timezone": "Asia/Kolkata"},
    "chennai":   {"name": "Chennai",   "country": "India",       "latitude": 13.0827,  "longitude": 80.2707,   "timezone": "Asia/Kolkata"},
    "madras":    {"name": "Chennai",   "country": "India",       "latitude": 13.0827,  "longitude": 80.2707,   "timezone": "Asia/Kolkata"},
    "kolkata":   {"name": "Kolkata",   "country": "India",       "latitude": 22.5726,  "longitude": 88.3639,   "timezone": "Asia/Kolkata"},
    "calcutta":  {"name": "Kolkata",   "country": "India",       "latitude": 22.5726,  "longitude": 88.3639,   "timezone": "Asia/Kolkata"},
    "hyderabad": {"name": "Hyderabad", "country": "India",       "latitude": 17.3850,  "longitude": 78.4867,   "timezone": "Asia/Kolkata"},
    "pune":      {"name": "Pune",      "country": "India",       "latitude": 18.5204,  "longitude": 73.8567,   "timezone": "Asia/Kolkata"},
    "ahmedabad": {"name": "Ahmedabad", "country": "India",       "latitude": 23.0225,  "longitude": 72.5714,   "timezone": "Asia/Kolkata"},
    "surat":     {"name": "Surat",     "country": "India",       "latitude": 21.1702,  "longitude": 72.8311,   "timezone": "Asia/Kolkata"},

    # ── India Destinations (hill stations, beaches, tier-2) ──
    "goa":          {"name": "Goa",          "country": "India",       "latitude": 15.4919,  "longitude": 73.8278,   "timezone": "Asia/Kolkata"},
    "panaji":       {"name": "Panaji",       "country": "India",       "latitude": 15.4909,  "longitude": 73.8278,   "timezone": "Asia/Kolkata"},
    "shimla":       {"name": "Shimla",       "country": "India",       "latitude": 31.1048,  "longitude": 77.1734,   "timezone": "Asia/Kolkata"},
    "manali":       {"name": "Manali",       "country": "India",       "latitude": 32.2396,  "longitude": 77.1887,   "timezone": "Asia/Kolkata"},
    "kerala":       {"name": "Kerala",       "country": "India",       "latitude": 10.8505,  "longitude": 76.2711,   "timezone": "Asia/Kolkata"},
    "kochi":        {"name": "Kochi",        "country": "India",       "latitude": 9.9312,   "longitude": 76.2673,   "timezone": "Asia/Kolkata"},
    "cochin":       {"name": "Kochi",        "country": "India",       "latitude": 9.9312,   "longitude": 76.2673,   "timezone": "Asia/Kolkata"},
    "munnar":       {"name": "Munnar",       "country": "India",       "latitude": 10.0889,  "longitude": 77.0595,   "timezone": "Asia/Kolkata"},
    "alappuzha":    {"name": "Alappuzha",    "country": "India",       "latitude": 9.4981,   "longitude": 76.3388,   "timezone": "Asia/Kolkata"},
    "alleppey":     {"name": "Alappuzha",    "country": "India",       "latitude": 9.4981,   "longitude": 76.3388,   "timezone": "Asia/Kolkata"},
    "jaipur":       {"name": "Jaipur",       "country": "India",       "latitude": 26.9124,  "longitude": 75.7873,   "timezone": "Asia/Kolkata"},
    "udaipur":      {"name": "Udaipur",      "country": "India",       "latitude": 24.5854,  "longitude": 73.7125,   "timezone": "Asia/Kolkata"},
    "jodhpur":      {"name": "Jodhpur",      "country": "India",       "latitude": 26.2389,  "longitude": 73.0243,   "timezone": "Asia/Kolkata"},
    "agra":         {"name": "Agra",         "country": "India",       "latitude": 27.1767,  "longitude": 78.0081,   "timezone": "Asia/Kolkata"},
    "varanasi":     {"name": "Varanasi",     "country": "India",       "latitude": 25.3176,  "longitude": 82.9739,   "timezone": "Asia/Kolkata"},
    "rishikesh":    {"name": "Rishikesh",    "country": "India",       "latitude": 30.0869,  "longitude": 78.2676,   "timezone": "Asia/Kolkata"},
    "haridwar":     {"name": "Haridwar",     "country": "India",       "latitude": 29.9457,  "longitude": 78.1642,   "timezone": "Asia/Kolkata"},
    "nainital":     {"name": "Nainital",     "country": "India",       "latitude": 29.3919,  "longitude": 79.4542,   "timezone": "Asia/Kolkata"},
    "mussoorie":    {"name": "Mussoorie",    "country": "India",       "latitude": 30.4599,  "longitude": 78.0620,   "timezone": "Asia/Kolkata"},
    "darjeeling":   {"name": "Darjeeling",   "country": "India",       "latitude": 27.0410,  "longitude": 88.2663,   "timezone": "Asia/Kolkata"},
    "gangtok":      {"name": "Gangtok",      "country": "India",       "latitude": 27.3314,  "longitude": 88.6138,   "timezone": "Asia/Kolkata"},
    "leh":          {"name": "Leh",          "country": "India",       "latitude": 34.1539,  "longitude": 77.5770,   "timezone": "Asia/Kolkata"},
    "ladakh":       {"name": "Ladakh",       "country": "India",       "latitude": 34.1526,  "longitude": 77.5771,   "timezone": "Asia/Kolkata"},
    "srinagar":     {"name": "Srinagar",     "country": "India",       "latitude": 34.0837,  "longitude": 74.7973,   "timezone": "Asia/Kolkata"},
    "amritsar":     {"name": "Amritsar",     "country": "India",       "latitude": 31.6340,  "longitude": 74.8723,   "timezone": "Asia/Kolkata"},
    "coimbatore":   {"name": "Coimbatore",   "country": "India",       "latitude": 11.0168,  "longitude": 76.9558,   "timezone": "Asia/Kolkata"},
    "mysore":       {"name": "Mysore",       "country": "India",       "latitude": 12.2958,  "longitude": 76.6394,   "timezone": "Asia/Kolkata"},
    "ooty":         {"name": "Ooty",         "country": "India",       "latitude": 11.4102,  "longitude": 76.6950,   "timezone": "Asia/Kolkata"},
    "kodaikanal":   {"name": "Kodaikanal",   "country": "India",       "latitude": 10.2381,  "longitude": 77.4892,   "timezone": "Asia/Kolkata"},
    "coorg":        {"name": "Coorg",        "country": "India",       "latitude": 12.4244,  "longitude": 75.7382,   "timezone": "Asia/Kolkata"},
    "hampi":        {"name": "Hampi",        "country": "India",       "latitude": 15.3350,  "longitude": 76.4600,   "timezone": "Asia/Kolkata"},
    "andaman":      {"name": "Andaman",      "country": "India",       "latitude": 11.7401,  "longitude": 92.6586,   "timezone": "Asia/Kolkata"},
    "port blair":   {"name": "Port Blair",   "country": "India",       "latitude": 11.6234,  "longitude": 92.7265,   "timezone": "Asia/Kolkata"},
    "puri":         {"name": "Puri",         "country": "India",       "latitude": 19.8135,  "longitude": 85.8312,   "timezone": "Asia/Kolkata"},
    "mcLeod ganj":  {"name": "McLeod Ganj",  "country": "India",       "latitude": 32.2168,  "longitude": 76.3227,   "timezone": "Asia/Kolkata"},
    "dharamshala":  {"name": "Dharamshala",  "country": "India",       "latitude": 32.2190,  "longitude": 76.3234,   "timezone": "Asia/Kolkata"},
    "dharamsala":   {"name": "Dharamshala",  "country": "India",       "latitude": 32.2190,  "longitude": 76.3234,   "timezone": "Asia/Kolkata"},
    "kasol":        {"name": "Kasol",        "country": "India",       "latitude": 32.0100,  "longitude": 77.3148,   "timezone": "Asia/Kolkata"},
    "spiti":        {"name": "Spiti",        "country": "India",       "latitude": 32.2461,  "longitude": 78.0526,   "timezone": "Asia/Kolkata"},
    "nagpur":       {"name": "Nagpur",       "country": "India",       "latitude": 21.1458,  "longitude": 79.0882,   "timezone": "Asia/Kolkata"},
    "indore":       {"name": "Indore",       "country": "India",       "latitude": 22.7196,  "longitude": 75.8577,   "timezone": "Asia/Kolkata"},
    "bhopal":       {"name": "Bhopal",       "country": "India",       "latitude": 23.2599,  "longitude": 77.4126,   "timezone": "Asia/Kolkata"},
    "lucknow":      {"name": "Lucknow",      "country": "India",       "latitude": 26.8467,  "longitude": 80.9462,   "timezone": "Asia/Kolkata"},
    "patna":        {"name": "Patna",        "country": "India",       "latitude": 25.5941,  "longitude": 85.1376,   "timezone": "Asia/Kolkata"},
    "ranchi":       {"name": "Ranchi",       "country": "India",       "latitude": 23.3441,  "longitude": 85.3096,   "timezone": "Asia/Kolkata"},
    "guwahati":     {"name": "Guwahati",     "country": "India",       "latitude": 26.1445,  "longitude": 91.7362,   "timezone": "Asia/Kolkata"},
    "chandigarh":   {"name": "Chandigarh",   "country": "India",       "latitude": 30.7333,  "longitude": 76.7794,   "timezone": "Asia/Kolkata"},
    "kolhapur":     {"name": "Kolhapur",     "country": "India",       "latitude": 16.6917,  "longitude": 74.2330,   "timezone": "Asia/Kolkata"},
    "aurngabad":    {"name": "Aurangabad",   "country": "India",       "latitude": 19.8762,  "longitude": 75.3433,   "timezone": "Asia/Kolkata"},
    "nashik":       {"name": "Nashik",       "country": "India",       "latitude": 19.9975,  "longitude": 73.7898,   "timezone": "Asia/Kolkata"},
    "rajkot":       {"name": "Rajkot",       "country": "India",       "latitude": 22.3039,  "longitude": 70.8022,   "timezone": "Asia/Kolkata"},
    "vadodara":     {"name": "Vadodara",     "country": "India",       "latitude": 22.3072,  "longitude": 73.1812,   "timezone": "Asia/Kolkata"},
    "thiruvananthapuram": {"name": "Thiruvananthapuram", "country": "India", "latitude": 8.5241, "longitude": 76.9366, "timezone": "Asia/Kolkata"},
    "trivandrum":   {"name": "Thiruvananthapuram", "country": "India", "latitude": 8.5241, "longitude": 76.9366, "timezone": "Asia/Kolkata"},
    "vizag":        {"name": "Visakhapatnam",          "country": "India",       "latitude": 17.6868,  "longitude": 83.2185,  "timezone": "Asia/Kolkata"},
    "visakhapatnam":{"name": "Visakhapatnam",          "country": "India",       "latitude": 17.6868,  "longitude": 83.2185,  "timezone": "Asia/Kolkata"},

    # ── International ──
    "paris":        {"name": "Paris",        "country": "France",        "latitude": 48.8566,  "longitude": 2.3522,     "timezone": "Europe/Paris"},
    "london":       {"name": "London",       "country": "United Kingdom","latitude": 51.5074,  "longitude": -0.1278,    "timezone": "Europe/London"},
    "tokyo":        {"name": "Tokyo",        "country": "Japan",         "latitude": 35.6762,  "longitude": 139.6503,   "timezone": "Asia/Tokyo"},
    "dubai":        {"name": "Dubai",        "country": "UAE",           "latitude": 25.2048,  "longitude": 55.2708,    "timezone": "Asia/Dubai"},
    "bangkok":      {"name": "Bangkok",      "country": "Thailand",      "latitude": 13.7563,  "longitude": 100.5018,   "timezone": "Asia/Bangkok"},
    "new york":     {"name": "New York",     "country": "United States", "latitude": 40.7128,  "longitude": -74.0060,   "timezone": "America/New_York"},
    "los angeles":  {"name": "Los Angeles",  "country": "United States", "latitude": 34.0522,  "longitude": -118.2437,  "timezone": "America/Los_Angeles"},
    "sydney":       {"name": "Sydney",       "country": "Australia",     "latitude": -33.8688, "longitude": 151.2093,   "timezone": "Australia/Sydney"},
    "bali":         {"name": "Bali",         "country": "Indonesia",     "latitude": -8.3405,  "longitude": 115.0920,   "timezone": "Asia/Makassar"},
    "phuket":       {"name": "Phuket",       "country": "Thailand",      "latitude": 7.8804,   "longitude": 98.3923,    "timezone": "Asia/Bangkok"},
    "pattaya":      {"name": "Pattaya",      "country": "Thailand",      "latitude": 12.9236,  "longitude": 100.8825,   "timezone": "Asia/Bangkok"},
    "chiang mai":   {"name": "Chiang Mai",   "country": "Thailand",      "latitude": 18.7883,  "longitude": 98.9853,    "timezone": "Asia/Bangkok"},
    "amsterdam":    {"name": "Amsterdam",    "country": "Netherlands",   "latitude": 52.3676,  "longitude": 4.9041,     "timezone": "Europe/Amsterdam"},
    "rome":         {"name": "Rome",         "country": "Italy",         "latitude": 41.9028,  "longitude": 12.4964,    "timezone": "Europe/Rome"},
    "venice":       {"name": "Venice",       "country": "Italy",         "latitude": 45.4408,  "longitude": 12.3155,    "timezone": "Europe/Rome"},
    "milan":        {"name": "Milan",        "country": "Italy",         "latitude": 45.4642,  "longitude": 9.1900,     "timezone": "Europe/Rome"},
    "barcelona":    {"name": "Barcelona",    "country": "Spain",         "latitude": 41.3874,  "longitude": 2.1686,     "timezone": "Europe/Madrid"},
    "madrid":       {"name": "Madrid",       "country": "Spain",         "latitude": 40.4168,  "longitude": -3.7038,    "timezone": "Europe/Madrid"},
    "istanbul":     {"name": "Istanbul",     "country": "Turkey",        "latitude": 41.0082,  "longitude": 28.9784,    "timezone": "Europe/Istanbul"},
    "singapore":    {"name": "Singapore",    "country": "Singapore",     "latitude": 1.3521,   "longitude": 103.8198,   "timezone": "Asia/Singapore"},
    "kuala lumpur": {"name": "Kuala Lumpur", "country": "Malaysia",      "latitude": 3.1390,   "longitude": 101.6869,   "timezone": "Asia/Kuala_Lumpur"},
    "hong kong":    {"name": "Hong Kong",    "country": "Hong Kong",     "latitude": 22.3193,  "longitude": 114.1694,   "timezone": "Asia/Hong_Kong"},
    "seoul":        {"name": "Seoul",        "country": "South Korea",   "latitude": 37.5665,  "longitude": 126.9780,   "timezone": "Asia/Seoul"},
    "osaka":        {"name": "Osaka",        "country": "Japan",         "latitude": 34.6937,  "longitude": 135.5023,   "timezone": "Asia/Tokyo"},
    "kyoto":        {"name": "Kyoto",        "country": "Japan",         "latitude": 35.0116,  "longitude": 135.7681,   "timezone": "Asia/Tokyo"},
    "maldives":     {"name": "Maldives",     "country": "Maldives",      "latitude": 3.2028,   "longitude": 73.2207,    "timezone": "Indian/Maldives"},
    "male":         {"name": "Malé",         "country": "Maldives",      "latitude": 4.1755,   "longitude": 73.5093,    "timezone": "Indian/Maldives"},
    "cairo":        {"name": "Cairo",        "country": "Egypt",         "latitude": 30.0444,  "longitude": 31.2357,    "timezone": "Africa/Cairo"},
    "cape town":    {"name": "Cape Town",    "country": "South Africa",  "latitude": -33.9249, "longitude": 18.4241,    "timezone": "Africa/Johannesburg"},
    "zurich":       {"name": "Zürich",       "country": "Switzerland",   "latitude": 47.3769,  "longitude": 8.5417,     "timezone": "Europe/Zurich"},
    "vienna":       {"name": "Vienna",       "country": "Austria",       "latitude": 48.2082,  "longitude": 16.3738,    "timezone": "Europe/Vienna"},
    "prague":       {"name": "Prague",       "country": "Czech Republic","latitude": 50.0755,  "longitude": 14.4378,    "timezone": "Europe/Prague"},
    "budapest":     {"name": "Budapest",     "country": "Hungary",       "latitude": 47.4979,  "longitude": 19.0402,    "timezone": "Europe/Budapest"},
    "berlin":       {"name": "Berlin",       "country": "Germany",       "latitude": 52.5200,  "longitude": 13.4050,    "timezone": "Europe/Berlin"},
    "munich":       {"name": "Munich",       "country": "Germany",       "latitude": 48.1351,  "longitude": 11.5820,    "timezone": "Europe/Berlin"},
    "miami":        {"name": "Miami",        "country": "United States", "latitude": 25.7617,  "longitude": -80.1918,   "timezone": "America/New_York"},
    "san francisco":{"name": "San Francisco","country": "United States", "latitude": 37.7749,  "longitude": -122.4194,  "timezone": "America/Los_Angeles"},
    "las vegas":    {"name": "Las Vegas",    "country": "United States", "latitude": 36.1699,  "longitude": -115.1398,  "timezone": "America/Los_Angeles"},
    "chicago":      {"name": "Chicago",      "country": "United States", "latitude": 41.8781,  "longitude": -87.6298,   "timezone": "America/Chicago"},
    "toronto":      {"name": "Toronto",      "country": "Canada",        "latitude": 43.6532,  "longitude": -79.3832,   "timezone": "America/Toronto"},
    "vancouver":    {"name": "Vancouver",    "country": "Canada",        "latitude": 49.2827,  "longitude": -123.1207,  "timezone": "America/Vancouver"},
    "doha":         {"name": "Doha",         "country": "Qatar",         "latitude": 25.2854,  "longitude": 51.5310,    "timezone": "Asia/Qatar"},
    "abu dhabi":    {"name": "Abu Dhabi",    "country": "UAE",           "latitude": 24.4539,  "longitude": 54.3773,    "timezone": "Asia/Dubai"},
    "riyadh":       {"name": "Riyadh",       "country": "Saudi Arabia",  "latitude": 24.7136,  "longitude": 46.6753,    "timezone": "Asia/Riyadh"},
    "dammam":       {"name": "Dammam",       "country": "Saudi Arabia",  "latitude": 26.4207,  "longitude": 50.0888,    "timezone": "Asia/Riyadh"},
    "manama":       {"name": "Manama",       "country": "Bahrain",       "latitude": 26.2285,  "longitude": 50.5860,    "timezone": "Asia/Bahrain"},
    "kuwait city":  {"name": "Kuwait City",  "country": "Kuwait",        "latitude": 29.3759,  "longitude": 47.9774,    "timezone": "Asia/Kuwait"},
    "muscat":       {"name": "Muscat",       "country": "Oman",          "latitude": 23.5880,  "longitude": 58.3829,    "timezone": "Asia/Muscat"},
    "colombo":      {"name": "Colombo",      "country": "Sri Lanka",     "latitude": 6.9271,   "longitude": 79.8612,    "timezone": "Asia/Colombo"},
    "kathmandu":    {"name": "Kathmandu",    "country": "Nepal",          "latitude": 27.7172,  "longitude": 85.3240,    "timezone": "Asia/Kathmandu"},
    "jakarta":      {"name": "Jakarta",      "country": "Indonesia",     "latitude": -6.2088,  "longitude": 106.8456,   "timezone": "Asia/Jakarta"},
    "manila":       {"name": "Manila",       "country": "Philippines",   "latitude": 14.5995,  "longitude": 120.9842,   "timezone": "Asia/Manila"},
    "ho chi minh":  {"name": "Ho Chi Minh City","country": "Vietnam",   "latitude": 10.8231,  "longitude": 106.6297,   "timezone": "Asia/Ho_Chi_Minh"},
    "hanoi":        {"name": "Hanoi",        "country": "Vietnam",       "latitude": 21.0278,  "longitude": 105.8342,   "timezone": "Asia/Bangkok"},
    "yangon":       {"name": "Yangon",       "country": "Myanmar",       "latitude": 16.8403,  "longitude": 96.1495,    "timezone": "Asia/Yangon"},
    "dhaka":        {"name": "Dhaka",        "country": "Bangladesh",    "latitude": 23.8103,  "longitude": 90.4125,    "timezone": "Asia/Dhaka"},
    "karachi":      {"name": "Karachi",      "country": "Pakistan",      "latitude": 24.8607,  "longitude": 67.0011,    "timezone": "Asia/Karachi"},
    "lahore":       {"name": "Lahore",       "country": "Pakistan",      "latitude": 31.5204,  "longitude": 74.3587,    "timezone": "Asia/Karachi"},
    "islamabad":    {"name": "Islamabad",    "country": "Pakistan",      "latitude": 33.6844,  "longitude": 73.0479,    "timezone": "Asia/Karachi"},
    "tel aviv":     {"name": "Tel Aviv",     "country": "Israel",        "latitude": 32.0853,  "longitude": 34.7818,    "timezone": "Asia/Jerusalem"},
    "beirut":       {"name": "Beirut",       "country": "Lebanon",       "latitude": 33.8938,  "longitude": 35.5018,    "timezone": "Asia/Beirut"},
    "shanghai":     {"name": "Shanghai",     "country": "China",         "latitude": 31.2304,  "longitude": 121.4737,   "timezone": "Asia/Shanghai"},
    "beijing":      {"name": "Beijing",      "country": "China",         "latitude": 39.9042,  "longitude": 116.4074,   "timezone": "Asia/Shanghai"},
    "shenzhen":     {"name": "Shenzhen",     "country": "China",         "latitude": 22.5431,  "longitude": 114.0579,   "timezone": "Asia/Shanghai"},
    "taipei":       {"name": "Taipei",       "country": "Taiwan",        "latitude": 25.0330,  "longitude": 121.5654,   "timezone": "Asia/Taipei"},
    "athens":       {"name": "Athens",       "country": "Greece",        "latitude": 37.9838,  "longitude": 23.7275,    "timezone": "Europe/Athens"},
    "santorini":    {"name": "Santorini",    "country": "Greece",        "latitude": 36.3932,  "longitude": 25.4615,    "timezone": "Europe/Athens"},
    "lisbon":       {"name": "Lisbon",       "country": "Portugal",      "latitude": 38.7223,  "longitude": -9.1393,    "timezone": "Europe/Lisbon"},
    "dublin":       {"name": "Dublin",       "country": "Ireland",       "latitude": 53.3498,  "longitude": -6.2603,    "timezone": "Europe/Dublin"},
    "edinburgh":    {"name": "Edinburgh",    "country": "United Kingdom","latitude": 55.9533,  "longitude": -3.1883,    "timezone": "Europe/London"},
    "stockholm":    {"name": "Stockholm",    "country": "Sweden",        "latitude": 59.3293,  "longitude": 18.0686,    "timezone": "Europe/Stockholm"},
    "oslo":         {"name": "Oslo",         "country": "Norway",        "latitude": 59.9139,  "longitude": 10.7522,    "timezone": "Europe/Oslo"},
    "copenhagen":   {"name": "Copenhagen",   "country": "Denmark",       "latitude": 55.6761,  "longitude": 12.5683,    "timezone": "Europe/Copenhagen"},
    "helsinki":     {"name": "Helsinki",     "country": "Finland",       "latitude": 60.1699,  "longitude": 24.9384,    "timezone": "Europe/Helsinki"},
    "reykjavik":    {"name": "Reykjavik",    "country": "Iceland",       "latitude": 64.1466,  "longitude": -21.9426,   "timezone": "Atlantic/Reykjavik"},
    "moscow":       {"name": "Moscow",       "country": "Russia",        "latitude": 55.7558,  "longitude": 37.6173,    "timezone": "Europe/Moscow"},
    "rio de janeiro":{"name":"Rio de Janeiro","country":"Brazil",        "latitude": -22.9068, "longitude": -43.1729,   "timezone": "America/Sao_Paulo"},
    "sao paulo":    {"name": "São Paulo",    "country": "Brazil",        "latitude": -23.5505, "longitude": -46.6333,   "timezone": "America/Sao_Paulo"},
    "buenos aires": {"name": "Buenos Aires", "country": "Argentina",     "latitude": -34.6037, "longitude": -58.3816,   "timezone": "America/Argentina/Buenos_Aires"},
    "santiago":     {"name": "Santiago",     "country": "Chile",         "latitude": -33.4489, "longitude": -70.6693,   "timezone": "America/Santiago"},
    "lima":         {"name": "Lima",         "country": "Peru",          "latitude": -12.0464, "longitude": -77.0428,   "timezone": "America/Lima"},
    "bogota":       {"name": "Bogotá",       "country": "Colombia",      "latitude": 4.7110,   "longitude": -74.0721,   "timezone": "America/Bogota"},
    "mexico city":  {"name": "Mexico City",  "country": "Mexico",        "latitude": 19.4326,  "longitude": -99.1332,   "timezone": "America/Mexico_City"},
    "cancun":       {"name": "Cancún",       "country": "Mexico",        "latitude": 21.1619,  "longitude": -86.8515,   "timezone": "America/Cancun"},
    "nairobi":      {"name": "Nairobi",      "country": "Kenya",         "latitude": -1.2921,  "longitude": 36.8219,    "timezone": "Africa/Nairobi"},
    "casablanca":   {"name": "Casablanca",   "country": "Morocco",       "latitude": 33.5731,  "longitude": -7.5898,    "timezone": "Africa/Casablanca"},
    "marrakech":    {"name": "Marrakech",    "country": "Morocco",       "latitude": 31.6295,  "longitude": -7.9811,    "timezone": "Africa/Casablanca"},
    "mauritius":    {"name": "Mauritius",    "country": "Mauritius",     "latitude": -20.3484, "longitude": 57.5522,    "timezone": "Indian/Mauritius"},
    "fiji":         {"name": "Fiji",         "country": "Fiji",          "latitude": -17.7134, "longitude": 178.0650,   "timezone": "Pacific/Fiji"},
    "auckland":     {"name": "Auckland",     "country": "New Zealand",   "latitude": -36.8485, "longitude": 174.7633,   "timezone": "Pacific/Auckland"},
}

# Build a reverse-lookup from canonical names → mapping keys
# Only maps FULL canonical names, NEVER individual words (avoids false matches like "york" → New York)
_ALIAS_MAP = {}
for key, val in POPULAR_MAPPINGS.items():
    canonical = val["name"].lower()
    if canonical not in _ALIAS_MAP and canonical != key:
        _ALIAS_MAP[canonical] = key


async def geocode(place_name: str) -> dict:
    """Resolve place name to lat/lon/timezone.

    Strategy (reliability first):
    1. Check hardcoded POPULAR_MAPPINGS first (instant, zero-fail).
    2. Try fuzzy/alias matching on POPULAR_MAPPINGS for spelling variations.
    3. Check module-level cache.
    4. Try Open-Meteo Geocoding API (clean REST API, good coverage).
    5. Try DuckDuckGo web search as last resort (regex is fragile).
    """
    normalized_name = place_name.strip().lower()

    # 1. Exact match in POPULAR_MAPPINGS (instant, covers 150+ cities)
    entry = POPULAR_MAPPINGS.get(normalized_name)
    if entry:
        return dict(entry)

    # 2. Fuzzy match — try alternate names and partial matches
    fuzzy = _fuzzy_lookup(normalized_name)
    if fuzzy:
        return dict(fuzzy)

    # 3. Check cache
    if normalized_name in _cache:
        return _cache[normalized_name]

    # 4. Open-Meteo Geocoding API (reliable, structured, good coverage)
    coords = await _resolve_via_openmeteo(place_name)
    if coords:
        _cache[normalized_name] = coords
        return coords

    # 5. Web search (fragile regex, last resort)
    coords = await _resolve_via_web_search(place_name)
    if coords:
        _cache[normalized_name] = coords
        return coords

    return {"error": f"Location not found: '{place_name}'"}


def _fuzzy_lookup(name: str) -> dict | None:
    """Try fuzzy matching on POPULAR_MAPPINGS for alternate spellings and variations."""
    if len(name) < 3:
        return None

    # Check alias map (built from canonical names like "bombay" → "mumbai")
    alias_key = _ALIAS_MAP.get(name)
    if alias_key:
        return POPULAR_MAPPINGS[alias_key]

    # Try prefix matching (e.g. "banga" -> "Bangalore", "new y" -> "New York")
    for key, val in POPULAR_MAPPINGS.items():
        if key.startswith(name) or name.startswith(key):
            return val
        # Check if canonical name starts with the input
        if val["name"].lower().startswith(name):
            return val

    return None


async def _resolve_via_web_search(place_name: str) -> dict | None:
    """Use DuckDuckGo web search to find coordinates of a place.
    
    Args:
        place_name (str): The name of the place.
        
    Returns:
        dict | None: Dictionary of coordinates if resolved, else None.
    """
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

        combined = " ".join(f"{r.get('title', '')} {r.get('snippet', '')}" for r in results)

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
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    logger.info(f"Web search resolved '{place_name}' -> ({lat}, {lon})")
                    return {
                        "name": place_name.title(),
                        "country": "",
                        "latitude": lat,
                        "longitude": lon,
                        "timezone": "UTC",
                    }

        return None
    except Exception as e:
        logger.warning(f"Web search geocoding failed for '{place_name}': {e}")
        return None


async def _resolve_via_openmeteo(place_name: str) -> dict | None:
    """Resolve location using Open-Meteo Geocoding API.
    
    Args:
        place_name (str): The name of the place.
        
    Returns:
        dict | None: Dictionary of coordinates if resolved, else None.
    """
    try:
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
