from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"

    def validate_secret_key(self) -> None:
        """Warn if default secret keys are used in production."""
        import logging
        _log = logging.getLogger(__name__)
        if self.app_env == "production" and self.app_secret_key == "change-me-in-production":
            _log.warning(
                "APP_SECRET_KEY is still the default value in production. "
                "Set a strong random secret via environment variable."
            )
        if (
            self.app_env == "production"
            and self.jwt_secret == "change-me-in-production"
            and not self.clerk_secret_key
        ):
            _log.warning(
                "JWT_SECRET is still the default value in production. "
                "Set a strong random secret via environment variable."
            )

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

    # ─── Clerk Authentication ───
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    jwt_secret: str = "change-me-in-production"  # Legacy HS256 fallback
    jwt_algorithm: str = "HS256"

    # ─── External APIs (EasyTrack) ───
    people_data_labs_api_key: str = ""
    fullcontact_api_key: str = ""  # deprecated — FullContact moved to B2B enterprise
    proxycurl_api_key: str = ""
    anthropic_api_key: str = ""
    resend_api_key: str = ""

    # ─── Waterfall enrichment providers ───
    ipinfo_token: str = ""          # IP → company/geolocation (50K free/month)
    hunter_api_key: str = ""        # Domain → employee emails (25 free/month)
    apollo_api_key: str = ""        # Contact database + email finder (10K credits free/month)

    # Shopify
    shopify_api_key: str = ""
    shopify_api_secret: str = ""

    # ─── OAuth Credentials (EasyEngage) ───
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    twitter_redirect_uri: str = "http://localhost:8000/api/v1/social/twitter/callback"
    twitter_bearer_token: str = ""

    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_redirect_uri: str = "http://localhost:8000/api/v1/social/facebook/callback"

    instagram_redirect_uri: str = "http://localhost:8000/api/v1/social/instagram/callback"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/api/v1/social/linkedin/callback"

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8000/api/v1/social/tiktok/callback"

    # ─── Encryption ───
    encryption_key: str = ""  # Fernet key for BYOK API keys (strict)
    token_encryption_key: str = ""  # Fernet key for OAuth tokens (graceful)

    # ─── Feature flags ───
    mock_external_apis: bool = True          # Enrichment/identity APIs (PDL, IPinfo, etc.)
    mock_social_oauth: bool = True           # Social OAuth (Twitter, Facebook, etc.)
    sync_interval_minutes: int = 60

    # ─── Rate limits ───
    default_daily_resolution_budget: int = 50
    max_emails_per_hour_per_site: int = 50

    # CORS — comma-separated origins allowed
    cors_origins: str = "http://localhost:3000"

    model_config = {"env_file": ("../../.env", ".env"), "extra": "ignore"}


settings = Settings()
