from openai import AsyncOpenAI

class LLMClient:
    MODEL = "mistralai/mistral-large-2-instruct"
    BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(self, config):
        self.client = AsyncOpenAI(
            api_key=config.nvidia_key,
            base_url=self.BASE_URL,
        )
        self.model = self.MODEL

    async def complete(self, messages: list, tools: list | None = None):
        """Send chat completion request to NVIDIA NIM."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
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
            "model": self.MODEL,
            "base_url": self.BASE_URL,
            "status": "connected",
        }
