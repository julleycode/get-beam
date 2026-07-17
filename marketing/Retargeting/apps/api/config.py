from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql://retarget:retarget@localhost:5432/retarget"
    redis_url: str = "redis://localhost:6379/0"
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "retarget"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    api_secret_key: str = "supersecretkey"
    cors_origins: str = "http://localhost:3000"
    anthropic_api_key: str = "mock"
    mock_ai: bool = True
    pdl_api_key: str = "mock"
    fullcontact_api_key: str = "mock"
    proxycurl_api_key: str = "mock"
    mock_enrichment: bool = True
    resend_api_key: str = "mock"
    from_email: str = "noreply@retargetagent.local"
    mock_email: bool = True
    app_url: str = "http://localhost:3000"
    pixel_url: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
