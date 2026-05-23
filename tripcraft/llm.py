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
        
        Args:
            messages: The list of messages to send.
            tools: Optional list of tool definitions.
            on_retry: Optional async callable(attempt, wait_time, reason) invoked before each retry sleep.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 4096,
            "timeout": 15.0,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            if self.provider == "nvidia":
                kwargs["parallel_tool_calls"] = True

        retries = 6
        delay = 1.0
        backoff_factor = 2.0
        last_exc = None

        keys_tried_in_row = 0

        for attempt in range(1, retries + 1):
            client = self.clients[self.current_client_idx]
            try:
                return await client.chat.completions.create(**kwargs)
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                # Detect rate limit errors, quotas, transient server timeouts, or auth issues
                is_transient = (
                    "429" in err_str 
                    or "too many requests" in err_str 
                    or "rate limit" in err_str 
                    or "500" in err_str 
                    or "timeout" in err_str 
                    or "timed out" in err_str
                    or "timedout" in err_str
                    or "503" in err_str
                    or "busy" in err_str
                    or "403" in err_str
                    or "forbidden" in err_str
                    or "unauthorized" in err_str
                    or "401" in err_str
                )
                
                if not is_transient or attempt == retries:
                    logger.error(f"LLM completion failed permanently on attempt {attempt}: {e}")
                    raise e

                # Rotate to the next key if we have multiple keys
                if len(self.clients) > 1:
                    old_idx = self.current_client_idx
                    self.current_client_idx = (self.current_client_idx + 1) % len(self.clients)
                    keys_tried_in_row += 1
                    logger.warning(
                        f"LLM call failed (attempt {attempt}/{retries}): {e}. "
                        f"Rotating from key index {old_idx} to index {self.current_client_idx}."
                    )
                    
                    # If we haven't tried all keys yet in this failure burst, retry immediately (no sleep)!
                    if keys_tried_in_row < len(self.clients):
                        logger.info("Retrying next key index immediately...")
                        continue

                # If all keys failed or we only have one key, perform backoff sleep
                keys_tried_in_row = 0
                wait_time = delay * (backoff_factor ** (attempt - 1))
                reason = "rate limited / auth error" if ("429" in err_str or "rate limit" in err_str or "403" in err_str or "401" in err_str) else "transient error"
                logger.warning(
                    f"All keys tried or rate-limited. Retrying in {wait_time:.2f}s... (Attempt {attempt}/{retries})"
                )
                # Notify caller so it can surface status to the user
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
