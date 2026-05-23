import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.nvidia_key = os.getenv("NVIDIA_API_KEY")
        self.foursquare_key = os.getenv("FOURSQUARE_API_KEY")
        self.amadeus_client_id = os.getenv("AMADEUS_CLIENT_ID")
        self.amadeus_client_secret = os.getenv("AMADEUS_CLIENT_SECRET")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.session_ttl = int(os.getenv("SESSION_TTL_MINUTES", "30"))

        if not self.nvidia_key:
            raise RuntimeError(
                "NVIDIA_API_KEY is required. Get one free at https://build.nvidia.com "
                "and add it to your .env file."
            )

    @property
    def has_foursquare(self) -> bool:
        return bool(self.foursquare_key)

    @property
    def has_amadeus(self) -> bool:
        return bool(self.amadeus_client_id and self.amadeus_client_secret)
