/**
 * Shared TypeScript types for the API client.
 *
 * Extracted verbatim from lib/api.ts (Phase 15 split). lib/api.ts re-exports
 * every name here, so `import { api, Visitor } from "@/lib/api"` keeps working
 * unchanged for all importers.
 */

export interface KnownUploadResult {
  inserted: number;
  skipped: number;
  total: number;
  truncated: boolean;
}

// ── Blog CMS types ──────────────────────────────────────
export interface BlogPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string | null;
  body_markdown: string;
  author_name: string;
  cover_image_url: string | null;
  tags: string[] | null;
  meta_title: string | null;
  meta_description: string | null;
  canonical_url: string | null;
  og_image_url: string | null;
  reading_time_minutes: number | null;
  published_at: string | null;
  created_at: string;
}

export interface BlogPostAdmin extends BlogPost {
  status: string;
  site_id: string | null;
  updated_at: string | null;
  scheduled_for: string | null;
  // Author-only SEO input (not exposed on public posts).
  focus_keyword: string | null;
}

export interface BlogPostListResponse {
  posts: BlogPost[];
  total: number;
}

export interface BlogPostAdminListResponse {
  posts: BlogPostAdmin[];
  total: number;
}

export interface BlogPostInput {
  title: string;
  body_markdown?: string;
  excerpt?: string | null;
  author_name?: string | null;
  cover_image_url?: string | null;
  tags?: string[] | null;
  slug?: string | null;
  focus_keyword?: string | null;
  meta_title?: string | null;
  meta_description?: string | null;
  canonical_url?: string | null;
  og_image_url?: string | null;
}

export type ChangelogCategory = "new" | "improved" | "fixed";

export interface ChangelogEntry {
  id: string;
  title: string;
  body: string;
  category: string;
  published_at: string | null;
  created_at: string;
}

export interface ChangelogEntryAdmin extends ChangelogEntry {
  status: string;
  updated_at: string | null;
}

export interface ChangelogAdminListResponse {
  entries: ChangelogEntryAdmin[];
  total: number;
}

export interface ChangelogEntryInput {
  title: string;
  body?: string;
  category?: ChangelogCategory;
}

export interface ChangelogSyncResponse {
  scanned: number;
  imported: number;
  skipped_internal: number;
  already_present: number;
}

// Types
export interface Site {
  id: string;
  site_id: string;
  name: string;
  url: string;
  description: string | null;
  category: string | null;
  pixel_verified: boolean;
  daily_resolution_budget: number;
  auto_identify_enabled: boolean;
  hot_alert_enabled: boolean;
  tracking_enabled: boolean;
  /** Cookie-consent mode emitted into the pixel snippet: off | eu | all | cmp. */
  consent_mode: ConsentMode;
  /** Optional — backend SiteOut may not return it; callers fall back to "unknown". */
  detected_platform?: string | null;
  created_at: string;
}

export type ConsentMode = "off" | "eu" | "all" | "cmp";

// Partial site update payload — mirrors the backend SiteUpdate schema.
export interface SiteUpdate {
  auto_identify_enabled: boolean;
  hot_alert_enabled: boolean;
  tracking_enabled: boolean;
  consent_mode: ConsentMode;
}

