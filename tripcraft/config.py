import os
from dotenv import load_dotenv


# ── Supported LLM providers ──
PROVIDER_NVIDIA = "nvidia"
PROVIDER_AIMLAPI = "aimlapi"

AIMLAPI_BASE_URL = "https://api.aimlapi.com/v1"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# ── Default models per provider ──
DEFAULT_MODELS = {
    PROVIDER_NVIDIA: "meta/llama-3.3-70b-instruct",
    PROVIDER_AIMLAPI: "openai/gpt-4o",
}


class Config:
    def __init__(self):
        load_dotenv()

        # ── Provider selection ──
        # Auto-detect: if no provider explicitly set, prefer AIMLAPI if key exists,
        # fall back to NVIDIA if NVIDIA key exists.
        explicit_provider = os.getenv("LLM_PROVIDER")
        if explicit_provider:
            self.llm_provider = explicit_provider.lower()
        else:
            self.aimlapi_key = os.getenv("AIMLAPI_API_KEY", "")
            self.nvidia_key = os.getenv("NVIDIA_API_KEY", "")
            if self.aimlapi_key:
                self.llm_provider = PROVIDER_AIMLAPI
            elif self.nvidia_key:
                self.llm_provider = PROVIDER_NVIDIA
            else:
                self.llm_provider = PROVIDER_AIMLAPI  # default fallback

        # ── API keys ──
        self.nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        self.nvidia_key_2 = os.getenv("NVIDIA_API_KEY_2", "")   # Optional second key for premium model
        self.aimlapi_key = os.getenv("AIMLAPI_API_KEY", "")
        self.foursquare_key = os.getenv("FOURSQUARE_API_KEY", "")
        self.amadeus_client_id = os.getenv("AMADEUS_CLIENT_ID", "")
        self.amadeus_client_secret = os.getenv("AMADEUS_CLIENT_SECRET", "")

        # ── Server ──
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.session_ttl = int(os.getenv("SESSION_TTL_MINUTES", "30"))

        # ── LLM model ──
        # Use provider-specific env var if set, else fall back to default
        env_model_key = f"{self.llm_provider.upper()}_MODEL"
        self.llm_model = os.getenv(
            env_model_key,
            DEFAULT_MODELS.get(self.llm_provider, DEFAULT_MODELS[PROVIDER_AIMLAPI])
        )

        # ── Active API key & base URL ──
        if self.llm_provider == PROVIDER_AIMLAPI:
            self.active_api_key = self.aimlapi_key
            self.active_base_url = AIMLAPI_BASE_URL
            if not self.active_api_key:
                raise RuntimeError(
                    "AIMLAPI_API_KEY is required when LLM_PROVIDER=aimlapi. "
                    "Add it to your .env file or set LLM_PROVIDER=nvidia to use NVIDIA."
                )
        elif self.llm_provider == PROVIDER_NVIDIA:
            # Use key_2 for premium model if available
            self.active_api_key = self.nvidia_key_2 or self.nvidia_key
            self.active_base_url = NVIDIA_BASE_URL
            if not self.active_api_key:
                raise RuntimeError(
                    "NVIDIA_API_KEY is required when LLM_PROVIDER=nvidia. "
                    "Get one free at https://build.nvidia.com"
                )
        else:
            raise RuntimeError(
                f"Unknown LLM_PROVIDER '{self.llm_provider}'. "
                f"Supported: {PROVIDER_NVIDIA}, {PROVIDER_AIMLAPI}"
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
