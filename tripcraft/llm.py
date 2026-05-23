import asyncio
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("tripcraft")

PROVIDER_LABELS = {
    "nvidia": "NVIDIA NIM",
    "aimlapi": "AIMLAPI (OpenAI-compatible)",
}


class LLMClient:
    def __init__(self, config):
        self.model = config.llm_model
        self.provider = config.llm_provider
        self.base_url = config.active_base_url
        self.client = AsyncOpenAI(
            api_key=config.active_api_key,
            base_url=self.base_url,
        )
        logger.info(
            f"LLM initialized: provider={PROVIDER_LABELS.get(self.provider, self.provider)}, "
            f"model={self.model}, base_url={self.base_url}"
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
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            if self.provider == "nvidia":
                kwargs["parallel_tool_calls"] = False

        retries = 4
        delay = 1.0
        backoff_factor = 2.0
        last_exc = None

        for attempt in range(1, retries + 1):
            try:
                return await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                # Detect rate limit errors, quotas, or transient server timeouts
                is_transient = (
                    "429" in err_str 
                    or "too many requests" in err_str 
                    or "rate limit" in err_str 
                    or "500" in err_str 
                    or "timeout" in err_str 
                    or "503" in err_str
                    or "busy" in err_str
                )
                
                if not is_transient or attempt == retries:
                    logger.error(f"LLM completion failed permanently: {e}")
                    raise e

                wait_time = delay * (backoff_factor ** (attempt - 1))
                reason = "rate limited" if ("429" in err_str or "rate limit" in err_str) else "transient error"
                logger.warning(
                    f"LLM {reason}: {e}. "
                    f"Retrying in {wait_time:.2f}s... (Attempt {attempt}/{retries})"
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
        await self.client.close()

    def status(self) -> dict:
        return {
            "provider": PROVIDER_LABELS.get(self.provider, self.provider),
            "model": self.model,
            "base_url": self.base_url,
            "status": "connected",
        }
