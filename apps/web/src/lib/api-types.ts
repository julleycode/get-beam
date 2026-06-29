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
  /** Optional — backend SiteOut may not return it; callers fall back to "unknown". */
  detected_platform?: string | null;
  created_at: string;
}

// Partial site update payload — mirrors the backend SiteUpdate schema.
export interface SiteUpdate {
  auto_identify_enabled: boolean;
  hot_alert_enabled: boolean;
  tracking_enabled: boolean;
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
  enrichment_completeness?: number | null;
  social_context?: {
    deep_research?: string;
    researched_at?: string;
    model?: string;
    osint_scan?: OsintScan;
    social_resolution?: SocialResolution;
  } | null;
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
  monthly_limit: number | null;  // null = unlimited
  trial_ends_at: string | null;
  current_period_end: string | null;
}

export interface CancelSubscriptionResponse {
  subscription_status: string | null;
  current_period_end: string | null;
}
