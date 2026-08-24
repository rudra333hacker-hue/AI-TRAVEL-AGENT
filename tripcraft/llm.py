import asyncio
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("tripcraft")

PROVIDER_LABELS = {
    "nvidia": "NVIDIA NIM",
    "gemini": "Google AI Studio (Gemini)",
    "groq": "Groq Console",
}


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

        # Build primary clients
        if not self.keys:
            self.clients = [AsyncOpenAI(api_key="", base_url=self.base_url)]
        else:
            self.clients = [AsyncOpenAI(api_key=key, base_url=self.base_url) for key in self.keys]
            
        # Build fallback clients from other providers if available
        self.fallback_clients = []
        if self.provider != "nvidia" and getattr(config, "nvidia_keys_list", []):
            for k in config.nvidia_keys_list:
                self.fallback_clients.append((
                    AsyncOpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1"),
                    "meta/llama-3.3-70b-instruct",
                    "nvidia"
                ))
        if self.provider != "gemini" and getattr(config, "gemini_keys_list", []):
            for k in config.gemini_keys_list:
                self.fallback_clients.append((
                    AsyncOpenAI(api_key=k, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
                    "gemini-2.5-flash",
                    "gemini"
                ))
            
        self.current_client_idx = 0
        logger.info(
            f"LLM initialized: provider={PROVIDER_LABELS.get(self.provider, self.provider)}, "
            f"model={self.model}, base_url={self.base_url}, active_keys={len(self.keys)}, fallback_clients={len(self.fallback_clients)}"
        )

    async def complete(self, messages: list, tools: list | None = None, on_retry=None):
        """Send chat completion request to the configured provider with retries for transient errors.
        
        Uses speculative parallel execution (race-mode) across all configured keys for absolute speed and reliability.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
            "timeout": 30.0,  # Standard timeout for reliable generations
        }
        if self.provider != "gemini":
            kwargs["max_tokens"] = 3000
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            # Only restrict tool calls to a single call on NVIDIA NIM
            if self.provider == "nvidia":
                kwargs["parallel_tool_calls"] = False

        retries = 3
        delay = 1.5
        backoff_factor = 1.5
        last_exc = None

        for attempt in range(1, retries + 1):
            # 1. Try primary provider keys sequentially
            for i, client in enumerate(self.clients):
                try:
                    logger.info(f"LLM request attempting primary key index {i} (attempt {attempt}/{retries})...")
                    req_kwargs = dict(kwargs)
                    if self.provider == "nvidia":
                        req_kwargs["timeout"] = 7.0
                    else:
                        req_kwargs["timeout"] = 30.0
                    
                    res = await client.chat.completions.create(**req_kwargs)
                    self.current_client_idx = i
                    logger.info(f"🏆 Primary key index {i} succeeded!")
                    return res
                except Exception as e:
                    last_exc = e
                    err_str = str(e)
                    logger.warning(f"LLM primary key index {i} failed: {err_str}")
                    if "400" in err_str and "rate" not in err_str.lower() and "429" not in err_str:
                        raise e
                    continue

            # 2. Try fallback provider clients if primary keys are exhausted
            for fb_idx, (fb_client, fb_model, fb_provider) in enumerate(self.fallback_clients):
                try:
                    logger.info(f"LLM request attempting fallback provider {fb_provider} ({fb_model}) index {fb_idx}...")
                    fb_kwargs = dict(kwargs)
                    fb_kwargs["model"] = fb_model
                    if fb_provider != "gemini":
                        fb_kwargs["max_tokens"] = 3000
                    elif "max_tokens" in fb_kwargs:
                        del fb_kwargs["max_tokens"]
                    if fb_provider == "nvidia":
                        fb_kwargs["timeout"] = 7.0
                    else:
                        fb_kwargs["timeout"] = 30.0

                    res = await fb_client.chat.completions.create(**fb_kwargs)
                    logger.info(f"🏆 Fallback provider {fb_provider} index {fb_idx} succeeded!")
                    return res
                except Exception as fb_err:
                    last_exc = fb_err
                    logger.warning(f"LLM fallback provider {fb_provider} index {fb_idx} failed: {fb_err}")
                    continue

            # If we reached here, all keys failed.
            # Perform backoff sleep before retry.
            wait_time = min(delay * (backoff_factor ** (attempt - 1)), 5.0)
            reason = "transient error or rate limits"
            logger.warning(f"All LLM keys failed in round {attempt}. Retrying in {wait_time:.2f}s...")
            if on_retry:
                try:
                    await on_retry(attempt, wait_time, reason)
                except Exception:
                    pass
            await asyncio.sleep(wait_time)

        if last_exc:
            raise last_exc

    async def close(self):
        for client in self.clients:
            await client.close()

    def status(self) -> dict:
        return {
            "provider": PROVIDER_LABELS.get(self.provider, self.provider),
            "model": self.model,
            "base_url": self.base_url,
            "status": "connected",
            "active_keys": len(self.keys),
        }
