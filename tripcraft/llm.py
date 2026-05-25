import asyncio
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("tripcraft")

PROVIDER_LABELS = {
    "nvidia": "NVIDIA NIM",
}


class LLMClient:
    def __init__(self, config):
        self.model = config.llm_model
        self.provider = config.llm_provider
        self.base_url = config.active_base_url
        
        # Load all available keys from config
        if hasattr(config, "nvidia_keys") and self.provider == "nvidia":
            self.keys = config.nvidia_keys
        else:
            self.keys = [config.active_api_key] if config.active_api_key else []

        # Initialize clients for all keys
        if not self.keys:
            self.clients = [AsyncOpenAI(api_key="", base_url=self.base_url)]
        else:
            self.clients = [AsyncOpenAI(api_key=key, base_url=self.base_url) for key in self.keys]
            
        self.current_client_idx = 0
        logger.info(
            f"LLM initialized: provider={PROVIDER_LABELS.get(self.provider, self.provider)}, "
            f"model={self.model}, base_url={self.base_url}, active_keys={len(self.keys)}"
        )

    async def complete(self, messages: list, tools: list | None = None, on_retry=None):
        """Send chat completion request to the configured provider with retries for transient errors.
        
        Uses speculative parallel execution (race-mode) across all configured keys for absolute speed and reliability.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 3000,
            "timeout": 15.0,  # Shorter timeout since we run in parallel
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False

        retries = 3
        delay = 1.5
        backoff_factor = 1.5
        last_exc = None

        for attempt in range(1, retries + 1):
            # Try keys sequentially to conserve credits
            for i, client in enumerate(self.clients):
                try:
                    logger.info(f"LLM request attempting key index {i} (attempt {attempt}/{retries})...")
                    # Try this client with a short timeout (7.0s) for snappy failover
                    req_kwargs = dict(kwargs)
                    req_kwargs["timeout"] = 7.0
                    
                    res = await client.chat.completions.create(**req_kwargs)
                    self.current_client_idx = i
                    logger.info(f"🏆 Key index {i} succeeded!")
                    return res
                except Exception as e:
                    last_exc = e
                    err_str = str(e)
                    logger.warning(f"LLM key index {i} failed: {err_str}")
                    # If it's a 400 Bad Request, raise it immediately
                    if "400" in err_str:
                        raise e
                    # Otherwise, failover to the next key immediately without waiting!
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
