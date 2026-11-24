from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, PositiveFloat, PositiveInt, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    jwt_signing_key: SecretStr = Field(min_length=1)
    jwt_leeway_seconds: int = Field(default=0, ge=0)
    auth_redis_url: RedisDsn = RedisDsn("redis://127.0.0.1:6379/1")
    auth_redis_timeout: PositiveFloat = 0.5
    drf_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8896")
    http_connect_timeout: PositiveFloat = 1.0
    http_read_timeout: PositiveFloat = 3.0
    drf_total_timeout: PositiveFloat = 5.0
    http_max_connections: PositiveInt = 32
    upstream_concurrency: PositiveInt = 16
    upstream_slot_timeout: PositiveFloat = 1.0
    drf_max_retries: int = Field(default=2, ge=0, le=5)
    llm_timeout: PositiveFloat = 30.0
    stream_timeout: PositiveFloat = 90.0
    stream_ping_interval: PositiveFloat = 10.0
    analysis_cache_ttl: PositiveInt = 600
    mock_llm: bool = True
    mock_llm_mode: Literal["normal", "slow", "timeout", "error"] = "normal"
    mock_first_delay: float = Field(default=0.15, ge=0)
    mock_chunk_delay: float = Field(default=0.05, ge=0)
    mock_chunks: int = Field(default=8, ge=1, le=100)
    llm_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_thinking: Literal["default", "enabled", "disabled"] = "default"

    @model_validator(mode="after")
    def require_provider_key(self) -> Self:
        if not self.mock_llm and (not self.llm_api_key or not self.llm_api_key.get_secret_value().strip()):
            raise ValueError("LLM_API_KEY is required when MOCK_LLM=false")
        return self
