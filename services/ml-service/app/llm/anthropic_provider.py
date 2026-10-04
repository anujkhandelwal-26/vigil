"""
Real call shape for the Anthropic API directly (not via Bedrock), kept
untested in this environment but structurally correct. Selected by setting
LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY in .env.
"""
from app.config import settings
from app.llm.provider import LlmProvider


class AnthropicProvider(LlmProvider):
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = "claude-sonnet-5"

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
        kwargs = {"system": system_prompt} if system_prompt else {}
        resp = self.client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user_prompt}],
            **kwargs,
        )
        # The first block isn't guaranteed to be text.
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return ""
