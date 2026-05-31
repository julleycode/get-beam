from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"

    def validate_production(self) -> None:
        """Fail fast on startup if any critical config is unsafe in production.

        Collects ALL violations and raises a single RuntimeError so the operator
        sees every problem at once rather than one-at-a-time.
        """
        if self.app_env != "production":
            return

        violations: list[str] = []

        if self.app_secret_key == "change-me-in-production":
            violations.append("APP_SECRET_KEY is still the insecure default — set a strong random value")

        if self.jwt_secret == "change-me-in-production" and not self.clerk_secret_key:
            violations.append(
                "JWT_SECRET is still the insecure default and no CLERK_SECRET_KEY is set — "
                "set one of these to secure authentication"
            )

        if self.mock_external_apis:
            violations.append("MOCK_EXTERNAL_APIS=true in production — enrichment/identity data will be fake")

        if self.mock_social_oauth:
            violations.append("MOCK_SOCIAL_OAUTH=true in production — social OAuth flows will be mocked")

        if not self.token_encryption_key:
            violations.append("TOKEN_ENCRYPTION_KEY is empty — OAuth tokens cannot be encrypted at rest")

        if not self.encryption_key:
            violations.append("ENCRYPTION_KEY is empty — BYOK API keys cannot be encrypted at rest")

        if violations:
            bullet_list = "\n  - ".join(violations)
            raise RuntimeError(
                f"PRODUCTION CONFIG ERROR: startup blocked due to {len(violations)} unsafe setting(s):\n"
                f"  - {bullet_list}"
            )

    def validate_secret_key(self) -> None:
        """Alias for validate_production() — kept for backward compatibility."""
        self.validate_production()

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
    anthropic_api_key: str = ""  # legacy — use OpenRouter instead
    openrouter_api_key: str = ""  # OpenRouter.ai — single key for 100+ models
    default_ai_model: str = "deepseek/deepseek-v4-flash:free"  # free tier — good for social replies
    resend_api_key: str = ""

    # ─── Identity Graph (person-level from IP) ───
    rb2b_api_key: str = ""          # RB2B API Suite — IP → hashed email → person (US traffic)
    leadpipe_api_key: str = ""      # Leadpipe — pixel-based identity graph (500 free IDs)
    leadpipe_default_pixel_id: str = ""  # Default Leadpipe pixel ID for all sites
    capturify_api_key: str = ""           # Capturify — identity graph (500 free leads)
    capturify_pixel_id: str = ""          # Capturify pixel ID
    fullcontact_pixel_id: str = ""        # FullContact Acumen webtag ID
    customers_ai_pixel_id: str = ""       # Customers.ai X-Ray pixel ID

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
    twitter_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/twitter"
    twitter_bearer_token: str = ""
    twitter_browser_cookie_path: str = "~/.retarget/twitter_cookies.json"
    twitter_browser_headless: bool = True
    twitter_browser_cookies_b64: str = ""  # Base64-encoded cookies JSON (for Railway/Docker)

    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/facebook"

    instagram_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/instagram"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/linkedin"
    linkedin_browser_cookie_path: str = "~/.retarget/linkedin_cookies.json"
    linkedin_browser_headless: bool = True
    linkedin_browser_cookies_b64: str = ""

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/tiktok"
    tiktok_browser_cookie_path: str = "~/.retarget/tiktok_cookies.json"
    tiktok_browser_headless: bool = True
    tiktok_browser_cookies_b64: str = ""

    # ─── Encryption ───
    encryption_key: str = ""  # Fernet key for BYOK API keys (strict)
    token_encryption_key: str = ""  # Fernet key for OAuth tokens (graceful)

    # ─── Stripe Billing ───
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro_monthly: str = ""       # Stripe Price ID — Pro monthly
    stripe_price_pro_yearly: str = ""        # Stripe Price ID — Pro yearly
    stripe_price_max_monthly: str = ""       # Stripe Price ID — Max monthly
    stripe_price_max_yearly: str = ""        # Stripe Price ID — Max yearly
    stripe_portal_config_id: str = ""        # Optional Stripe Portal Configuration ID

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
