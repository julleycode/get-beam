from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://retarget:retarget_dev@localhost:5432/retarget_agent"

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "retarget"
    clickhouse_password: str = "retarget_dev"
    clickhouse_db: str = "retarget_events"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # External APIs
    people_data_labs_api_key: str = ""
    fullcontact_api_key: str = ""
    proxycurl_api_key: str = ""
    anthropic_api_key: str = ""
    resend_api_key: str = ""
    twitter_bearer_token: str = ""

    # Shopify
    shopify_api_key: str = ""
    shopify_api_secret: str = ""

    # Encryption (for BYOK API keys at rest)
    encryption_key: str = ""

    # Feature flags
    mock_external_apis: bool = True

    # Rate limits
    default_daily_resolution_budget: int = 50
    max_emails_per_hour_per_site: int = 50

    model_config = {"env_file": ("../../.env", ".env"), "extra": "ignore"}


settings = Settings()
