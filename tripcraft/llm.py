import asyncio
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("tripcraft")

PROVIDER_LABELS = {
    "nvidia": "NVIDIA NIM",
    "gemini": "Google AI Studio (Gemini)",
    "groq": "Groq Console",
}

# Supported Gemini model hierarchy for failover across independent quota buckets
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-flash-lite-latest"
]


class LLMClient:
    def __init__(self, config):
        self.model = config.llm_model
        self.provider = config.llm_provider
        self.base_url = config.active_base_url
        
        # Load all available keys for primary provider
        if self.provider == "gemini" and hasattr(config, "gemini_keys_list") and config.gemini_keys_list:
            self.keys = config.gemini_keys_list
        elif self.provider == "nvidia" and hasattr(config, "nvidia_keys_list") and config.nvidia_keys_list:
            self.keys = config.nvidia_keys_list
        elif self.provider == "groq" and hasattr(config, "groq_keys_list") and config.groq_keys_list:
            self.keys = config.groq_keys_list
        else:
            self.keys = [config.active_api_key] if config.active_api_key else []

        # Build clients: map each API key to all available model fallback candidates
        self.clients_pool = []
        if self.provider == "gemini":
            for k in self.keys:
                client = AsyncOpenAI(api_key=k, base_url=self.base_url, timeout=15.0)
                for m in GEMINI_MODELS:
                    self.clients_pool.append((client, m, "gemini"))
        else:
            for k in self.keys:
                client = AsyncOpenAI(api_key=k, base_url=self.base_url, timeout=15.0)
                self.clients_pool.append((client, self.model, self.provider))

        # Build cross-provider fallback clients
        if self.provider != "gemini" and getattr(config, "gemini_keys_list", []):
            for k in config.gemini_keys_list:
                client = AsyncOpenAI(api_key=k, base_url="https://generativelanguage.googleapis.com/v1beta/openai/", timeout=15.0)
                for m in GEMINI_MODELS:
                    self.clients_pool.append((client, m, "gemini"))
                    
        if getattr(config, "nvidia_keys_list", []):
            for k in config.nvidia_keys_list:
                client = AsyncOpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1", timeout=12.0)
                self.clients_pool.append((client, "meta/llama-3.3-70b-instruct", "nvidia"))

        logger.info(
            f"LLM initialized: provider={PROVIDER_LABELS.get(self.provider, self.provider)}, "
            f"model={self.model}, base_url={self.base_url}, total_failover_clients={len(self.clients_pool)}"
        )

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an error is a rate limit / quota / resource exhausted error."""
        err_str = str(error).lower()
        return any(kw in err_str for kw in [
            "429", "rate limit", "rate_limit", "resource exhausted",
            "resource_exhausted", "too many requests", "quota",
            "server_busy", "overloaded", "capacity", "timeout", "timed out"
        ])

    def _is_bad_request_error(self, error: Exception) -> bool:
        """Check if an error is a non-retryable bad request (malformed input etc.)."""
        err_str = str(error)
        if "400" in err_str and not self._is_rate_limit_error(error):
            return True
        return False

    async def complete(self, messages: list, tools: list | None = None, on_retry=None):
        """Send chat completion request with instant failover across Gemini model quota buckets."""
        kwargs = {
            "messages": messages,
            "temperature": 0.5,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        max_rounds = 2
        last_exc = None
        hit_rate_limit = False

        for round_num in range(1, max_rounds + 1):
            for idx, (client, model_name, provider_name) in enumerate(self.clients_pool):
                try:
                    logger.info(f"LLM attempt {idx+1}/{len(self.clients_pool)}: {provider_name} ({model_name})")
                    req_kwargs = dict(kwargs)
                    req_kwargs["model"] = model_name

                    if provider_name != "gemini":
                        req_kwargs["max_tokens"] = 3000
                        if provider_name == "nvidia":
                            req_kwargs["parallel_tool_calls"] = False

                    res = await asyncio.wait_for(
                        client.chat.completions.create(**req_kwargs),
                        timeout=15.0
                    )
                    logger.info(f"🏆 LLM client {idx+1} ({provider_name} - {model_name}) SUCCEEDED!")
                    return res
                except Exception as e:
                    last_exc = e
                    err_str = str(e)
                    logger.warning(f"LLM client {idx+1} ({provider_name} - {model_name}) failed: {err_str[:150]}")
                    
                    if self._is_bad_request_error(e):
                        raise e
                    
                    if self._is_rate_limit_error(e):
                        hit_rate_limit = True
                    continue

            if round_num < max_rounds:
                wait_time = 2.0
                logger.warning(f"All {len(self.clients_pool)} failover targets exhausted in round {round_num}. Retrying in {wait_time}s...")
                if on_retry:
                    try:
                        await on_retry(round_num, wait_time, "rate limit" if hit_rate_limit else "transient error")
                    except Exception:
                        pass
                await asyncio.sleep(wait_time)

        if last_exc:
            raise last_exc

    async def close(self):
        pass

    def status(self) -> dict:
        return {
            "provider": PROVIDER_LABELS.get(self.provider, self.provider),
            "model": self.model,
            "base_url": self.base_url,
            "status": "connected",
            "active_keys": len(self.keys),
            "total_clients": len(self.clients_pool),
        }
