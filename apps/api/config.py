from pydantic_settings import BaseSettings

# Only these app_env values skip production safety checks. ANYTHING else — a
# typo like "prod"/"produciton", or "staging" holding prod data — is treated as
# production-strict, so a fat-fingered APP_ENV can't silently disable the
# encryption-key / secret requirements (and the PII blind index with them).
_KNOWN_NONPROD_ENVS = {"development", "test", "local", "ci"}


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str = "change-me-in-production"

    def validate_production(self) -> None:
        """Fail fast on startup if any critical config is unsafe.

        Runs for production AND any UNRECOGNIZED app_env (so a typo can't bypass
        it). Collects ALL violations and raises a single RuntimeError so the
        operator sees every problem at once rather than one-at-a-time.
        """
        if self.app_env in _KNOWN_NONPROD_ENVS:
            return

        violations: list[str] = []

        if self.app_secret_key == "change-me-in-production":
            violations.append("APP_SECRET_KEY is still the insecure default — set a strong random value")

        if not self.token_encryption_key:
            violations.append("TOKEN_ENCRYPTION_KEY is empty — OAuth tokens cannot be encrypted at rest")

        if not self.encryption_key:
            violations.append(
                "ENCRYPTION_KEY is empty — BYOK API keys + the PII blind index cannot be secured"
            )

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
    # Gate new-account creation to waitlist-approved emails. Default open now
    # that the private beta is over; set INVITE_ONLY=true to re-gate.
    invite_only: bool = False

    # ─── External APIs (EasyTrack) ───
    people_data_labs_api_key: str = ""
    fullcontact_api_key: str = ""  # deprecated — FullContact moved to B2B enterprise
    proxycurl_api_key: str = ""
    anthropic_api_key: str = ""  # legacy — replaced by Gemini (see gemini_api_key)
    gemini_api_key: str = ""  # Google Gemini — deep research (Google Search grounding) + segmentation/campaigns
    gemini_model: str = "gemini-2.5-flash"  # free tier + grounding; 3.x needs billing
    openrouter_api_key: str = ""  # OpenRouter.ai — single key for 100+ models
    default_ai_model: str = "deepseek/deepseek-v4-flash"  # PAID (~$0.00008/reply) — uses OpenRouter credit, avoids free-tier 429. Falls back to :free chain then Gemini.
    resend_api_key: str = ""  # deprecated — use SendGrid
    sendgrid_api_key: str = ""
    sendgrid_webhook_secret: str = ""  # shared secret for the SendGrid event webhook URL

    # ─── Changelog auto-generator (GitHub → Gemini → landing-page "what's new") ───
    github_token: str = ""  # repo-scoped PAT; required for the changelog sync (repo is private)
    github_repo: str = "julleycode/retarget-agent"  # owner/name to pull merged PRs from
    changelog_sync_enabled: bool = False  # master switch for the daily auto-sync job
    changelog_sync_interval_hours: int = 24  # how often the daily job pulls new merged PRs

    # ─── Connection-expiry nudge (email account owners before a social token dies) ───
    connection_nudge_enabled: bool = False  # master switch for the hourly nudge job
    connection_nudge_warn_days: int = 7  # warn when a token expires within this window

    # ─── Identity Graph (person-level from IP) ───
    rb2b_api_key: str = ""          # RB2B API Suite — IP → hashed email → person (US traffic)
    leadpipe_api_key: str = ""      # Leadpipe — pixel-based identity graph (500 free IDs)
    leadpipe_default_pixel_id: str = ""  # Default Leadpipe pixel ID for all sites
    capturify_api_key: str = ""           # Capturify — identity graph (500 free leads)
    capturify_pixel_id: str = ""          # Capturify pixel ID
    fullcontact_pixel_id: str = ""        # FullContact Acumen webtag ID
    customers_ai_pixel_id: str = ""       # Customers.ai X-Ray pixel ID

    # When true, drop ingest events whose client IP belongs to a cloud-compute
    # provider (Azure/AWS/GCP/DO/OVH/…) — server/bot traffic, never real eyeballs.
    # Cached + fail-open: an IPinfo error never blocks a real visitor's events.
    block_datacenter_traffic: bool = True

    # MaxMind GeoLite2-ASN: a FREE, unlimited, offline IP→ASN database. When
    # maxmind_asn_db_path points at a GeoLite2-ASN.mmdb, datacenter detection uses
    # it (sub-ms local lookup, no per-IP IPinfo call) and only falls back to IPinfo
    # when the DB is absent. Download with scripts/download_geolite2_asn.py using a
    # free MaxMind license key (maxmind_license_key / MAXMIND_LICENSE_KEY).
    maxmind_asn_db_path: str = ""
    maxmind_license_key: str = ""

    # ─── Waterfall enrichment providers ───
    ipinfo_token: str = ""          # IP → company/geolocation (50K free/month)
    hunter_api_key: str = ""        # Domain → employee emails (25 free/month)
    apollo_api_key: str = ""        # Contact database + email finder (10K credits free/month)

    # ─── Provider on/off toggles (own-data P3) ───
    # Disable a provider WITHOUT deleting its key. Default on = no behavior change;
    # flip the env var to demote a provider as the owned graph grows. e.g. RB2B
    # keeps charging $0.09/match while returning invalid emails — set
    # RB2B_ENABLED=false to stop it. The resolver checks the flag alongside the key.
    rb2b_enabled: bool = True
    leadpipe_enabled: bool = True
    capturify_enabled: bool = True
    pdl_ip_enabled: bool = True
    ipinfo_enabled: bool = True
    hunter_enabled: bool = True
    apollo_enabled: bool = True

    # Skip PAID enrichment (PDL/Proxycurl/Twitter) for a resolved visitor whose
    # email is already in the customer's uploaded CRM list (known_contacts) — they
    # own that person's data, so enriching them again just burns provider credits.
    # Default on (cost saving); set false to always enrich.
    skip_enrich_known: bool = True

    # When false (default), a captured/owned email is saved as a $0 form_capture
    # identification WITHOUT an extra pre-waterfall PDL person-enrich call — the
    # email is already owned, and the post-resolution enricher (enrich_tier1) still
    # fills job/company data. Set true to enrich captured emails inline at resolve
    # time (spends a PDL credit on data you already have).
    enrich_captured_email_pdl: bool = False

    # Shopify
    shopify_api_key: str = ""
    shopify_api_secret: str = ""

    # ─── CRM Connectors (push identified visitors OUT to a CRM) ───
    # When true, every external connector call returns deterministic fakes
    # instead of hitting the provider — lets us dev/test/demo without real
    # credentials or credit burn (CLAUDE.md "every external API has a mock").
    mock_external_apis: bool = False
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    hubspot_redirect_uri: str = "http://localhost:8000/api/v1/crm/callback/hubspot"
    pipedrive_client_id: str = ""
    pipedrive_client_secret: str = ""
    pipedrive_redirect_uri: str = "http://localhost:8000/api/v1/crm/callback/pipedrive"
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_redirect_uri: str = "http://localhost:8000/api/v1/crm/callback/salesforce"
    # Per-site cap on CRM push operations per clock hour (abuse / runaway guard).
    max_crm_pushes_per_hour_per_site: int = 20
    # Offload large pushes to Celery. OFF by default — only safe when a Celery
    # worker is actually running (prod currently has none). When off, every push
    # runs synchronously in the request.
    crm_async_push: bool = False
    crm_async_push_threshold: int = 200  # segment member count above which async kicks in
    # Auto-push every newly created segment to all connected CRMs. OFF by
    # default — syncing to a customer's CRM unattended is a strong side effect,
    # so operators opt in explicitly.
    crm_auto_push: bool = False
    # Exclude contacts already in the site's known-contacts (CRM) list from CRM
    # pushes — push only net-new leads. Default off: pushing a known contact just
    # upserts (updates) their existing record, which some owners want.
    crm_push_exclude_known: bool = False

    # Supabase Storage (blog image uploads). No service-role key → mock mode.
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "blog-images"

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

    # Instagram can use a SEPARATE Meta app from Facebook. Meta does not allow the
    # Instagram use case and the consumer "Facebook Login" use case in the same app,
    # so Facebook Login typically lives in a consumer app while Instagram lives in a
    # business app. If instagram_app_id/secret are empty they fall back to the
    # facebook_* credentials (legacy single-app setups keep working).
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/instagram"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/api/v1/social/callback/linkedin"
    # LinkedIn versioned REST API month (YYYYMM), sent as the LinkedIn-Version header
    linkedin_api_version: str = "202506"
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
    # HMAC key for the PII blind index (suppression list now; encrypted PII
    # lookups in Phase 05). Falls back to encryption_key when empty so no new
    # mandatory env is required to ship the suppression list.
    pii_hmac_key: str = ""
    # Fernet key for encrypting PII at rest (Phase 05). Falls back to
    # encryption_key (itself a valid Fernet key) when empty.
    pii_encryption_key: str = ""

    # ─── Stripe Billing ───
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro_monthly: str = ""       # Stripe Price ID — Pro monthly
    stripe_price_pro_yearly: str = ""        # Stripe Price ID — Pro yearly
    stripe_price_max_monthly: str = ""       # Stripe Price ID — Max monthly
    stripe_price_max_yearly: str = ""        # Stripe Price ID — Max yearly
    stripe_portal_config_id: str = ""        # Optional Stripe Portal Configuration ID

    # ─── Lemon Squeezy Billing (Merchant of Record — active billing provider) ───
    # Stripe is unavailable in Vietnam; Lemon Squeezy is a MoR that handles
    # global tax and pays out via Wise. The stripe_* vars above are dormant.
    lemonsqueezy_api_key: str = ""           # Settings → API
    lemonsqueezy_store_id: str = ""          # numeric store id
    lemonsqueezy_webhook_secret: str = ""    # webhook signing secret
    ls_variant_pro_monthly: str = ""         # LS variant id — Pro monthly
    ls_variant_pro_yearly: str = ""          # LS variant id — Pro yearly
    ls_variant_max_monthly: str = ""         # LS variant id — Max monthly
    ls_variant_max_yearly: str = ""          # LS variant id — Max yearly

    # ─── Gumroad Billing (fallback MoR — Lemon Squeezy rejected Beam's category) ───
    # Gumroad provides NO webhook HMAC signature, so the Ping is authenticated by
    # a secret token appended to the endpoint URL plus an optional seller_id
    # match. Configure at Gumroad → Settings → Advanced → "Ping endpoint":
    #   https://<api-host>/api/v1/billing/gumroad/webhook?token=<gumroad_webhook_secret>
    gumroad_webhook_secret: str = ""         # secret URL token authenticating the Ping
    gumroad_seller_id: str = ""              # your Gumroad seller_id (optional defense-in-depth)
    gumroad_product_permalink: str = ""      # product permalink, e.g. "rlkwnz" (optional sanity check)

    # ─── Feature flags ───
    sync_interval_minutes: int = 60
    resolution_sweep_interval_minutes: int = 30  # APScheduler identity-resolution sweep cadence
    # Data retention (GDPR data minimization / privacy-policy 90-day promise):
    # raw events older than this are auto-purged. Enriched profiles are kept.
    event_retention_days: int = 90
    retention_purge_interval_hours: int = 24  # daily purge sweep

    # ─── OSINT account scanner (manual per-visitor; free stacked engines) ───
    enable_osint_scan: bool = False             # master gate — off in prod until explicitly enabled
    osint_engines: str = "user-scanner,holehe,maigret"  # comma-separated engines to run (drop one to disable it). "maigret" is a username-stage engine (social_resolver), not an email-scan adapter.
    osint_scan_concurrency: int = 10            # max simultaneous outbound site checks (asyncio.Semaphore)
    osint_scan_per_module_timeout: float = 8.0  # per-site check timeout (seconds)
    osint_scan_wall_clock_cap: float = 45.0     # overall scan budget; partial results returned past this
    osint_scan_skip_categories: str = "adult,nsfw,porn"  # category names to skip (NSFW)
    osint_scan_daily_budget: int = 5            # free scans/day/site (BYOK = unlimited)
    # Maigret (username→profile, stage B)
    osint_maigret_top_sites: int = 500          # check top-N ranked sites (3000 total)
    osint_maigret_parse: bool = True            # fetch+parse hit pages (real name/bio, fewer soft-404s; slower)
    # GHunt (Gmail dossier, stage D — opt-in; disabled until cookies provided)
    ghunt_cookies_b64: str = ""                 # base64 GHunt creds.json; empty = stage D off
    # Paid fallback (OSINT Industries, stage F — auto when free+AI come up empty)
    osint_industries_api_key: str = ""          # system key; empty = paid fallback off
    osint_paid_min_profiles: int = 1            # run paid only if free+AI found fewer than this
    osint_paid_daily_budget: int = 10           # hard cap on paid lookups/day/site (credit guard)

    # ─── Content reader (read public YouTube + Reddit content for persona /
    # campaign personalization; behind a flag, default OFF) ───
    enable_content_reader: bool = False          # master gate — off until explicitly enabled
    content_reader_max_items: int = 5            # number of recent videos/posts to keep per source

    # ─── phantommm sidecar (LinkedIn outreach automation) ───
    # Beam NEVER talks to LinkedIn directly and NEVER stores the raw LinkedIn
    # session cookie. The cookie lives encrypted inside the phantommm sidecar;
    # Beam only holds an opaque connection_id reference. Both must be set for the
    # LinkedIn-outreach endpoints to work (else they return HTTP 503, mirroring
    # the Lemon Squeezy "not configured" pattern). PHANTOMMM_API_KEY must match
    # phantommm's own API_KEY — it's sent as the `x-api-key` header on every call.
    phantommm_base_url: str | None = None
    phantommm_api_key: str | None = None

    # ─── Twitter/X enrichment fallback ───
    # TwitterAPI.io — cheap third-party X data provider used as a FALLBACK when
    # the official X API v2 call errors / returns non-200 / no bearer token.
    # Gated: empty key = fallback disabled. See enricher._enrich_twitter.
    twitterapi_io_api_key: str = ""

    # ─── Rate limits ───
    default_daily_resolution_budget: int = 50   # Free tier: 50 visitor identifications/day per site (BYOK = unlimited)
    default_daily_enrichment_budget: int = 3    # Free tier: 3 deep research/day (BYOK = unlimited)
    max_emails_per_hour_per_site: int = 50

    model_config = {"env_file": ("../../.env", ".env"), "extra": "ignore"}


settings = Settings()