export interface FeatureRequest {
  id: string;
  title: string;
  detail: string | null;
  urgency: string | null;
  email: string | null;
  source: string | null;
  status: string;
  admin_note: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface FeatureBoardItem {
  id: string;
  title: string;
  detail: string | null;
  urgency: string | null;
  status: string;
  votes: number;
  my_vote: boolean;
  created_at: string;
}

export interface FeatureBoardResponse {
  items: FeatureBoardItem[];
  total: number;
}

export interface FeatureVoteResult {
  request_id: string;
  votes: number;
  my_vote: boolean;
}

export interface FeatureRequestListResponse {
  requests: FeatureRequest[];
  total: number;
}

export interface Visitor {
  id: string;
  site_id: string;
  visitor_id: string;
  first_seen: string;
  last_seen: string;
  total_pageviews: number;
  total_sessions: number;
  avg_time_on_page: number;
  max_scroll_depth: number;
  pages_visited: string[];
  top_referrer: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  country_code: string | null;
  device_type: string | null;
  // AI answer-engine that referred this human click (chatgpt/perplexity/…).
  // Additive attribution only — never affects emailability.
  ai_source?: string | null;
  intent_score: number;
  identity_status: string;
  enrichment_status: string;
  email?: string | null;
  full_name?: string | null;
  // 'person' = the real visitor; 'company' = an arbitrary employee guessed
  // from the visitor's IP→company domain (Hunter/Apollo), NOT the real person.
  identity_level?: "person" | "company" | null;
  is_known?: boolean;
  known_source?: string | null;
  conviction?: string | null;
  // Handoff Detection H2: strongest fetch↔click handoff link confidence
  // ("high"/"medium"), or null/undefined when none. PROBABILISTIC list-row pill.
  handoff_confidence?: string | null;
}

export interface VisitorDetail extends Visitor {
  email?: string | null;
  full_name?: string | null;
  phone?: string | null;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  coverage_note?: string | null;
  job_title?: string | null;
  company_name?: string | null;
  industry?: string | null;
  linkedin_url?: string | null;
  twitter_handle?: string | null;
  linkedin_headline?: string | null;
  twitter_bio?: string | null;
  avatar_url?: string | null;
  enrichment_completeness?: number | null;
  social_context?: {
    deep_research?: string;
    researched_at?: string;
    model?: string;
    osint_scan?: OsintScan;
    social_resolution?: SocialResolution;
  } | null;
  // Handoff Detection H2: latest fetch↔click handoff link for this visitor, if
  // any. PROBABILISTIC attribution only (an AI agent fetched this page shortly
  // before the visit) — never a certainty assertion, never affects emailability.
  handoff_vendor?: string | null;
  handoff_confidence?: string | null; // "high" | "medium"
  handoff_delta_seconds?: number | null;
  handoff_matched_page?: string | null;
  handoff_fetch_at?: string | null;
}

export interface SocialResolution {
  status: "scanning" | "complete" | "error" | "not_identified";
  resolved_at?: string;
  stages_run?: string[];
  profiles?: OsintAccount[]; // verified = confirmed + likely
  guesses?: OsintAccount[]; // unverified guesses (collapsed in UI)
  paid?: {
    used: boolean;
    provider: string;
    found: number;
    cached?: boolean;
    error?: string | null;
  };
  summary?: {
    profile_count?: number;
    confirmed_count?: number;
    likely_count?: number;
    guess_count?: number;
    candidates_used?: string[];
  };
  message?: string;
}

export interface OsintAccount {
  site_name: string;
  category?: string | null;
  url?: string | null;
  kind: "profile" | "registered";
  confidence: "confirmed" | "likely" | "guess";
  source_engine: string;
  extra?: Record<string, unknown>;
}

export interface OsintScan {
  status:
    | "scanning"
    | "complete"
    | "cached"
    | "error"
    | "disabled"
    | "not_identified"
    | "skipped_no_email";
  scanned_at?: string;
  engines?: string[];
  accounts?: OsintAccount[];
  summary?: {
    registered_count?: number;
    profile_count?: number;
    checked?: number;
    total?: number;
    partial?: boolean;
    skipped_categories?: string[];
  };
  message?: string;
}

export interface VisitorListResponse {
  visitors: Visitor[];
  total: number;
  page: number;
  page_size: number;
}

export interface VisitorCountry {
  country_code: string;
  count: number;
}

export interface VisitorAiSource {
  ai_source: string;
  count: number;
}

// Agent traffic (SPEC D1 — AI-agent visits, structurally separate from human
// Visitor data). Field names are snake_case on the wire, matching AgentOut /
// AgentDetailOut in apps/api/schemas/agents.py exactly (no camelCase mapping).
export interface Agent {
  id: string;
  site_id: string;
  vendor: string;
  product_or_ua_token: string;
  // "ua-only" | "ip-verified" | "rdns-verified"
  verification_method: string;
  last_seen_at: string;
  visit_count: number;
}

export interface AgentDetail extends Agent {
  first_seen_at: string;
  ip_address: string | null;
  page_paths: string[];
  resolved_company_id: string | null;
}

export interface AgentListResponse {
  agents: Agent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AgentStatsResponse {
  total_visits: number;
  distinct_vendors: number;
  by_vendor: Record<string, number>;
}

// Read-only GEO/AEO analytics snapshot — matches AgentAnalyticsResponse /
// TopPageEntry in apps/api/schemas/agents.py field-for-field (snake_case wire).
export interface TopPageEntry {
  path: string;
  count: number;
}

export interface RecentAiResearchEntry {
  company_name: string;
  domain: string | null;
  matched_page: string;
  researched_at: string;
}

export interface AgentAnalytics {
  by_vendor: Record<string, number>;
  top_pages: TopPageEntry[];
  by_verification: Record<string, number>;
  // Handoff Detection H2: agent fetches correlated to a human AI-referral click.
  handoff_links_count: number;
  // Handoff Detection H3: companies that appeared shortly after an AI agent
  // fetched a commercial page. Read-only metadata, never an outreach feed.
  recent_ai_researched_companies: RecentAiResearchEntry[];
}

export interface Segment {
  id: string;
  site_id: string;
  name: string;
  description: string | null;
  characteristics: Record<string, unknown>;
  recommended_channels: string[];
  messaging_angle: string | null;
  priority: string;
  visitor_count: number;
  created_at: string;
}

export interface SegmentListResponse {
  segments: Segment[];
  total: number;
}

export interface Campaign {
  id: string;
  site_id: string;
  segment_id: string | null;
  name: string;
  campaign_type: string;
  platform: string | null;
  status: string;
  plan: Record<string, unknown>;
  created_at: string;
  approved_at: string | null;
  started_at: string | null;
}

export interface CampaignListResponse {
  campaigns: Campaign[];
  total: number;
}

export interface CampaignSendSummary {
  total_audience: number;
  sent: number;
  skipped_no_email: number;
  skipped_suppressed: number;
  skipped_already_sent: number;
  throttled: number;
  failed: number;
}

export interface CampaignSendResponse {
  campaign_id: string;
  status: string;
  summary: CampaignSendSummary;
}

export interface ReturnedVisitor {
  visitor_id: string;
  full_name: string | null;
  email_masked: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  last_visit_at: string | null;
  pageviews_after: number;
}

export interface CampaignStats {
  sent: number;
  opened: number;
  clicked: number;
  open_rate: number;
  click_rate: number;
  converted: number;
  conversion_rate: number;
  revenue_cents: number;
  returned_visitors: ReturnedVisitor[];
}

// ── Conversion outcomes ──
export interface ConversionGoal {
  id: string;
  name: string;
  goal_type: string;
  match_type: "exact" | "prefix" | "contains";
  pattern: string;
  value_cents: number | null;
  repeatable: boolean;
  enabled: boolean;
  created_at: string;
}

export interface GoalListResponse {
  goals: ConversionGoal[];
  total: number;
}

export interface GoalCreatePayload {
  name: string;
  goal_type?: "url_match" | "js_event";
  match_type?: "exact" | "prefix" | "contains";
  pattern?: string;
  value_cents?: number | null;
  repeatable?: boolean;
}

export interface GoalUpdatePayload {
  name?: string;
  match_type?: "exact" | "prefix" | "contains";
  pattern?: string;
  value_cents?: number | null;
  repeatable?: boolean;
  enabled?: boolean;
}

export interface OutcomeTotals {
  conversions: number;
  attributed: number;
  organic: number;
  revenue_cents: number;
  attributed_revenue_cents: number;
}

export interface CampaignOutcomeRow {
  campaign_id: string;
  name: string;
  sent: number;
  opened: number;
  clicked: number;
  converted: number;
  conversion_rate: number;
  revenue_cents: number;
}

export interface GoalOutcomeRow {
  goal_id: string;
  name: string;
  goal_type: string;
  enabled: boolean;
  conversions: number;
  attributed: number;
  revenue_cents: number;
}

export interface OutcomesReport {
  days: number;
  totals: OutcomeTotals;
  campaigns: CampaignOutcomeRow[];
  goals: GoalOutcomeRow[];
}

export interface OutcomesWebhookConfig {
  configured: boolean;
  hint: string | null;
  url: string;
}

export interface OutcomesWebhookSecret {
  secret: string;
  hint: string;
}

// ── LinkedIn outreach (via phantommm sidecar) ──
export interface LinkedInOutreachConnectResponse {
  connected: boolean;
  name: string | null;
  connection_id_present: boolean;
}

export interface LinkedInOutreachStatus {
  outreach_connected: boolean;
  configured: boolean;
}

export interface LinkedInOutreachResponse {
  job_id: string;
  dry_run: boolean;
  total_targets: number;
  audience_skipped_no_linkedin: number;
}

export interface LinkedInOutreachJob {
  status: string;
  done: number;
  total: number;
  sent: number;
  results: Record<string, unknown>[];
}

// ── LinkedIn scheduled drip campaign (via phantommm sidecar) ──
export interface LinkedInScheduleResponse {
  // Empty string in dry-run (phantommm may omit campaignId).
  campaign_id: string;
  scheduled_at: string | null;
  delay_hours: number;
  dry_run: boolean;
  total_targets: number;
  audience_skipped_no_linkedin: number;
}

export interface LinkedInCampaignDetail {
  status_counts: Record<string, number>;
  scheduled_at: string | null;
  days: Record<string, unknown>[];
}

export interface BrowserRow {
  browser: string;
  captured: number;
  identified: number;
  identification_rate: number;
  share: number;
}

export interface SafariCoverage {
  actual_share: number;
  expected_share: number;
  coverage_ratio: number | null;
  status: "ok" | "watch" | "likely_blocked" | "insufficient_data";
  message: string;
}

export interface BrowserMetrics {
  total_pageviews: number;
  avg_time_on_page: number; // seconds
  bounce_rate: number; // 0..1
  identified: number;
  enriched: number;
}

export interface BrowserBreakdown {
  site_id: string;
  window_days: number;
  total_visitors: number;
  browsers: BrowserRow[];
  // Optional so the card degrades gracefully against a backend not yet deployed.
  metrics?: BrowserMetrics;
  safari_coverage: SafariCoverage;
}

export interface CountryShare {
  country: string;
  count: number;
  share: number; // 0..1
}

export interface TrafficFit {
  site_id: string;
  window_days: number;
  total_visitors: number;
  located_visitors: number; // visitors with a known country
  us_share: number; // 0..1, of located
  unknown_share: number; // 0..1, of total
  servable_count: number;
  identified_servable: number;
  us_match_rate: number | null; // measured, null until enough US visitors
  identifiable_estimate: number; // 0..1 — "~X% of visitors are identifiable"
  top_countries: CountryShare[];
  status: "good_fit" | "partial_fit" | "poor_fit" | "insufficient_data";
  message: string;
}

export interface SiteKpis {
  site_id: string;
  window_days: number;
  visitors: number;
  identified: number;
  enriched: number;
  high_intent: number;
  acted: number;
  acted_high_intent: number;
  sent: number;
  identify_rate: number; // 0..1
  action_rate: number; // 0..1
  reply_tracking_available: boolean;
}

export interface TimeseriesPoint {
  date: string; // YYYY-MM-DD
  visitors: number;
  identified: number;
  high_intent: number;
}

export interface SiteTimeseries {
  site_id: string;
  window_days: number;
  series: TimeseriesPoint[];
}

export interface SiteStats {
  total_visitors: number;
  identified: number;
  enriched: number;
  could_enrich_more: number;
  // Action-panel fields — backend /visitors/{id}/stats returns these; optional
  // here for back-compat with callers that only read the core counts.
  eligible_for_resolution?: number;
  enriched_unsegmented?: number;
  identify_used_today?: number;
  identify_daily_limit?: number | null;
}

export interface CostProviderRow {
  provider: string;
  calls: number;
  cost_usd: number;
  success_rate: number; // 0..1
}

export interface CostCategoryRow {
  category: string;
  calls: number;
  cost_usd: number;
}

export interface CostDayRow {
  date: string; // YYYY-MM-DD
  calls: number;
  cost_usd: number;
}

export interface IdentityCoverage {
  owned_calls: number; // free resolutions from Beam's own data
  paid_calls: number; // resolutions from paid providers
  coverage_rate: number; // owned / (owned + paid), 0..1
}

export interface CostSummary {
  site_id: string;
  days: number;
  total_usd: number;
  total_calls: number;
  success_calls: number;
  failed_calls: number;
  by_provider: CostProviderRow[];
  by_category: CostCategoryRow[];
  by_day: CostDayRow[];
  identity_coverage: IdentityCoverage;
}

export interface ApiKeyInfo {
  provider: string;
  key_hint: string;
  is_valid: boolean;
  created_at: string;
}

export type CrmProvider = "generic_webhook" | "hubspot" | "pipedrive" | "salesforce";

export interface CrmConnection {
  provider: CrmProvider;
  auth_type: "oauth" | "webhook";
  status: "pending" | "connected" | "error" | "disconnected";
  direction: string;
  external_account_label: string | null;
  webhook_url: string | null;
  secret_hint: string | null;
  field_mapping: Record<string, string>;
  is_valid: boolean;
  last_pushed_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface CrmPushResult {
  provider: string;
  segment_id: string;
  pushed: number;
  failed: number;
  skipped: number;
  errors: string[];
  queued?: boolean;
}

// ── EasyEngage types ──────────────────────────────────

export type Platform = "facebook" | "instagram" | "linkedin" | "twitter" | "tiktok";
export type DraftStatus = "pending" | "approved" | "rejected" | "sent" | "failed";

export interface SocialAccount {
  id: string;
  platform: Platform;
  username: string;
  platform_user_id: string;
  is_active: boolean;
  token_expires_at: string | null;
  created_at: string;
  /** LinkedIn cookie-registered outreach account: no OAuth token to expire/reconnect. */
  is_outreach: boolean;
  /** Backend holds a refresh token and renews access automatically at send
   * time, so a short access-token expiry (e.g. Twitter's 2h) is not a
   * user-facing problem. */
  has_refresh_token: boolean;
  /** Connect-time write-access probe: true = ready to post, false = needs
   * write access, null = unknown / not probed. */
  post_ready: boolean | null;
}

export interface SocialPost {
  id: string;
  platform: Platform;
  author_name: string;
  author_username: string;
  author_avatar_url: string | null;
  content: string | null;
  media_urls: string[] | null;
  post_url: string | null;
  commented: boolean;
  posted_at: string;
  created_at: string;
}

export interface FeedResponse {
  posts: SocialPost[];
  total: number;
  page: number;
  per_page: number;
}

export interface SocialDraft {
  id: string;
  type: "reply" | "comment";
  platform: Platform;
  ai_content: string;
  edited_content: string | null;
  status: DraftStatus;
  strategy: string | null;
  strategy_label: string | null;
  sent_at: string | null;
  created_at: string;
  /** Plain-language reason a send failed (set on failed drafts). */
  failure_reason: string | null;
  /** Why a rejected draft was rejected: "user_rejected" | "auto_rejected_sibling". */
  rejection_reason: string | null;
  original_content: string | null;
  original_author: string | null;
}

export interface DraftListResponse {
  drafts: SocialDraft[];
  total: number;
}

export interface GenerateMultiDraftResponse {
  mode: "learning" | "confident";
  drafts: SocialDraft[];
  voice_example_count: number;
}

// ── Billing types ─────────────────────────────────────────

// ── Engagement types ──────────────────────────────────────

export interface EngagementROI {
  total_engagements: number;
  new_visitors_attributed: number;
  identified_from_engagement: number;
  period_days: number;
}

export type BillingPlan = "free" | "pro" | "max";
export type BillingInterval = "monthly" | "yearly";

// Classifies a usage-limit outcome from resolve/enrich. "monthly_plan" is the
// only upgrade moment (plan tiers differ only on the monthly cap); daily kinds
// are BYOK-only and must NOT open the upgrade modal.
export type LimitKind = "monthly_plan" | "daily_budget" | "daily_enrichment";

// ── Waitlist types ───────────────────────────────────────

export interface WaitlistSignup {
  id: string;
  email: string;
  site_url: string | null;
  status: string;
  invite_token: string | null;
  created_at: string | null;
  approved_at: string | null;
}

export interface WaitlistListResponse {
  signups: WaitlistSignup[];
  counts: {
    pending: number;
    approved: number;
    granted: number;
    rejected: number;
  };
}

export interface BillingStatus {
  plan: BillingPlan;
  subscription_status: string | null;
  monthly_identified_count: number;
  monthly_limit: number | null;  // null = unlimited; includes referral bonus
  bonus_monthly_quota: number;   // earned referral bonus baked into monthly_limit
  trial_ends_at: string | null;
  current_period_end: string | null;
}

// ── Referral program ──────────────────────────────────────

export interface ReferralEntry {
  email_masked: string;
  status: "pending" | "activated";
  signed_up_at: string | null;
  activated_at: string | null;
}

export interface ReferralInfo {
  code: string;
  link: string;
  bonus_monthly_quota: number;
  bonus_cap: number;
  bonus_per_activation: number;
  referred_count: number;
  activated_count: number;
  referrals: ReferralEntry[];
}

export interface CancelSubscriptionResponse {
  subscription_status: string | null;
  current_period_end: string | null;
  portal_url: string | null;
  message: string | null;
}
