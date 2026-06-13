const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;
  private clerkToken: string | null = null;

  // ── Clerk token (primary, set by ClerkTokenSync) ────
  setClerkToken(token: string | null) {
    this.clerkToken = token;
  }

  // ── Legacy token (localStorage fallback) ────────────
  setToken(token: string) {
    this.token = token;
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_token", token);
    }
  }

  getToken(): string | null {
    // Prefer Clerk token over legacy
    if (this.clerkToken) return this.clerkToken;
    if (this.token) return this.token;
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem("auth_token");
    }
    return this.token;
  }

  clearToken() {
    this.token = null;
    this.clerkToken = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem("auth_token");
    }
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
      });
    } catch (err) {
      throw new Error(
        `Network error: unable to reach API (${(err as Error).message})`
      );
    }

    if (res.status === 401) {
      // Don't clear Clerk token — Clerk handles re-auth via middleware
      if (!this.clerkToken) {
        this.clearToken();
        if (typeof window !== "undefined") {
          window.location.href = "/sign-in";
        }
      }
      throw new Error("Unauthorized");
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }

    if (res.status === 204) return undefined as T;
    return res.json();
  }

  // Auth
  async signup(email: string, password: string, fullName?: string) {
    return this.request<{ access_token: string }>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName }),
    });
  }

  async login(email: string, password: string) {
    return this.request<{ access_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  }

  async getMe() {
    return this.request<{
      id: string;
      email: string;
      full_name: string | null;
      is_admin?: boolean;
    }>("/api/v1/auth/me");
  }

  // Feature requests (submitted from the landing page FAB)
  async listFeatureRequests(status?: string) {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request<FeatureRequestListResponse>(`/api/v1/feature-requests${qs}`);
  }

  async updateFeatureRequest(id: string, data: { status?: string; admin_note?: string }) {
    return this.request<FeatureRequest>(`/api/v1/feature-requests/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  // Community feature board (logged-in users)
  async getFeatureBoard() {
    return this.request<FeatureBoardResponse>("/api/v1/feature-requests/board");
  }

  async submitBoardRequest(data: { title: string; detail?: string; urgency?: string }) {
    return this.request<FeatureBoardItem>("/api/v1/feature-requests/board", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async voteFeature(requestId: string) {
    return this.request<FeatureVoteResult>(
      `/api/v1/feature-requests/${requestId}/vote`,
      { method: "POST" }
    );
  }

  // Sites
  async createSite(name: string, url: string, description?: string, category?: string) {
    return this.request<Site>("/api/v1/sites/", {
      method: "POST",
      body: JSON.stringify({ name, url, description, category }),
    });
  }

  async listSites() {
    return this.request<Site[]>("/api/v1/sites/");
  }

  async getSite(siteId: string) {
    return this.request<Site>(`/api/v1/sites/${siteId}`);
  }

  async getPixelSnippet(siteId: string) {
    return this.request<{ site_id: string; snippet: string }>(
      `/api/v1/sites/${siteId}/pixel`
    );
  }

  // Visitors
  async listVisitors(
    siteId: string,
    params: {
      page?: number;
      page_size?: number;
      identity_status?: string;
      min_intent?: number;
      sort_by?: string;
    } = {}
  ) {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.page_size) query.set("page_size", String(params.page_size));
    if (params.identity_status) query.set("identity_status", params.identity_status);
    if (params.min_intent !== undefined) query.set("min_intent", String(params.min_intent));
    if (params.sort_by) query.set("sort_by", params.sort_by);

    return this.request<VisitorListResponse>(
      `/api/v1/visitors/${siteId}?${query.toString()}`
    );
  }

  async getVisitor(siteId: string, visitorId: string) {
    return this.request<VisitorDetail>(
      `/api/v1/visitors/${siteId}/${visitorId}`
    );
  }

  async getVisitorStats(siteId: string) {
    return this.request<SiteStats>(`/api/v1/visitors/${siteId}/stats`);
  }

  async getBrowserBreakdown(siteId: string, windowDays = 30) {
    return this.request<BrowserBreakdown>(
      `/api/v1/sites/${siteId}/browser-breakdown?window_days=${windowDays}`
    );
  }

  // Segments
  async listSegments(siteId: string) {
    return this.request<SegmentListResponse>(`/api/v1/segments/${siteId}`);
  }

  async triggerSegmentation(siteId: string) {
    return this.request<{ status: string }>(`/api/v1/segments/${siteId}/run`, {
      method: "POST",
    });
  }

  // Campaigns
  async listCampaigns(siteId: string) {
    return this.request<CampaignListResponse>(`/api/v1/campaigns/${siteId}`);
  }

  async getCampaign(siteId: string, campaignId: string) {
    return this.request<Campaign>(`/api/v1/campaigns/${siteId}/${campaignId}`);
  }

  async updateCampaignStatus(siteId: string, campaignId: string, status: string) {
    return this.request<Campaign>(
      `/api/v1/campaigns/${siteId}/${campaignId}/status`,
      {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }
    );
  }

  /**
   * Send the campaign's email touchpoint to its segment audience.
   * Backend requires status === "active" (human-approval gate), skips
   * do_not_email recipients, honors the per-site hourly cap, and is
   * idempotent per recipient — re-invoking never double-sends.
   */
  async sendCampaign(siteId: string, campaignId: string) {
    return this.request<CampaignSendResponse>(
      `/api/v1/campaigns/${siteId}/${campaignId}/send`,
      { method: "POST" }
    );
  }

  // Platform Detection & Pixel Install
  async detectPlatform(url: string) {
    return this.request<{
      platform: string;
      confidence: number;
      has_gtm: boolean;
      gtm_id: string | null;
    }>("/api/v1/sites/detect-platform", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  }

  async verifyPixel(siteId: string) {
    return this.request<{
      site_id: string;
      status: string;
      verified: boolean;
      message: string;
    }>(`/api/v1/sites/${siteId}/verify-pixel`, {
      method: "POST",
    });
  }

  async getDetectionPreview(siteId: string) {
    return this.request<{
      site_id: string;
      signals: Array<{
        key: string;
        name: string;
        category: string;
        active: boolean;
        description: string;
      }>;
      total_visitors: number;
    }>(`/api/v1/sites/${siteId}/detection-preview`);
  }

  async shopifyConnect(siteId: string, shopDomain: string) {
    return this.request<{ install_url: string }>(
      `/api/v1/sites/${siteId}/shopify/connect`,
      {
        method: "POST",
        body: JSON.stringify({ shop_domain: shopDomain }),
      }
    );
  }

  async downloadWordPressPlugin(siteId: string): Promise<void> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(
      `${API_BASE}/api/v1/sites/${siteId}/wordpress-plugin`,
      { headers }
    );
    if (!res.ok) throw new Error("Failed to download plugin");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `beam-pixel-${siteId}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  getWordPressPluginUrl(siteId: string): string {
    return `${API_BASE}/api/v1/sites/${siteId}/wordpress-plugin`;
  }

  // Exports — authenticated blob download (the endpoint requires a Bearer
  // token, so a plain link/window.open would 401)
  async downloadExport(
    siteId: string,
    segmentId: string,
    platform: string
  ): Promise<void> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(
      `${API_BASE}/api/v1/exports/${siteId}/${segmentId}?platform=${platform}`,
      { headers }
    );
    if (!res.ok) throw new Error("Failed to download export");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${platform}_audience_${segmentId.slice(0, 8)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // BYOK API Keys
  async listApiKeys() {
    return this.request<ApiKeyInfo[]>("/api/v1/api-keys/");
  }

  async saveApiKey(provider: string, apiKey: string) {
    return this.request<ApiKeyInfo>("/api/v1/api-keys/", {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    });
  }

  async deleteApiKey(provider: string) {
    return this.request<{ status: string }>(`/api/v1/api-keys/${provider}`, {
      method: "DELETE",
    });
  }

  async testApiKey(provider: string) {
    return this.request<{ provider: string; is_valid: boolean; message: string }>(
      `/api/v1/api-keys/${provider}/test`,
      { method: "POST" }
    );
  }

  // Deep Research Enrichment
  async enrichVisitor(siteId: string, visitorId: string) {
    return this.request<{
      status: string;
      completeness?: number;
      message: string;
      social_context?: Record<string, unknown>;
    }>(`/api/v1/visitors/${siteId}/${visitorId}/enrich`, {
      method: "POST",
    });
  }

  // ── EasyEngage: Social Accounts ────────────────────
  async getSocialAccounts() {
    return this.request<SocialAccount[]>("/api/v1/social/accounts/");
  }

  async connectPlatform(platform: Platform) {
    return this.request<{ auth_url: string }>(
      `/api/v1/social/connect/${platform}`
    );
  }

  async disconnectAccount(accountId: string) {
    return this.request<{ message: string }>(
      `/api/v1/social/accounts/${accountId}`,
      { method: "DELETE" }
    );
  }

  // ── EasyEngage: Feed ───────────────────────────────
  async getFeed(
    page = 1,
    platform?: Platform,
    dateFrom?: string,
    dateTo?: string,
    source?: string,
  ) {
    const params = new URLSearchParams({ page: String(page), per_page: "20" });
    if (platform) params.set("platform", platform);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (source) params.set("source", source);
    return this.request<FeedResponse>(`/api/v1/feed?${params}`);
  }

  async triggerSync() {
    return this.request<{ message: string; breakdown: Record<string, number> }>(
      "/api/v1/feed/sync",
      { method: "POST" }
    );
  }

  async importPost(data: {
    url: string;
    platform: Platform;
    content: string;
    author_name: string;
    author_username: string;
  }) {
    return this.request<SocialPost>("/api/v1/feed/import", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  // ── EasyEngage: Drafts ─────────────────────────────
  async getDrafts(status?: DraftStatus) {
    const params = status ? `?status=${status}` : "";
    return this.request<DraftListResponse>(`/api/v1/drafts${params}`);
  }

  async generateDraft(postId: string) {
    return this.request<GenerateMultiDraftResponse>("/api/v1/drafts/generate", {
      method: "POST",
      body: JSON.stringify({ post_id: postId }),
    });
  }

  async approveDraft(draftId: string) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);
    try {
      return await this.request<{ id: string; status: DraftStatus; message: string }>(
        `/api/v1/drafts/${draftId}/approve`,
        { method: "POST", signal: controller.signal }
      );
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async rejectDraft(draftId: string) {
    return this.request<{ id: string; status: DraftStatus; message: string }>(
      `/api/v1/drafts/${draftId}/reject`,
      { method: "POST" }
    );
  }

  // ── EasyTrack + EasyEngage: Campaign creation from segment ─
  async createCampaignFromSegment(siteId: string, segmentId: string) {
    return this.request<Campaign>(
      `/api/v1/campaigns/${siteId}/create/${segmentId}`,
      { method: "POST" }
    );
  }

  async editDraft(draftId: string, editedContent: string) {
    return this.request<SocialDraft>(`/api/v1/drafts/${draftId}/edit`, {
      method: "PUT",
      body: JSON.stringify({ edited_content: editedContent }),
    });
  }

  // ── Engagement ROI ─────────────────────────────────────
  async getEngagementRoi(days = 7) {
    return this.request<EngagementROI>(
      `/api/v1/engagement/roi?days=${days}`
    );
  }

  async trackEngagement(data: {
    platform: string;
    engagement_type: string;
    post_url?: string;
    draft_id?: string;
    site_id: string;
  }) {
    return this.request<{ utm_tag: string }>("/api/v1/engagement/track", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  // ── Waitlist Admin ─────────────────────────────────────
  async getWaitlist() {
    return this.request<WaitlistListResponse>("/api/v1/waitlist/");
  }

  async approveWaitlist(id: string) {
    return this.request<{ status: string; id: string }>(
      `/api/v1/waitlist/${id}/approve`,
      { method: "PATCH" }
    );
  }

  async grantWaitlist(id: string) {
    return this.request<{ status: string; id: string }>(
      `/api/v1/waitlist/${id}/grant`,
      { method: "PATCH" }
    );
  }

  async rejectWaitlist(id: string) {
    return this.request<{ status: string; id: string }>(
      `/api/v1/waitlist/${id}/reject`,
      { method: "PATCH" }
    );
  }

  async deleteWaitlist(id: string) {
    return this.request<{ status: string; id: string }>(
      `/api/v1/waitlist/${id}`,
      { method: "DELETE" }
    );
  }

  // Public: validate an invite token before showing the signup form
  async validateInvite(token: string) {
    return this.request<{ valid: boolean; email?: string | null }>(
      `/api/v1/waitlist/validate-invite?token=${encodeURIComponent(token)}`
    );
  }

  /**
   * Consume an invite token after first sign-in. Returns "consumed" on
   * success and "invalid" on 404 (unknown token, or already used by another
   * user) — both terminal, so callers can discard the stored token. Throws on
   * transient failures (network, 5xx) so callers can retry on a later visit.
   * Idempotent for the same user.
   */
  async consumeInvite(token: string): Promise<"consumed" | "invalid"> {
    const authToken = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/v1/waitlist/consume-invite`, {
        method: "POST",
        headers,
        body: JSON.stringify({ token }),
      });
    } catch (err) {
      throw new Error(
        `Network error: unable to reach API (${(err as Error).message})`
      );
    }
    if (res.status === 404) return "invalid";
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return "consumed";
  }

  // ── Billing ────────────────────────────────────────────
  async createCheckout(plan: BillingPlan, interval: BillingInterval) {
    return this.request<{ checkout_url: string }>("/api/v1/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan, interval }),
    });
  }

  async createPortal() {
    return this.request<{ portal_url: string }>("/api/v1/billing/portal", {
      method: "POST",
    });
  }

  async getBillingStatus() {
    return this.request<BillingStatus>("/api/v1/billing/status");
  }

  // ── Blog CMS ──────────────────────────────────────────
  async getBlogPosts(limit = 20, offset = 0) {
    return this.request<BlogPostListResponse>(
      `/api/v1/blog/posts?limit=${limit}&offset=${offset}`
    );
  }

  async getAdminPosts(limit = 50, offset = 0) {
    return this.request<BlogPostAdminListResponse>(
      `/api/v1/blog/admin/posts?limit=${limit}&offset=${offset}`
    );
  }

  async createPost(data: BlogPostInput) {
    return this.request<BlogPostAdmin>("/api/v1/blog/posts", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updatePost(id: string, data: BlogPostInput) {
    return this.request<BlogPostAdmin>(`/api/v1/blog/posts/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async publishPost(id: string) {
    return this.request<BlogPostAdmin>(`/api/v1/blog/posts/${id}/publish`, {
      method: "POST",
    });
  }

  async unpublishPost(id: string) {
    return this.request<BlogPostAdmin>(`/api/v1/blog/posts/${id}/unpublish`, {
      method: "POST",
    });
  }

  async schedulePost(id: string, scheduledFor: string) {
    return this.request<BlogPostAdmin>(`/api/v1/blog/posts/${id}/schedule`, {
      method: "POST",
      body: JSON.stringify({ scheduled_for: scheduledFor }),
    });
  }

  async deletePost(id: string) {
    return this.request<void>(`/api/v1/blog/posts/${id}`, { method: "DELETE" });
  }

  async uploadImage(file: File): Promise<{ url: string }> {
    // Multipart — must NOT set Content-Type (browser sets the boundary), so
    // this bypasses the JSON `request` helper.
    const token = this.getToken();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/v1/blog/upload`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Upload failed: ${res.status}`);
    }
    return res.json() as Promise<{ url: string }>;
  }
}

export const api = new ApiClient();

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
  created_at: string;
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
}

export interface VisitorDetail extends Visitor {
  email?: string | null;
  full_name?: string | null;
  phone?: string | null;
  city?: string | null;
  region?: string | null;
  country?: string | null;
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
  } | null;
}

export interface VisitorListResponse {
  visitors: Visitor[];
  total: number;
  page: number;
  page_size: number;
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

export interface BrowserBreakdown {
  site_id: string;
  window_days: number;
  total_visitors: number;
  browsers: BrowserRow[];
  safari_coverage: SafariCoverage;
}

export interface SiteStats {
  total_visitors: number;
  identified: number;
  enriched: number;
  could_enrich_more: number;
}

export interface ApiKeyInfo {
  provider: string;
  key_hint: string;
  is_valid: boolean;
  created_at: string;
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
