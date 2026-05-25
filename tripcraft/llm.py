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

        retries = 3
        delay = 1.5
        backoff_factor = 1.5
        last_exc = None

        async def _try_client(client, client_idx, req_kwargs):
            try:
                res = await client.chat.completions.create(**req_kwargs)
                return res, client_idx
            except Exception as e:
                logger.warning(f"Speculative LLM call on key index {client_idx} failed: {e}")
                raise e

        for attempt in range(1, retries + 1):
            if len(self.clients) > 1:
                logger.info(f"LLM speculative race starting (attempt {attempt}/{retries}) across {len(self.clients)} parallel keys...")
                tasks = [
                    asyncio.create_task(_try_client(self.clients[i], i, kwargs))
                    for i in range(len(self.clients))
                ]
                
                pending = set(tasks)
                successful_response = None
                
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        try:
                            res, idx = t.result()
                            successful_response = res
                            self.current_client_idx = idx
                            logger.info(f"🏆 Key index {idx} won the speculative LLM race!")
                            break
                        except Exception as e:
                            last_exc = e
                    
                    if successful_response:
                        break
                
                # Clean up / cancel remaining tasks
                for t in pending:
                    t.cancel()
                
                if successful_response:
                    return successful_response
            else:
                # Single client fallback
                client = self.clients[0]
                try:
                    return await client.chat.completions.create(**kwargs)
                except Exception as e:
                    last_exc = e

            # If we reached here, all keys failed or single client failed.
            # Perform backoff sleep before retry.
            wait_time = min(delay * (backoff_factor ** (attempt - 1)), 5.0)
            reason = "transient error / rate limits"
            logger.warning(f"All parallel LLM attempts failed. Retrying in {wait_time:.2f}s... (Attempt {attempt}/{retries})")
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
