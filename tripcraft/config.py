import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.nvidia_key = os.getenv("NVIDIA_API_KEY")
        self.nvidia_key_2 = os.getenv("NVIDIA_API_KEY_2")   # Optional second key for better model
        self.foursquare_key = os.getenv("FOURSQUARE_API_KEY")
        self.amadeus_client_id = os.getenv("AMADEUS_CLIENT_ID")
        self.amadeus_client_secret = os.getenv("AMADEUS_CLIENT_SECRET")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.session_ttl = int(os.getenv("SESSION_TTL_MINUTES", "30"))

        # Model selection: use env variable or default
        # Supported NVIDIA NIM models (best first):
        #   nvidia/llama-3.1-nemotron-ultra-253b-v1  (best, needs key)
        #   meta/llama-3.1-405b-instruct             (great, needs key)
        #   nvidia/llama-3.3-nemotron-super-49b-v1   (good balance)
        #   meta/llama-3.3-70b-instruct              (default, free tier)
        self.llm_model = os.getenv(
            "NVIDIA_MODEL",
            "meta/llama-3.3-70b-instruct"
        )
        # Use key_2 for the premium model if provided, else fall back to key
        self.active_nvidia_key = self.nvidia_key_2 if self.nvidia_key_2 else self.nvidia_key

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

    @property
    def has_premium_model(self) -> bool:
        return bool(self.nvidia_key_2)
