from pydantic import field_validator
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
    database_url: str = "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent"

    # ─── DB pool + timeout hardening (capacity-hardening plan Phase 4a/4b / W4) ───
    # 4a — SERVER-SIDE statement timeout, applied via asyncpg `server_settings`
    # (so Postgres itself kills the query; a client-side cancel would still leave
    # the backend running). 0 = DISABLED = today's exact behavior, so this ships
    # inert; flipping it on is an explicit operator action.
    # Ordering matters: this must only be raised above 0 AFTER Phase 3's bounded
    # aggregation queries exist. Setting it earlier would convert the (slow,
    # correct) full-history recompute into an error path. Suggested first live
    # value once Phase 3 has soaked: 30_000 ms. NOTE the full-recompute repair
    # sweep (_aggregation_sweep_job) still runs an unbounded query by design —
    # size any non-zero value against THAT query, not against request-path SQL.
    db_statement_timeout_ms: int = 0
    # 4b — pool sizing. Defaults reproduce the previous hardcoded 3/2 (=5 per
    # container) exactly, which is correct for the Supabase SESSION pooler
    # (port 5432, 15-client cap) with one deploy overlap (old+new = 10 peak).
    #
    # Pool math (keep this satisfied before raising either value):
    #   containers x (db_pool_size + db_max_overflow)
    #     + celery_workers x (worker_pool_size + worker_overflow)
    #     <= client_cap,      with headroom for ONE deploy overlap.
    # Also reserve 2 connections for `services/retention.py`, which holds an
    # outer advisory-lock session plus an inner delete session for the whole
    # purge (retention.py:116/122 and :177/183).
    #
    # OPERATOR MIGRATION (not a code change): moving DATABASE_URL to the
    # Supabase TRANSACTION pooler on port 6543 lifts the client cap and is what
    # actually unlocks larger pools. It also FORBIDS session-scoped state —
    # advisory locks held across statements, SET-based session settings. This
    # repo holds advisory locks across statements in retention.py, so the port
    # change is NOT recommended until that audit closes. See
    # process/general-plans/active/capacity-hardening_25-07-26/
    # transaction-pooler-advisory-lock-audit_NOTE_25-07-26.md
    # The pool code below is port-aware and safe under EITHER pooler; only the
    # defaults differ, and the non-5432 default is deliberately identical to the
    # 5432 one until an operator raises it.
    db_pool_size: int = 3
    db_max_overflow: int = 2

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
    # Is a Celery WORKER actually deployed and consuming the broker? OFF by
    # default. No worker process exists in this repo (Dockerfile CMD is
    # alembic+uvicorn; railway.json declares one service), so queueing a task
    # would drop it silently. Every `.delay()` call site ANDs this flag with its
    # own per-surface `*_async_push` flag, so the default keeps today's exact
    # behavior: the async branch is never entered and the work runs inline.
    # Flipping this to True is an explicit operator action, valid only once a
    # worker service is live (see capacity-hardening plan Phase 1(a)).
    celery_worker_enabled: bool = False

    # ─── Aggregation cost control (capacity-hardening plan Phase 3 / W1) ───
    # OFF = today's exact behavior: every ingest batch triggers a FULL-history
    # recompute per site, totals SET (not incremented) on conflict, which is
    # idempotent but superlinear under a traffic spike.
    # ON = watermark-incremental path: only events newer than the site's
    # last_aggregated_at are merged (with a 30-minute LAG lookback so session
    # boundaries stay correct at the window edge). Only the mergeable columns are
    # written incrementally; avg_time_on_page and intent_score are DESCOPED (D7)
    # and refreshed exclusively by the APScheduler full-recompute repair sweep
    # (aggregation_sweep_interval_minutes, default 60 = the staleness bound).
    # Flipping this to True is an explicit operator action.
    aggregation_incremental_enabled: bool = False
    # Per-site debounce TTL for the cross-container Redis key agg:debounce:{site_id}.
    # Replaces the per-process in-memory _aggregating set, which cannot dedup N
    # containers. Also the TTL that bounds the sweep's end-of-pass retry (E16c).
    aggregation_min_interval_seconds: int = 60
    # Rows per bulk-upsert chunk on the incremental path (one round-trip per
    # chunk instead of one per visitor — shortens the row-lock window).
    aggregation_upsert_chunk_size: int = 500

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

    # ─── Gemini JSON self-correction + tool loop (see services/gemini_client.py) ───
    # Retry-with-feedback when a JSON response fails to parse/validate
    # (segmentation, campaign planning). 2 repairs = max 3 model calls.
    gemini_json_repair_attempts: int = 2
    gemini_tool_loop_max_iterations: int = 5      # hard cap on model calls per loop
    gemini_tool_loop_token_budget: int = 60000    # cumulative totalTokenCount across loop calls
    gemini_tool_loop_timeout_s: float = 60.0      # wall clock; past this the next call is forced final
    gemini_tool_output_max_chars: int = 8000      # per-tool-result serialization cap
    ai_ask_tools_enabled: bool = True             # /ai/ask agentic path (falls back to single-shot on error/off)
    campaign_planner_tools_enabled: bool = False  # planner fetches recent_content/accounts via tools (opt-in)
    openrouter_api_key: str = ""  # OpenRouter.ai — single key for 100+ models
    default_ai_model: str = "deepseek/deepseek-v4-flash"  # PAID (~$0.00008/reply) — uses OpenRouter credit, avoids free-tier 429. Falls back to :free chain then Gemini.
    resend_api_key: str = ""  # deprecated — use SendGrid
    sendgrid_api_key: str = ""
    sendgrid_webhook_secret: str = ""  # shared secret for the SendGrid event webhook URL
    # Shared secret for the Leadpipe identity webhook URL. Same query-token shape
    # as SendGrid above, because the Leadpipe dashboard's webhook form takes only
    # a URL (no signing secret / custom header field). Empty = endpoint disabled
    # (403), so it can never become an open identity-injection vector.
    leadpipe_webhook_secret: str = ""

    # ─── Changelog auto-generator (GitHub → Gemini → landing-page "what's new") ───
    github_token: str = ""  # repo-scoped PAT; required for the changelog sync (repo is private)
    github_repo: str = "julleycode/retarget-agent"  # owner/name to pull merged PRs from
    changelog_sync_enabled: bool = False  # master switch for the daily auto-sync job
    changelog_sync_interval_hours: int = 24  # how often the daily job pulls new merged PRs

    # ─── Connection-expiry nudge (email account owners before a social token dies) ───
    connection_nudge_enabled: bool = False  # master switch for the hourly nudge job
    connection_nudge_warn_days: int = 7  # warn when a token expires within this window

    # ─── Weekly outcomes digest ("Beam this week: X sent, Y clicks, Z conversions") ───
    outcomes_digest_enabled: bool = False  # master switch for the Monday digest email job

    # ─── Daily activity digest (owner-only: today's actions + identified/enriched detail) ───
    # Distinct from outcomes_digest_enabled above: that one is the WEEKLY,
    # forward-safe proof email (no contact details). This one is the DAILY
    # working report and DOES contain visitor PII, so it goes to the site owner
    # only and is never framed as shareable.
    daily_digest_enabled: bool = False  # master switch for the daily digest job
    daily_digest_hour_utc: int = 13  # cron hour (UTC) — ~08:00 US Eastern
    daily_digest_max_visitors: int = 25  # detail rows per email before "see all" link

    # ─── Referral program ("give quota, get quota") ───
    referrals_enabled: bool = False  # master switch for the hourly activation-reward job

    # ─── Identity Graph (person-level from IP) ───
    rb2b_api_key: str = ""          # RB2B API Suite — IP → hashed email → person (US traffic)
    leadpipe_api_key: str = ""      # Leadpipe — pixel-based identity graph (500 free IDs)
    # NOTE: there is deliberately no `leadpipe_default_pixel_id` here anymore.
    # A Leadpipe pixel is bound 1-1 to a domain (POST /v1/data/pixels answers
    # 409 on a duplicate), so one shared id served to every site loaded on all
    # of them and collected on none. Each site now carries its own
    # `Site.leadpipe_pixel_id`, provisioned by services/leadpipe_pixels.py.
    capturify_api_key: str = ""           # Capturify — identity graph (500 free leads)
    capturify_pixel_id: str = ""          # Capturify pixel ID
    fullcontact_pixel_id: str = ""        # FullContact Acumen webtag ID
    customers_ai_pixel_id: str = ""       # Customers.ai X-Ray pixel ID

    # ─── Ingest abuse hardening (P1–P5) ───
    # Hard ceiling on the POST /ingest request body, enforced as a running byte
    # count during ASGI receive() (NOT a Content-Length-only check — that header
    # is forgeable and absent on chunked transfer-encoding). 256 KB is generous:
    # a realistic 100-event batch is well under this, so no legitimate pixel
    # payload is ever rejected.
    ingest_body_max_bytes: int = 262_144

    # How many TRUSTED reverse proxies / load balancers sit in front of the app.
    # 0 (default) = trust nothing: X-Forwarded-For is ignored entirely and the
    # client IP is request.client.host, which a caller cannot forge. N >= 1 =
    # take the Nth-from-the-right XFF entry (the value the Nth trusted hop
    # observed). Misconfiguration ALWAYS fails safe back to request.client.host —
    # see services/ip_resolution.resolve_client_ip.
    #
    # SPOOFING TRADEOFF (read before changing this value). Trusting N hops means
    # the caller can forge every XFF entry to the LEFT of the trusted ones —
    # resolve_client_ip takes the Nth-from-the-RIGHT entry precisely so that the
    # forgeable prefix is discarded. Therefore N must equal EXACTLY the number of
    # reverse proxies Beam actually controls:
    #   N too HIGH -> a caller injects entries and mints an arbitrary limiter key
    #                 per request, evading the per-IP limit entirely.
    #   N too LOW  -> every visitor behind the proxy shares one bucket (collapse),
    #                 and real traffic gets mass-429'd.
    # A chain shorter than N fails safe back to request.client.host, so a wrong
    # HIGH value degrades to collapse rather than to a crash — but it is still a
    # rate-limiter bypass and must not be guessed.
    #
    # WHY THIS IS STILL 0 (Phase 2, capacity-hardening plan 25-07-26). The
    # expected Railway topology is one edge proxy (N = 1), but the collapse is
    # UNVERIFIED live and the real hop count cannot be derived from this repo.
    # The plan forbids flipping it blind. The default therefore stays at today's
    # safe value until the Phase 0 P0.1 diagnostic (routers/events.py,
    # "ingest_client_key") has been observed over >=100 real ingests and distinct
    # key_hash counts are compared against distinct visitor_id counts. Raising
    # this value is then an explicit operator action, set to the OBSERVED hop
    # count and never higher.
    trusted_proxy_hops: int = 0

    # Prefer Cloudflare's CF-Connecting-IP header for the ingest client IP.
    # api.getbeam.fyi is permanently CF-proxied, so the direct peer (and any
    # trusted-hop XFF walk) sees CF edge IPs — useless for identity resolution.
    # CF-Connecting-IP always carries the real client. Trade-off vs the P2
    # hop-count design: a caller that reaches the Railway origin DIRECTLY
    # (bypassing CF) can forge this header — acceptable until the origin is
    # locked to CF IP ranges (backlogged). Set false to fall back to the pure
    # trusted_proxy_hops behavior.
    ingest_trust_cf_connecting_ip: bool = True

    # Per-SITE ingest ceiling. The existing 100/min per-IP limiter is blind to a
    # rotating-IP flood: spread across 500 IPs, every bucket stays under its
    # allowance while one site absorbs the whole aggregate. This ceiling is the
    # only layer that sees that total. Defaults OFF (same precedent as
    # agent_detection_enabled / company_graph_enabled) — turning it on in a real
    # environment is a deliberate operator action after the thresholds are tuned.
    #
    # ROLLOUT ORDER (Phase 2, capacity-hardening plan 25-07-26). This ceiling and
    # ingest_velocity_enabled below were both designed to COMPENSATE for a blind
    # per-IP limiter. Enabling either before trusted_proxy_hops is correct would
    # tune them against collapsed traffic and bake in the wrong thresholds.
    # Required order:
    #   1. trusted_proxy_hops set to the P0.1-observed value (per-IP keying correct)
    #   2. THEN site_ingest_limit_enabled, after ~1 week of real per-site volume;
    #      set site_ingest_limit_per_minute to ~5x the OBSERVED per-site p99/min,
    #      never to the audit's 3000 placeholder below.
    #   3. THEN ingest_velocity_enabled, last (see its own note).
    site_ingest_limit_enabled: bool = False
    # Only consulted when site_ingest_limit_enabled is True.
    site_ingest_limit_per_minute: int = 3000

    # Write-time behavioural velocity detection. A rotating-IP flood has HIGH IP
    # entropy by construction, so IP entropy alone is worthless against it. The
    # signal that DOES separate a flood from real traffic is identity diversity:
    # a flood mints many distinct visitor_ids that share very few distinct browser
    # fingerprints. Flag only when BOTH hold — high distinct-visitor count AND low
    # fingerprint diversity — so an organic viral spike (many visitors, many real
    # fingerprints) is never caught. Defaults OFF, same precedent as above.
    #
    # ROLLOUT ORDER: enable LAST — step 3 of the sequence documented on
    # site_ingest_limit_enabled above. This is the rotating-IP-flood detector;
    # once per-IP keying is correct it becomes a SECOND layer of defence rather
    # than the primary one, so its thresholds should be calibrated against
    # already-correct per-IP data.
    ingest_velocity_enabled: bool = False
    ingest_velocity_window_seconds: int = 60
    # Distinct visitor_ids per site per window before the shape starts to look
    # like a flood at all. Calibration value — operator-tunable.
    ingest_velocity_visitor_threshold: int = 200
    # distinct_fingerprints / distinct_visitors ratio below which the traffic
    # looks like "one attacker, many fake identities" rather than "many humans".
    ingest_velocity_min_fingerprint_diversity: float = 0.3

    # When true, drop events whose page URL host is a loopback/dev host
    # (localhost, 127.x, ::1, 0.0.0.0, *.localhost) — dev environments loading a
    # prod snippet produce noise visitors; disable in test harnesses that
    # legitimately post localhost URLs.
    ingest_drop_local_urls: bool = True

    # When true, drop ingest events whose client IP belongs to a cloud-compute
    # provider (Azure/AWS/GCP/DO/OVH/…) — server/bot traffic, never real eyeballs.
    # Cached + fail-open: an IPinfo error never blocks a real visitor's events.
    block_datacenter_traffic: bool = True

    # When true, also drop ingest events whose client IP is flagged by IPinfo's
    # Privacy Detection as proxy / VPN / Tor / hosting — the "no-PTR proxy" traffic
    # (Sprious-style scrapers, commercial proxies, VPN egress) that hides behind a
    # real-looking UA and a datacenter ASN the org-token net misses. `relay` is
    # deliberately NOT a drop signal (Apple Private Relay / Cloudflare WARP front
    # real humans). Needs ipinfo_token; cached 7d + fail-open, so a lookup error
    # never blocks a real visitor.
    block_proxy_vpn_traffic: bool = True

    # When true, recognized AI-agent traffic (OpenAI/Anthropic/Perplexity/
    # ByteSpider UAs, per agent_classifier.classify_agent) is classified and
    # persisted to the agent_visits rollup table instead of being silently
    # dropped by is_bot(). Gates BOTH classification and persistence on the
    # ingest hot path. Defaults OFF until the agent_visits migration is confirmed
    # applied in prod — with the flag off, ingest behavior is byte-identical to
    # pre-EvalLayer (recognized agent UAs fall through to the is_bot() drop).
    agent_detection_enabled: bool = False

    # ─── Job-change detection (v1, same-tenant) ───
    # Detects that an ALREADY-IDENTIFIED visitor's company changed, by re-checking
    # them against this site's OWN stored EnrichmentProfile baseline. Gates the
    # whole pipeline: the event-driven Trigger A dispatch, the scheduled Trigger B
    # sweep, and job_change_detector.run_recheck itself (the service re-checks the
    # flag independently of its callers, same belt-and-suspenders posture as
    # agent_detection_enabled).
    #
    # Defaults OFF. Flipping this in a real environment is an explicit operator
    # action AFTER the job_change_events migration (a4f2b8c15d70) is confirmed
    # live-applied — with the flag off, zero rechecks fire, zero provider credits
    # are spent, and zero rows are written.
    job_change_detection_enabled: bool = False

    # Daily per-site ceiling on re-checks (Redis counter, NOT the DB-row-count
    # Site.daily_resolution_budget — the two are deliberately different stores so
    # neither can influence the other). PLACEHOLDER value: tune from observed
    # per-site resolution-budget sizing before enabling live, same posture as
    # site_ingest_limit_per_minute. Every re-check costs a paid provider call, so
    # this is a real spend cap, not just a throttle.
    job_change_recheck_daily_cap: int = 200

    # How stale an EnrichmentProfile must be before the Trigger B sweep will
    # re-check it. Deliberately the same number as company_graph_staleness_days,
    # not independently re-derived: both answer "how stale is too stale to trust a
    # cached professional-data snapshot".
    job_change_staleness_days: int = 75

    # Corroboration gate threshold. A detected company difference is only recorded
    # when confidence >= this AND at least one independent corroborating signal is
    # present (work-email domain or company_graph IP attribution). The confidence
    # constants themselves live in services/job_change_detector.py and are an
    # UNCALIBRATED heuristic — see the plan's Known-Gap #2.
    job_change_min_confidence: float = 0.5

    # ─── Candidate outreach (identity-vocab-reconcile D5/D10) ───
    # Gates the D2 WIDENING only: whether a graph-candidate identity
    # (rb2b/leadpipe/capturify/beam_identity_network) that is still
    # identity_status == "candidate" — an UNCONFIRMED graph guess — may be an
    # outreach target.
    #
    # OFF (default): unconfirmed candidates are held back at the 3 outreach call
    # sites (campaign send, CSV export, LinkedIn target resolution). A candidate a
    # human has explicitly CONFIRMED (identity_status == "identified", via the
    # confirm-candidate endpoint) is emailable regardless of this flag — that is
    # the entire point of the confirm workflow, not a bypass.
    # ON: the full D2 rule — any person-level identity is emailable, restrained
    # only by the personalization gate (generic copy for unconfirmed candidates).
    #
    # is_emailable_identity() is NOT parameterized by this flag; the check is a
    # wrapper at the call sites (hot_alert.py and outcome_digest.py are
    # deliberately excluded — they gate what the SITE OWNER sees, not outreach to
    # the candidate). Turning this on is a separate deliberate operator action,
    # same posture as agent_detection_enabled / company_graph_enabled.
    candidate_outreach_enabled: bool = False

    # ─── Identity co-op (Phase 1) ───
    # Turns the implicit cross-tenant identity graph into an opt-in data co-op:
    # a site that contributes successful graph writes accrues spendable credits.
    # Read access to the graph is UNCONDITIONAL and is never gated on any of these.
    #
    # REQUIRED ROLLOUT ORDER — do not reorder:
    #   1. cross-tenant erasure LIVE (graph-erasure-compliance) — already shipped;
    #      the co-op must never be able to create a new record of an erased person.
    #   2. the two Phase 1 migrations live-applied in the target environment.
    #   3. legal review of the contribution terms text, and coop_terms_version
    #      re-pinned to the digest of the REVIEWED text.
    #   4. identity_coop_enabled -> True.
    #   5. per-site contribution_enabled -> True, only via the API's acceptance
    #      guard (never by direct SQL — that would skip the AC-10 audit row).
    # Never flip step 4 or 5 before step 3. Same operator-gated posture as
    # agent_detection_enabled / company_graph_enabled / identity_signals_enabled.
    identity_coop_enabled: bool = False
    coop_credit_per_contribution: int = 1
    coop_credit_expiry_days: int = 90
    coop_credit_hold_hours: int = 24
    # Immutable snapshot hash (64-char lowercase hex) of the exact contribution
    # terms text, NOT a free-form label: routers/sites.py rejects 422 unless the
    # submitted terms_version equals this value, so an acceptance row can only
    # ever record terms that actually existed. Re-pin this whenever the policy
    # text changes; Phase 3's coop_terms.py replaces this constant compare with a
    # multi-version history and supersedes it.
    # Current value = sha256("Beam Identity Co-op Contribution Terms v1 (2026-08-07)").
    coop_terms_version: str = (
        "c655274f585ef9b515688e9d4572f7cd64b8ed2fed8ebe6602e0040ecf73d7eb"
    )

    # ─── Agent gateway (agent-gateway Phase 1+2) ───
    # When true, the public per-site agent-facing read surface is served:
    # GET /api/v1/agent/{site_id}/manifest.json | /offers.json | /llms.txt and
    # the read-only JSON-RPC MCP endpoint. Content is customer-authored
    # (AgentProfile) — no PII, no visitor data, no operational fields.
    #
    # TWO gates, both required: this global flag AND the per-site
    # AgentProfile.enabled. Either off => 404, endpoint not revealed (same
    # dormant-not-revealed posture as agent_fetch_beacon_enabled). An unknown or
    # foreign site_id is likewise 404, NEVER 403 — never leak which site_ids exist.
    #
    # Defaults OFF until the agent_profiles migration (a4f7c2e9d31b) is
    # live-applied in prod; flipping it on in a real environment is an explicit
    # operator action, matching agent_detection_enabled / company_graph_enabled.
    agent_gateway_enabled: bool = False

    # ─── Agent link marker (Handoff Detection F2) ───
    # When true, offers.json stamps each same-host offer URL with an opaque
    # per-fetch marker, so a human arriving on that link is tied to the exact
    # agent fetch that surfaced it — replacing the 30-minute temporal guess with
    # a deterministic match.
    #
    # Turning this on CHANGES THE CACHE POSTURE of offers.json: the response goes
    # private/no-store, because a marker is per-fetch and a shared cache would
    # hand one agent's marker to every later agent — attributing the human to the
    # wrong fetch, which is worse than the guess it replaces. manifest.json and
    # llms.txt are untouched and keep AGENT_CACHE_CONTROL; they carry no marker.
    #
    # Defaults OFF, matching agent_detection_enabled / agent_gateway_enabled.
    # Requires no migration: the marker is self-describing, and the deterministic
    # link lands in the existing agent_handoff_links table.
    agent_marker_enabled: bool = False

    # ─── Cadence bot flag ───
    # Fifth, ORTHOGONAL bot layer. The four existing ones (tracker.js webdriver
    # check, bot_filter UA regex, agent_classifier vendor list, ingest_velocity
    # flood shape) all reason about identity strings or short-window traffic
    # shape. A polite, low-volume daily crawl with a convincing UA sails past all
    # four. This layer looks at BEHAVIOR OVER TIME instead: is the visit schedule
    # cron-like (low coefficient of variation on inter-visit gaps) AND does the
    # visitor never do anything a script would not bother faking (near-zero
    # engagement-event ratio)? Only the CONJUNCTION flags.
    #
    # VISIBILITY-ONLY. is_bot_suspect never sets is_abuse_flagged or
    # do_not_resolve, is never read by is_emailable_identity(), and is never
    # added to any aggregate FILTER exclusion. A real, wanted contact who also
    # runs a bot stays exactly as emailable and exactly as counted — the only
    # new thing is a dashboard badge.
    #
    # Defaults OFF (same operator-gated posture as agent_detection_enabled /
    # site_ingest_limit_enabled). ROLLOUT ORDER: the migration adding
    # visitors.is_bot_suspect / identified_visitors.is_bot_suspect must be
    # LIVE-APPLIED first; then tune the two thresholds below against real event
    # history samples; only then flip this flag in a real environment.
    cadence_bot_flag_enabled: bool = False

    # How often the batch sweep runs. Mirrors aggregation_sweep_interval_minutes.
    # Detection is batch-only by design (AC-4) — nothing here ever runs on the
    # POST /ingest hot path.
    cadence_bot_flag_sweep_interval_minutes: int = 60

    # NON-NEGOTIABLE bounded-read cap. Without it, a visitor with years of
    # history would force an unbounded events scan on every sweep tick — a
    # self-inflicted DoS that grows with the table. Every sweep query carries
    # `events.created_at >= now() - cadence_bot_flag_lookback_days`.
    cadence_bot_flag_lookback_days: int = 90

    # Minimum distinct visit-day floor, evaluated BEFORE any variance math
    # (precondition-before-ratio, same shape as ingest_velocity_visitor_threshold).
    # Below this floor the decision is False unconditionally: too little data to
    # judge a cadence, and a 2-visit "perfectly regular" series is noise.
    cadence_bot_flag_min_visits: int = 5

    # Coefficient-of-variation ceiling below which a visit schedule counts as
    # "cron-like". Operator-tunable so the detection module carries no magic
    # number. Tune against real samples before enabling.
    cadence_bot_flag_max_variance_threshold: float = 0.15

    # Engagement-ratio ceiling below which a visitor's sessions count as
    # "pageview-only" (no click/scroll/time_on_page/conversion). Operator-tunable.
    cadence_bot_flag_max_engagement_ratio: float = 0.05

    # ─── WS2 agent-driven session classifier ───
    # Labels human-SHAPED but agent-OPERATED sessions (Comet, Claude-in-Chrome,
    # Playwright/CDP) via ws2_session_classifier.py + ws2_session_classifier_sweep.py.
    #
    # VISIBILITY-ONLY: is_agent_operated is NEVER read by is_emailable_identity(),
    # never sets is_abuse_flagged/do_not_resolve, never excluded from any aggregate
    # FILTER, never enters a render/redirect/blocking path. A labeled visitor stays
    # fully emailable and fully counted — the flag is a dashboard badge, nothing more.
    #
    # OFF-by-default, same operator-gated posture as cadence_bot_flag_enabled and
    # agent_detection_enabled. ROLLOUT ORDER: (1) LIVE-APPLY both migrations first
    # (b8e3f6a2c904 events.agent_sig, then c9f4a7b31e85 visitors.is_agent_operated);
    # (2) let real agent_sig samples accumulate and calibrate the placeholder
    # thresholds below against them — they are conservative placeholders, never ship
    # them live untuned; (3) only then flip this flag in a real environment.
    #
    # KNOWN LIMITATION (not a bug): this is a periodic sweep, so it flags a session
    # AFTER identity resolution has already fired for it. Visibility-only keeps a
    # flagged visitor out of nothing — it prevents outreach-pool confusion, it does
    # NOT recover the identity-resolution budget already spent. A resolution-time
    # gate on the Stage-1 signals is a separate, unscoped future workstream.
    ws2_classifier_enabled: bool = False

    # How often the batch sweep runs. Batch-only by design: nothing here ever runs
    # on the POST /ingest hot path. Independent interval from the cadence sweep —
    # the two features' tuning cadences differ.
    ws2_classifier_sweep_interval_minutes: int = 60

    # NON-NEGOTIABLE bounded-read cap, same rationale as
    # cadence_bot_flag_lookback_days: every sweep query carries
    # `events.created_at >= now() - ws2_classifier_lookback_days`.
    ws2_classifier_lookback_days: int = 90

    # Minimum click floor per session, evaluated BEFORE any ratio math
    # (precondition-before-ratio). Below this the decision is False
    # unconditionally: too few clicks to judge a dead-centre rate.
    ws2_classifier_min_clicks: int = 5

    # Pointer-entropy CEILING below which movement counts as "robotic". Normalized
    # 0..1. The pixel currently reports a coarse PROXY (0 = no pointermove seen
    # before first interaction, 1 = real movement occurred), so any threshold in
    # [0, 1) behaves identically today; the setting stays a float so a finer-grained
    # entropy signal can replace the proxy without a config change.
    ws2_classifier_max_pointer_entropy: float = 0.15

    # Dead-centre-click-rate FLOOR above which clicking counts as synthetic.
    # Operator-tunable. Placeholder — calibrate before enabling.
    ws2_classifier_min_dead_center_rate: float = 0.6

    # ─── Outlier / internal-traffic damping ───
    # Damps the influence of statistical-outlier visitors (measured live
    # 27-07-26: 3 of 4 sites draw 89-95% of their 90-day events from <20
    # visitors, and those visitors eat the identity-resolution budget because
    # resolution_runner orders by intent_score desc).
    #
    # NOT A GLOBAL FLAG. The on/off switch is PER SITE:
    # Site.internal_damping_enabled, default False. The settings below are only
    # the operator-tunable knobs; with no site opted in, the sweep is a no-op.
    #
    # ROLLOUT ORDER: (1) live-apply the migration adding
    # visitors.is_internal_suspect / visitors.internal_override /
    # identified_visitors.is_internal_suspect / sites.internal_damping_enabled;
    # (2) tune the two thresholds below against that site's REAL per-visitor
    # event-count distribution — the defaults are conservative placeholders, not
    # calibrated values, and must never be shipped live untuned;
    # (3) only then flip internal_damping_enabled on for one site and compare
    # before/after. Never enable across all sites at once.
    #
    # SUGGESTION-ONLY. is_internal_suspect is a LABEL — a "review these" surface
    # and a badge. It never by itself excludes a visitor from the daily digest
    # aggregate and never by itself deprioritises them in resolution_runner.
    # ONLY an explicit human confirmation (internal_override == "internal")
    # does either. Calibrated live 27-07-26 against the real per-visitor
    # distribution:
    #     >=20x  median & >=3 days -> 34 flagged, 5 already identified w/ email
    #     >=50x  median & >=3 days -> 21 flagged, 3 already identified w/ email
    #     >=100x median & >=5 days -> 15 flagged, 2 already identified w/ email
    # There are only 28 identified visitors in the entire system, so automatic
    # exclusion at 20x would have silently hidden ~18% of every customer's real
    # leads. No statistical threshold separates "owner who browses 30k times"
    # from "extremely engaged prospect" — both are high-volume, multi-day, fully
    # engaged — and the error types are wildly asymmetric. Hence: the machine
    # suggests, the human decides.
    #
    # REVERSIBILITY: unlike the cadence/abuse flags above, is_internal_suspect is
    # NOT sticky and a human's internal_override always wins over the sweep, in
    # both directions. A false positive here would silently hide a real prospect,
    # so it must always be clearable.
    outlier_traffic_damping_sweep_interval_minutes: int = 60

    # NON-NEGOTIABLE bounded-read cap, same rationale as
    # cadence_bot_flag_lookback_days: every sweep query carries
    # `events.created_at >= now() - outlier_traffic_damping_lookback_days`.
    outlier_traffic_damping_lookback_days: int = 90

    # Minimum distinct visit-DAY floor per visitor, evaluated before any ratio
    # math. A single-day burst of 2,000 events is a load test or a one-off
    # scrape, not the sustained pattern of someone who works on the site daily.
    # 3 days is the calibrated value (see the 50x/3d row in the table above).
    outlier_traffic_damping_min_visit_days: int = 3

    # Minimum number of visitors a site must have before ANY of its visitors can
    # be judged an outlier — you cannot be an outlier against a distribution of
    # three. Mirrors the sample-size-precondition-first shape used throughout.
    outlier_traffic_damping_min_site_visitors: int = 20

    # How many times the site's OWN median per-visitor event count a visitor must
    # exceed. Site-relative and scale-free by construction, so this one number
    # works for a 29-visitor site and a 532-visitor site alike. 50x is the
    # CALIBRATED value (measured live 27-07-26): it produces a suggestion list a
    # customer can review in about a minute (21 visitors across all sites) rather
    # than the 34 that 20x produced. Because the flag is suggestion-only, this
    # number sizes a review queue — it never silently hides anyone.
    outlier_traffic_damping_outlier_threshold: float = 50.0

    # Engagement-ratio FLOOR — note the INVERSE polarity vs
    # cadence_bot_flag_max_engagement_ratio's ceiling above. A heavy HUMAN
    # scrolls, clicks and dwells; a heavy SCRAPER does not. Requiring engagement
    # to be PRESENT is what keeps crawlers out of this flag (they belong to the
    # cadence/bot layer instead). Operator-tunable; tune before enabling.
    outlier_traffic_damping_min_engagement_ratio: float = 0.1

    # ─── Click→verified promotion sweep (identity-honesty Phase 5) ───
    # When an imported contact clicks their tokenized link, the pixel writes a
    # `visitor_emails` row with source="utm". This batch sweep promotes that
    # visitor to a verified identity within <=5 minutes by re-running the
    # resolver's existing deterministic email path — AFTER the /ingest request
    # completes, never synchronously inside it (locked SPEC constraint).
    #
    # DEFAULT OFF, matching every other recent identity/traffic sweep in this
    # file (cadence_bot_flag_enabled, agent_detection_enabled,
    # identity_signals_enabled, site_ingest_limit_enabled): identity-status
    # mutation is a high-risk class, so enabling it is an explicit operator act.
    promotion_sweep_enabled: bool = False

    # Sweep cadence. 1-2 minutes keeps click→verified comfortably inside the
    # 5-minute SLA. The sweep is cheap: it only touches visitors that just had a
    # `visitor_emails` row written, and the resolver short-circuits on the free
    # prior-signal path before any paid provider is reached.
    promotion_sweep_interval_minutes: int = 2

    # ABSOLUTE lookback floor in minutes, independent of cadence. The window is
    # max(2 * cadence, this) — a bare "2x cadence" would be only 2-4 minutes and
    # would NOT survive a routine deploy restart, silently aging rows out of
    # scope. Residual (documented, not eliminated): the query is time-bound, not
    # state-bound, so a sustained outage LONGER than the window still drops rows;
    # the affected visitor is then only promoted if they click again.
    promotion_sweep_window_floor_minutes: int = 15

    # ─── Cross-tenant identity-graph erasure (graph-erasure-compliance) ───
    # DELIBERATE DEVIATION FROM PRECEDENT: this sweep ships default ON, unlike
    # agent_detection_enabled / site_ingest_limit_enabled / cadence_bot_flag_
    # enabled / promotion_sweep_enabled, which all default OFF. Those flags gate
    # NEW risky behaviour. This one gates the REMOVAL of data Beam has promised
    # to delete: defaulting it OFF would ship a compliance fix that does nothing
    # and would silently retain data after an erasure was accepted and reported
    # complete. The flag exists as an OPERATOR KILL-SWITCH, not a rollout gate —
    # flip it to false to stop the only destructive actor in this feature, which
    # has no restart-unsafe state.
    #
    # The producer (enqueue) and the write-boundary guard carry no flag at all:
    # the enqueue is try/except-wrapped so a missing table cannot break the
    # tenant-facing delete, and the guard is a refusal to write, which fails
    # closed and cannot break a non-suppressed visitor.
    graph_erasure_sweep_enabled: bool = True
    graph_erasure_sweep_interval_minutes: int = 5
    # Attempts before a request is parked at status='failed'. A failed row is
    # NOT a backlog item: the data subject's request is unfulfilled, so
    # failed_count > 0 raises the queue-health log to warning.
    graph_erasure_max_attempts: int = 5
    # How long a row may sit at status='processing' before the sweep reclaims it
    # as pending (crash recovery). Only meaningful because the claim commits in
    # its own transaction, separate from the destructive work.
    graph_erasure_stale_processing_minutes: int = 30
    # Age at which erasure_queue_health logs at warning. 7 days, deliberately
    # well inside GDPR's ~1-month response window so a stuck queue surfaces with
    # weeks of slack.
    graph_erasure_stale_alert_hours: int = 168
    # NOT A CAP, DESPITE THE NAME. This is the threshold for a FORENSIC VOLUME
    # MARKER, not an enforced limit. Exceeding it sets throttle_flagged=True on
    # the enqueued row for after-the-fact human review and changes NO execution
    # path: the request is never rejected (never a 429), the tenant's own local
    # deletion always runs, and the flagged row is claimed and processed by the
    # sweep identically to an unflagged one. The 61st request in a minute does
    # NOT fail. It records volumetric abuse; it prevents none. This deliberately
    # differs from the is_flagged_abuse precedent, which DOES exclude downstream
    # — excluding here would wedge a real erasure behind a manual release on a
    # legal clock while still failing to stop the actual named attack (a single
    # precision request). There is consequently no erasure abuse control of any
    # kind today; see the cumulative-cap backlog note.
    graph_erasure_max_per_minute: int = 60
    # The operator lookup IS an existence oracle by design, so precedent applies
    # in full here: default OFF, and admin-gated on top.
    graph_identity_lookup_enabled: bool = False

    # ─── Server-side AI-fetch capture beacon (Handoff Detection H5) ───
    # When true, POST /api/v1/agents/fetch-beacon accepts an authenticated
    # server-side beacon (from the getbeam.fyi edge middleware) that classifies
    # an on-demand AI-fetcher UA and writes agent_visit + agent_fetch_event rows.
    # Defaults OFF (mirrors agent_detection_enabled): with the flag off the
    # endpoint answers 404 (dormant, not revealed) and writes nothing. Flip on
    # only AFTER the pending EvalLayer migrations are live-applied in prod.
    agent_fetch_beacon_enabled: bool = False
    # Shared secret for the fetch-beacon trust boundary. Server-only on BOTH
    # Cloudflare Pages (web) and Railway (API) — identical value, NEVER shipped
    # to the browser. Empty (default) => the endpoint answers 401 to every call
    # (dormant, guarded BEFORE any constant-time compare: hmac.compare_digest
    # ('','') == True would otherwise ACCEPT an empty header — an auth bypass).
    beam_fetch_beacon_secret: str = ""

    # ─── Owned identity data layer (durable company graph) ───
    # When true, every successful free rDNS company resolution is persisted
    # write-through to the durable cross-tenant company_graph table, and a fresh
    # (non-stale) row is read before a new rDNS lookup. Defaults OFF until the
    # company_graph migration is confirmed applied — with the flag off, company
    # resolution behavior is byte-identical to the Redis-only path (same
    # precedent as agent_detection_enabled).
    company_graph_enabled: bool = False
    # Configurable window (days) before a company_graph row triggers lazy
    # re-validation at read time (no cron; read-time only).
    company_graph_staleness_days: int = 75

    # ─── Self-hosted IP→org database (Pillar 1: own the IP→company core) ───
    # When true, a local ``ip_org_prefixes`` longest-prefix lookup runs as the
    # LAST free rung of the company-resolution ladder (after rDNS, before the
    # paid PDL/IPinfo path in identity_resolver), and a hit is written through to
    # company_graph as source="rir_asn". Defaults OFF until the
    # ip_org_prefixes migration is live-applied AND a dataset has been ingested
    # — with the flag off the ladder is byte-identical to today (same
    # operator-gated posture as agent_detection_enabled / company_graph_enabled).
    # An empty table with the flag ON is still safe: the lookup just misses.
    ip_org_lookup_enabled: bool = False
    # CAIDA dataset roots. Directory URLs, not file URLs — the exact daily
    # snapshot filename changes, so the ingest job discovers the newest file from
    # each directory rather than pinning a name that goes 404 within a day.
    ip_org_dataset_pfx2as_url: str = (
        "https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/"
    )
    ip_org_dataset_as2org_url: str = (
        "https://publicdata.caida.org/datasets/as-organizations/"
    )
    # Snapshots are published daily; refreshing more often than that only burns
    # bandwidth. The job is advisory-locked, so a short interval is safe but
    # pointless.
    ip_org_refresh_interval_hours: int = 24

    # ─── IP-org evidence graph (Phase 3) ───
    # Phase 3 stops treating ip_org_prefixes as one flat prefix→company table and
    # starts recording WHICH relationship each row asserts, from three
    # independent sources, fused into a scored hypothesis. Every flag here
    # defaults OFF and each is an independent operator action AFTER the migration
    # is live-applied — same posture as ip_org_lookup_enabled above.
    #
    # Ingest of the RIR delegated-extended files (registered_holder evidence).
    # Rows land with org_kind='registry', which BOTH lookups filter out, so
    # turning this on cannot change what the currently-enabled v1 path returns —
    # it only makes the corroborating corpus available to fusion.
    ip_org_rir_ingest_enabled: bool = False
    ip_org_rir_delegated_urls: str = (
        "https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest,"
        "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest,"
        "https://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest,"
        "https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest,"
        "https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-extended-latest"
    )
    # Allocations change on the order of days, not hours. Weekly.
    ip_org_rir_refresh_interval_hours: int = 168

    # Ingest of validated RPKI ROAs (route-origin authorization cross-check).
    ip_org_rpki_ingest_enabled: bool = False
    ip_org_rpki_json_url: str = "https://rpki.cloudflare.com/rpki.json"
    ip_org_rpki_refresh_interval_hours: int = 24
    # Hard ceiling on the rpki.json body, enforced WHILE STREAMING. The file runs
    # ~50-100 MB uncompressed (400k-700k ROAs) and json.loads roughly doubles
    # peak RSS, so an unbounded read of an unexpectedly large or hostile response
    # is a real memory-exhaustion path. Exceeding this aborts the fetch mid-flight
    # and keeps the previously loaded ROAs — a normal fail-open outcome.
    ip_org_rpki_max_bytes: int = 209_715_200  # 200 MB

    # When true, the resolver's ip_org rung calls lookup_ip_org_v2 (fused,
    # multi-source, scored) instead of v1, and writes the FUSED confidence to
    # company_graph. With it off, v1 runs and the written row is byte-identical
    # to Phase 2 (source="rir_asn", confidence=0.45).
    #
    # The fused score is clamped to <= 0.65 on purpose: it must never outrank the
    # paid path (0.7), so a strongly-corroborated free hit cannot silently
    # displace data we paid for. It CAN exceed rDNS (0.5) when three independent
    # sources agree, which is the point of fusing them, and the reason this sits
    # behind a flag rather than shipping on.
    ip_org_fusion_enabled: bool = False

    # How long after a site is deleted its site_id stays eligible for reuse when
    # the SAME owner re-creates a site for the SAME normalized url. This bounds
    # REUSE ELIGIBILITY only — site_tombstones rows are never deleted (they are
    # a cheap audit trail of what id a domain used to have), and the window is
    # enforced at READ time in the create_site lookup, with no cron/TTL job
    # (mirrors company_graph_staleness_days above). Past this window a
    # re-created site gets a fresh random id, so a years-old tombstone can never
    # silently resurrect an id whose pixel is long gone.
    site_id_reclaim_window_days: int = 90

    # When true, SendGrid open/click engagement events are captured to the
    # identity_signals corroborating table (all 4 write gates enforced), and
    # corroborate_identity() may bump confidence on an ALREADY-matched identity.
    # NEVER creates or upgrades an IdentifiedVisitor on its own. Defaults OFF
    # until the identity_signals migration is confirmed applied — with the flag
    # off, the SendGrid webhook behavior is byte-identical to today.
    identity_signals_enabled: bool = False

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
    # Poll `GET /v1/data` inside the resolution waterfall. Separate from
    # leadpipe_enabled so the PULL path can be retired without also disabling the
    # webhook ingest path, which shares the provider name. Defaults True = no
    # behavior change; both paths may run at once (the unique index on
    # identified_visitors makes a double identification collapse into one row —
    # the only cost of overlap is one redundant API call, never a duplicate).
    # Flip to False once the webhook has proven itself; leave True as the fallback
    # while it hasn't, because Leadpipe auto-disables a webhook that errors
    # repeatedly and the pull path is then the only thing still collecting.
    leadpipe_pull_enabled: bool = True
    # Create a Leadpipe pixel for a site's domain on first snippet fetch.
    # Defaults OFF, like every other provider-touching switch here: this is the
    # one code path that MUTATES state at the vendor (POST /v1/data/pixels), and
    # pixels consume an org's quota and cannot be moved between orgs. An
    # always-on default would also make any test that fetches an install snippet
    # provision a real pixel for its fixture domain. Turn on deliberately, after
    # confirming LEADPIPE_API_KEY points at the org that should own the pixels.
    leadpipe_pixel_autoprovision_enabled: bool = False
    # Defaults OFF, unlike its siblings: the configured host `api.capturify.io` has
    # no DNS record (NXDOMAIN, checked 05-08-26), so every call fails to connect and
    # the provider has never produced a single `resolution_logs` row. The parsing
    # code is kept because `app.capturify.io` (the pixel host in tracker.js) does
    # resolve — the product exists, only this base URL is unverified. Turn back on
    # once an official doc confirms the real API base URL.
    capturify_enabled: bool = False
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

    # ─── Ad Audiences (push a segment's hashed contacts OUT to an ad platform) ───
    # Master feature flag. OFF by default: while false, every /api/v1/ads connect
    # attempt returns HTTP 501 and no site's behavior changes. Flipping this on in
    # a real environment is an explicit operator action AFTER the ad_connections /
    # ad_audience_links migrations are live-applied.
    ad_audiences_enabled: bool = False
    meta_ads_client_id: str = ""
    meta_ads_client_secret: str = ""
    meta_ads_redirect_uri: str = "http://localhost:8000/api/v1/ads/callback/meta"
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_redirect_uri: str = "http://localhost:8000/api/v1/ads/callback/google"
    # Google Ads API requires a `developer-token` HTTP header on EVERY call
    # (docs: developers.google.com/google-ads/api/rest/auth#developer-token).
    # Obtained from the Google Ads UI API Center under the manager account. A
    # Test-Account-Access token is enough for the sandbox dev path — Basic
    # access approval is a separate, later operator action.
    google_ads_developer_token: str = ""
    # Present for schema symmetry only — LinkedIn stays ready=False, so these are
    # never read while the provider is unsupported.
    linkedin_ads_client_id: str = ""
    linkedin_ads_client_secret: str = ""
    linkedin_ads_redirect_uri: str = "http://localhost:8000/api/v1/ads/callback/linkedin"
    # Per-site cap on ad push operations per clock hour. Independent counter from
    # the CRM cap — a site's ad pushes and CRM pushes do not share one budget.
    max_ads_pushes_per_hour_per_site: int = 20
    ads_async_push: bool = False
    ads_async_push_threshold: int = 200  # segment member count above which async kicks in

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

    # Trailing whitespace pasted into an env var (e.g. a stray newline when
    # copying an OAuth secret into Railway) silently breaks credential
    # validation: the value looks correct in the dashboard but the provider
    # rejects it with a baffling "invalid client secret". Strip every OAuth
    # id/secret/redirect so a fat-fingered paste can't cause that failure.
    @field_validator(
        "twitter_client_id", "twitter_client_secret", "twitter_redirect_uri",
        "twitter_bearer_token",
        "facebook_app_id", "facebook_app_secret", "facebook_redirect_uri",
        "instagram_app_id", "instagram_app_secret", "instagram_redirect_uri",
        "linkedin_client_id", "linkedin_client_secret", "linkedin_redirect_uri",
        "tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri",
        "google_client_id", "google_client_secret", "google_redirect_uri",
        "meta_ads_client_id", "meta_ads_client_secret", "meta_ads_redirect_uri",
        "google_ads_client_id", "google_ads_client_secret", "google_ads_redirect_uri",
        "google_ads_developer_token",
        "linkedin_ads_client_id", "linkedin_ads_client_secret", "linkedin_ads_redirect_uri",
        mode="after",
    )
    @classmethod
    def _strip_oauth_credential(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    # ─── Connect-Gmail (send campaign email from the site owner's Gmail) ───
    # OAuth client from Google Cloud (Gmail API, scope gmail.send). When empty,
    # the Connect-Gmail endpoints 400 and campaign sends stay on SendGrid.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/email/callback/google"

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

    # ─── Lemon Squeezy Billing (legacy MoR fallback) ───
    # Stripe is unavailable in Vietnam, and Lemon Squeezy rejected Beam's
    # category. These settings remain for historical webhook compatibility.
    lemonsqueezy_api_key: str = ""           # Settings → API
    lemonsqueezy_store_id: str = ""          # numeric store id
    lemonsqueezy_webhook_secret: str = ""    # webhook signing secret
    ls_variant_pro_monthly: str = ""         # LS variant id — Pro monthly
    ls_variant_pro_yearly: str = ""          # LS variant id — Pro yearly
    ls_variant_max_monthly: str = ""         # LS variant id — Max monthly
    ls_variant_max_yearly: str = ""          # LS variant id — Max yearly

    # ─── Gumroad Billing (active Merchant of Record) ───
    # Gumroad provides NO webhook HMAC signature, so the Ping is authenticated by
    # a secret token appended to the endpoint URL plus an optional seller_id
    # match. Configure at Gumroad → Settings → Advanced → "Ping endpoint":
    #   https://<api-host>/api/v1/billing/gumroad/webhook?token=<gumroad_webhook_secret>
    gumroad_webhook_secret: str = ""         # secret URL token authenticating the Ping
    gumroad_seller_id: str = ""              # your Gumroad seller_id (optional defense-in-depth)
    gumroad_product_permalink: str = ""      # product permalink, e.g. "rlkwnz" (fallback checkout page)
    gumroad_checkout_pro_monthly_url: str = ""
    gumroad_checkout_pro_yearly_url: str = ""
    gumroad_checkout_max_monthly_url: str = ""
    gumroad_checkout_max_yearly_url: str = ""
    gumroad_customer_portal_url: str = "https://gumroad.com/library"

    # ─── Feature flags ───
    sync_interval_minutes: int = 60
    resolution_sweep_interval_minutes: int = 30  # APScheduler identity-resolution sweep cadence
    agent_verification_sweep_interval_minutes: int = 15  # APScheduler agent IP-verification sweep cadence
    agent_ip_range_refresh_interval_hours: int = 24  # Re-fetch published per-agent IP-range datasets; stale ranges make real agents look like forged ones
    handoff_correlation_sweep_interval_minutes: int = 10  # APScheduler fetch↔click handoff correlation sweep cadence (H2)
    # How long a fetch event must age before the H2 sweep will correlate it. This
    # is ONLY the settle delay — it is NOT the correlation window. The window
    # (agent_handoff_correlation._WINDOW_SECONDS) still decides which clicks count,
    # so lowering this shortens the wait for a link to appear without narrowing
    # what qualifies as a match. Lower it in dev/UAT to see a link in ~1 min
    # instead of ~30; production keeps the default so every fetch is scored
    # against its complete candidate set (a fetch is linked once, permanently —
    # settling early can lock in a weak click and shut out a better later one).
    # Must stay below agent_handoff_correlation._UNLINKED_LOOKBACK_MINUTES or no
    # fetch is ever both old enough and young enough to be swept; the sweep clamps
    # and warns rather than silently linking nothing.
    handoff_correlation_settle_seconds: int = 1800
    intent_signal_sweep_interval_minutes: int = 10  # APScheduler live commercial-page intent-signal + spike sweep cadence (H3)
    aggregation_sweep_interval_minutes: int = 60  # APScheduler full-recompute aggregation repair sweep cadence
    # Data retention (GDPR data minimization / privacy-policy 90-day promise):
    # raw events older than this are auto-purged. Enriched profiles are kept.
    event_retention_days: int = 90
    # Per-hit agent_fetch_events (Handoff Detection H1) share the same 90-day
    # retention promise as raw events — purged by the same sweep.
    agent_fetch_event_retention_days: int = 90
    retention_purge_interval_hours: int = 24  # daily purge sweep

    # ─── Admin request/response log (debug observability) ───
    # Captures full request + response JSON for requests that were DROPPED or
    # FLAGGED, so an operator can answer "why was this traffic rejected?" without
    # hand-writing SQL. Default OFF — same operator-gated posture as
    # agent_detection_enabled / ingest_velocity_enabled.
    #
    # PII posture: bodies pass through services/log_redaction.py before storage —
    # emails become domain-only, credential-shaped keys become "***". This keeps
    # the guardrail "never log PII" intact while leaving the JSON shape debuggable.
    # Turning redaction off is deliberately NOT a setting; it would create a new
    # raw-PII store with no compensating control.
    request_log_enabled: bool = False
    # 7 days, deliberately shorter than the 90-day event retention: these rows
    # carry richer per-request detail, so they earn a tighter window.
    request_log_retention_days: int = 7
    # Hard cap per captured body. Anything past this is truncated with a marker —
    # the middleware never buffers an unbounded response.
    request_log_max_body_bytes: int = 16_384
    # Fraction of NON-dropped, NON-flagged (i.e. successful) requests to sample.
    # 0.0 = log only drops/flags, which is the shipped default. Raise it only to
    # capture a baseline for comparison; every sampled row costs a write on the
    # hot path.
    request_log_sample_rate: float = 0.0
    # Paths never logged regardless of outcome — health checks and the log
    # viewer itself (which would otherwise log its own reads in a loop).
    request_log_exclude_paths: str = "/health,/api/v1/admin/request-logs"
    # Status codes that never produce a row on their own.
    #
    # 401 by default: the dashboard's Clerk token has a ~60s TTL, so the API
    # client's normal refresh path (401 -> fetch fresh token -> retry -> 200)
    # emits a 401 on routine page loads. Logging those buries real signal under
    # the app's own healthy behaviour. 403 is deliberately NOT ignored —
    # authenticated-but-denied is worth seeing (permission bug, or probing).
    #
    # Set to "" to capture 401s during an auth-probing investigation. An explicit
    # route marker (request.state.log_reason) still wins over this list, so a
    # deliberately-flagged request is never silenced by it.
    request_log_ignore_statuses: str = "401"

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

    # ─── GitHub public-profile reader (read public bio + top repos for persona /
    # campaign personalization; behind a flag, default OFF) ───
    enable_github_reader: bool = False           # master gate — off until explicitly enabled (G5)
    # DELIBERATELY SEPARATE from `github_token` above (G4). `github_token` is a
    # repo-scoped PAT for the private changelog sync — reusing it here would burn
    # the same 5000 req/hr budget as an unrelated internal job AND widen the blast
    # radius of a credential that can read a private repo. This one is a plain
    # public-API PAT (classic with no scopes, or fine-grained with zero repo
    # access). Empty is fine: the public REST endpoints work unauthenticated at a
    # lower 60 req/hr ceiling; a token raises it to 5000 req/hr.
    github_osint_token: str = ""
    github_reader_max_repos: int = 5             # top-N most-recently-pushed repos to keep

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
    # Comma-separated hostnames; sites whose url matches get US-any-intent resolution
    # eligibility (all other sites keep the RESOLUTION_MIN_INTENT gate). Empty string disables.
    resolve_all_us_domains: str = "getbeam.fyi"
    # While a site has fewer than N identified visitors EVER, the resolution intent
    # floor is waived entirely for that site (aha-moment bootstrap — a brand-new site
    # can't clear the floor on first-visit traffic). Highest-intent-first ordering,
    # the daily budget, the plan cap, and the 30-day no-retry gate are unchanged.
    # 0 disables the boost.
    first_win_boost_count: int = 5
    default_daily_enrichment_budget: int = 3    # Free tier: 3 deep research/day (BYOK = unlimited)
    max_emails_per_hour_per_site: int = 50

    model_config = {"env_file": ("../../.env", ".env"), "extra": "ignore"}


settings = Settings()
