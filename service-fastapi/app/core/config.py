from pydantic import AnyHttpUrl, Field, PositiveFloat, PositiveInt, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    jwt_signing_key: SecretStr = Field(min_length=1)
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
