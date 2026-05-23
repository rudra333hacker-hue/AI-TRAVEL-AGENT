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

    async def complete(self, messages: list, tools: list | None = None):
        """Send chat completion request to the configured provider."""
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
            "provider": PROVIDER_LABELS.get(self.provider, self.provider),
            "model": self.model,
            "base_url": self.base_url,
            "status": "connected",
        }
