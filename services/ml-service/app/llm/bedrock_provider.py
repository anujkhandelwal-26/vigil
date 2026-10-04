"""
Real call shape for AWS Bedrock (Claude via the Converse API), kept
untested in this environment (no AWS credentials configured for the
hackathon demo) but structurally correct behind the same LlmProvider
interface as OllamaProvider. Selected by setting LLM_PROVIDER=bedrock.
"""
from app.config import settings
from app.llm.provider import LlmProvider


class BedrockProvider(LlmProvider):
    def __init__(self):
        import boto3
        self.client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        self._model = settings.bedrock_llm_model_id

    @property
    def name(self) -> str:
        return "bedrock"

    @property
    def model(self) -> str:
        return self._model

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
        kwargs = {}
        if system_prompt:  # Converse rejects an empty system text block
            kwargs["system"] = [{"text": system_prompt}]
        resp = self.client.converse(
            modelId=self._model,
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
            **kwargs,
        )
        return resp["output"]["message"]["content"][0]["text"].strip()
