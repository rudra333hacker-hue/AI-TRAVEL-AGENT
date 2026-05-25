import os
from dotenv import load_dotenv


# ── Supported LLM providers ──
PROVIDER_NVIDIA = "nvidia"
PROVIDER_GEMINI = "gemini"

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# ── Default models per provider ──
DEFAULT_MODELS = {
    PROVIDER_NVIDIA: "meta/llama-3.3-70b-instruct",
    PROVIDER_GEMINI: "gemini-2.0-flash",
}


class Config:
    def __init__(self):
        load_dotenv()

        # ── API keys ──
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        
        self.nvidia_keys_list = []
        for suffix in ["", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9", "_10"]:
            val = os.getenv(f"NVIDIA_API_KEY{suffix}")
            if val and val.strip() and val not in self.nvidia_keys_list:
                self.nvidia_keys_list.append(val)
                
        self.nvidia_key = self.nvidia_keys_list[0] if self.nvidia_keys_list else ""
        self.nvidia_key_2 = self.nvidia_keys_list[1] if len(self.nvidia_keys_list) > 1 else ""
        self.nvidia_key_3 = self.nvidia_keys_list[2] if len(self.nvidia_keys_list) > 2 else ""
        self.nvidia_key_4 = self.nvidia_keys_list[3] if len(self.nvidia_keys_list) > 3 else ""
        
        self.foursquare_key = os.getenv("FOURSQUARE_API_KEY", "")
        self.navitia_key = os.getenv("NAVITIA_API_KEY", "")
        self.amadeus_client_id = os.getenv("AMADEUS_CLIENT_ID", "")
        self.amadeus_client_secret = os.getenv("AMADEUS_CLIENT_SECRET", "")

        # ── Provider selection ──
        # Auto-detect: if no provider explicitly set, prefer Gemini if key exists,
        # otherwise fall back to NVIDIA.
        explicit_provider = os.getenv("LLM_PROVIDER")
        if explicit_provider:
            self.llm_provider = explicit_provider.lower()
        elif self.gemini_key:
            self.llm_provider = PROVIDER_GEMINI
        else:
            self.llm_provider = PROVIDER_NVIDIA

        # ── Server ──
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.session_ttl = int(os.getenv("SESSION_TTL_MINUTES", "30"))

        # ── LLM model ──
        # Use provider-specific env var if set, else fall back to default
        env_model_key = f"{self.llm_provider.upper()}_MODEL"
        self.llm_model = os.getenv(
            env_model_key,
            DEFAULT_MODELS.get(self.llm_provider, DEFAULT_MODELS[PROVIDER_NVIDIA])
        )

        # ── Active API key & base URL ──
        if self.llm_provider == PROVIDER_NVIDIA:
            self.active_api_key = self.nvidia_key
            self.active_base_url = NVIDIA_BASE_URL
            if not self.active_api_key:
                raise RuntimeError(
                    "NVIDIA_API_KEY is required when LLM_PROVIDER=nvidia. "
                    "Get one free at https://build.nvidia.com"
                )
        elif self.llm_provider == PROVIDER_GEMINI:
            self.active_api_key = self.gemini_key
            self.active_base_url = GEMINI_BASE_URL
            if not self.active_api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is required when LLM_PROVIDER=gemini. "
                    "Get one free at https://aistudio.google.com"
                )
        else:
            raise RuntimeError(
                f"Unknown LLM_PROVIDER '{self.llm_provider}'."
            )

    @property
    def has_foursquare(self) -> bool:
        return bool(self.foursquare_key)

    @property
    def has_navitia(self) -> bool:
        return bool(self.navitia_key)

    @property
    def has_amadeus(self) -> bool:
        return bool(self.amadeus_client_id and self.amadeus_client_secret)

    @property
    def nvidia_keys(self) -> list[str]:
        return self.nvidia_keys_list

    @property
    def has_premium_model(self) -> bool:
        return len(self.nvidia_keys_list) > 1
