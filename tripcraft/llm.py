import logging
from openai import AsyncOpenAI

logger = logging.getLogger("tripcraft")

class LLMClient:
    BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(self, config):
        self.model = config.llm_model
        self.client = AsyncOpenAI(
            api_key=config.active_nvidia_key,
            base_url=self.BASE_URL,
        )
        logger.info(f"LLM initialized: {self.model} ({'premium key' if config.has_premium_model else 'default key'})")

    async def complete(self, messages: list, tools: list | None = None):
        """Send chat completion request to NVIDIA NIM."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 4096,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return await self.client.chat.completions.create(**kwargs)

    async def close(self):
        await self.client.close()

    def status(self) -> dict:
        return {
            "provider": "nvidia_nim",
            "model": self.model,
            "base_url": self.BASE_URL,
            "status": "connected",
        }
