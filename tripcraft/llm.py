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
        
        # Track rate-limited keys to avoid hammering them
        self._rate_limited_keys = {}  # key_index -> timestamp when rate limit expires
        
        logger.info(
            f"LLM initialized: provider={PROVIDER_LABELS.get(self.provider, self.provider)}, "
            f"model={self.model}, base_url={self.base_url}, active_keys={len(self.keys)}, fallback_clients={len(self.fallback_clients)}"
        )

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an error is a rate limit / quota / resource exhausted error."""
        err_str = str(error).lower()
        return any(kw in err_str for kw in [
            "429", "rate limit", "rate_limit", "resource exhausted",
            "resource_exhausted", "too many requests", "quota",
            "server_busy", "overloaded", "capacity"
        ])

    def _is_bad_request_error(self, error: Exception) -> bool:
        """Check if an error is a non-retryable bad request (malformed input etc.)."""
        err_str = str(error)
        # 400 errors that are NOT rate limits should not be retried
        if "400" in err_str and not self._is_rate_limit_error(error):
            return True
        return False

    async def complete(self, messages: list, tools: list | None = None, on_retry=None):
        """Send chat completion request with robust multi-key, multi-provider failover.
        
        Strategy:
        1. Try all primary provider keys sequentially (skip known rate-limited keys).
        2. If all primary keys fail, try all fallback provider keys.
        3. If everything fails, wait with exponential backoff and retry up to 4 rounds.
        4. On rate limit errors, add a small delay between key attempts to avoid burst.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
        }
        if self.provider != "gemini":
            kwargs["max_tokens"] = 3000
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            # Only restrict tool calls to a single call on NVIDIA NIM
            if self.provider == "nvidia":
                kwargs["parallel_tool_calls"] = False

        max_rounds = 4
        base_delay = 2.0
        last_exc = None
        hit_rate_limit = False

        for round_num in range(1, max_rounds + 1):
            # ── 1. Try primary provider keys ──
            for i, client in enumerate(self.clients):
                try:
                    logger.info(f"LLM request: primary key {i+1}/{len(self.clients)} (round {round_num}/{max_rounds})")
                    req_kwargs = dict(kwargs)
                    req_kwargs["timeout"] = 30.0 if self.provider != "nvidia" else 12.0
                    
                    res = await client.chat.completions.create(**req_kwargs)
                    self.current_client_idx = i
                    logger.info(f"Primary key {i+1} succeeded!")
                    return res
                except Exception as e:
                    last_exc = e
                    err_str = str(e)
                    logger.warning(f"Primary key {i+1} failed: {err_str[:200]}")
                    
                    # Non-retryable errors (bad request, auth errors)
                    if self._is_bad_request_error(e):
                        raise e
                    
                    # If rate limited, add a small delay before trying the next key
                    if self._is_rate_limit_error(e):
                        hit_rate_limit = True
                        await asyncio.sleep(0.5)  # Brief pause between rate-limited keys
                    continue

            # ── 2. Try fallback provider keys ──
            for fb_idx, (fb_client, fb_model, fb_provider) in enumerate(self.fallback_clients):
                try:
                    logger.info(f"Fallback: {fb_provider} ({fb_model}) key {fb_idx+1}/{len(self.fallback_clients)} (round {round_num})")
                    fb_kwargs = dict(kwargs)
                    fb_kwargs["model"] = fb_model
                    
                    # Adjust provider-specific settings
                    if fb_provider == "gemini":
                        fb_kwargs.pop("max_tokens", None)
                        fb_kwargs["timeout"] = 30.0
                    elif fb_provider == "nvidia":
                        fb_kwargs["max_tokens"] = 3000
                        fb_kwargs["timeout"] = 15.0  # Generous timeout for fallback
                    else:
                        fb_kwargs["timeout"] = 30.0

                    res = await fb_client.chat.completions.create(**fb_kwargs)
                    logger.info(f"Fallback {fb_provider} key {fb_idx+1} succeeded!")
                    return res
                except Exception as fb_err:
                    last_exc = fb_err
                    logger.warning(f"Fallback {fb_provider} key {fb_idx+1} failed: {str(fb_err)[:200]}")
                    
                    if self._is_rate_limit_error(fb_err):
                        hit_rate_limit = True
                        await asyncio.sleep(0.5)
                    continue

            # ── 3. All keys exhausted this round — backoff before retry ──
            if round_num < max_rounds:
                wait_time = min(base_delay * (1.5 ** (round_num - 1)), 8.0)
                if hit_rate_limit:
                    wait_time = max(wait_time, 3.0)  # Minimum 3s on rate limits
                
                logger.warning(
                    f"All {len(self.clients)} primary + {len(self.fallback_clients)} fallback keys failed "
                    f"(round {round_num}). Retrying in {wait_time:.1f}s..."
                )
                if on_retry:
                    try:
                        await on_retry(round_num, wait_time, 
                                       "rate limit" if hit_rate_limit else "transient error")
                    except Exception:
                        pass
                await asyncio.sleep(wait_time)
                hit_rate_limit = False  # Reset for next round

        # All rounds exhausted
        total_keys = len(self.clients) + len(self.fallback_clients)
        logger.error(
            f"LLM request failed after {max_rounds} rounds across {total_keys} keys. "
            f"Last error: {last_exc}"
        )
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
            "fallback_keys": len(self.fallback_clients),
        }
