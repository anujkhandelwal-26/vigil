"""Configuration — every value from the environment. No secret defaults."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    database_url: str = "postgresql://vigil:vigil@localhost:5433/vigil"
    ml_service_port: int = 8001
    model_dir: str = "./artifacts"
    # Novelty-channel escalation: an anomaly score at or above this routes the
    # case to at least REVIEW, even when the supervised risk score is low.
    anomaly_review_threshold: float = 0.85

    llm_provider: str = "ollama"
    embedding_provider: str = "ollama"

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:3b-instruct-q4_K_M"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768

    aws_region: str = "ap-south-1"
    bedrock_llm_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"

    anthropic_api_key: str = ""


settings = Settings()
