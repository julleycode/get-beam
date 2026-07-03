import type {
  KnownUploadResult,
  BlogPostAdmin,
  BlogPostListResponse,
  BlogPostAdminListResponse,
  BlogPostInput,
  ChangelogEntryAdmin,
  ChangelogAdminListResponse,
  ChangelogEntryInput,
  ChangelogSyncResponse,
  Site,
  SiteUpdate,
  ConsentMode,
  FeatureRequest,
  FeatureBoardItem,
  FeatureBoardResponse,
  FeatureVoteResult,
  FeatureRequestListResponse,
  VisitorDetail,
  VisitorListResponse,
  VisitorCountry,
  SegmentListResponse,
  Campaign,
  CampaignListResponse,
  CampaignSendResponse,
  CampaignStats,
  BrowserBreakdown,
  TrafficFit,
  SiteKpis,
  SiteTimeseries,
  SiteStats,
  CostSummary,
  ApiKeyInfo,
  CrmConnection,
  CrmPushResult,
  Platform,
  DraftStatus,
  SocialAccount,
  LinkedInOutreachConnectResponse,
  LinkedInOutreachStatus,
  LinkedInOutreachResponse,
  LinkedInOutreachJob,
  LinkedInScheduleResponse,
  LinkedInCampaignDetail,
  SocialPost,
  FeedResponse,
  SocialDraft,
  DraftListResponse,
  GenerateMultiDraftResponse,
  EngagementROI,
  BillingPlan,
  BillingInterval,
  LimitKind,
  WaitlistListResponse,
  BillingStatus,
  CancelSubscriptionResponse,
} from "./api-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;
  private clerkToken: string | null = null;
  // Fetches a FRESH Clerk token on demand (Clerk's getToken). Used to retry
  // once on 401 when the cached token has expired (~60s TTL).
  private clerkTokenGetter: (() => Promise<string | null>) | null = null;

  // ── Clerk token (primary, set by ClerkTokenSync) ────
  setClerkToken(token: string | null) {
    this.clerkToken = token;
  }

  setClerkTokenGetter(fn: (() => Promise<string | null>) | null) {
    this.clerkTokenGetter = fn;
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
    options: RequestInit = {},
    _retried = false
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const method = (options.method ?? "GET").toUpperCase();
    // Only auto-retry idempotent reads. Mutations fail fast so a request the
    // server may have already received is never re-applied.
    const idempotent = method === "GET" || method === "HEAD";

    let res: Response;
    try {
      res = await this.fetchWithRetry(
        `${API_BASE}${path}`,
        { ...options, headers },
        idempotent
      );
    } catch (err) {
      throw new Error(
        `Network error: unable to reach API (${(err as Error).message})`
      );
    }

    // Cached Clerk token expired (~60s TTL) → fetch a fresh one and retry once.
    if (res.status === 401 && !_retried && this.clerkTokenGetter) {
      try {
        const fresh = await this.clerkTokenGetter();
        if (fresh) {
          this.setClerkToken(fresh);
          return this.request<T>(path, options, true);
        }
      } catch {
        // fall through to the standard 401 handling below
      }
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

  /**
   * fetch() with cold-start resilience for idempotent reads.
   *
   * Railway hobby services sleep when idle; the first request after a cold
   * period can hang or return a 502/503/504 while the container wakes. Without
   * this, that surfaces to the user as "Network error: unable to reach API
   * (Failed to fetch)". We give the backend a few seconds to come up:
   *   - a per-attempt timeout turns a hang into a retry (unless the caller
   *     supplied its own AbortSignal);
   *   - network errors and gateway 5xx are retried with exponential backoff.
   * Non-idempotent requests pass straight through (no retry, no timeout) so a
   * mutation is never re-applied.
   */
  private async fetchWithRetry(
    url: string,
    init: RequestInit,
    idempotent: boolean,
    maxAttempts = 3
  ): Promise<Response> {
    if (!idempotent) return fetch(url, init);

    let lastErr: unknown;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const isLast = attempt === maxAttempts - 1;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let attemptInit = init;
      // Add a timeout only when the caller didn't bring its own signal.
      if (!init.signal && typeof AbortController !== "undefined") {
        const ctrl = new AbortController();
        // Escalate per attempt (12s, 24s, 36s). A Railway hobby container
        // sleeps when idle and can take 15-30s to wake; a flat 10s aborted
        // mid-boot on every attempt, surfacing as
        // "Network error: unable to reach API (signal is aborted without reason)".
        // Attempt 0 stays snappy for the warm case; later attempts give a
        // cold-starting backend room to finish booting.
        timer = setTimeout(() => ctrl.abort(), 12_000 * (attempt + 1));
        attemptInit = { ...init, signal: ctrl.signal };
      }
      try {
        const res = await fetch(url, attemptInit);
        if (
          !isLast &&
          (res.status === 502 || res.status === 503 || res.status === 504)
        ) {
          await this.backoff(attempt);
          continue;
        }
        return res;
      } catch (err) {
        lastErr = err;
        if (isLast) throw err;
        await this.backoff(attempt);
      } finally {
        if (timer) clearTimeout(timer);
      }
    }
    // Unreachable — the loop always returns or throws — but satisfies the type.
    throw lastErr;
  }

  // Exponential backoff between retries: ~0.5s, then 1s.
  private backoff(attempt: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
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

  /**
   * Overview in one round-trip: sites + per-site stats (keyed by site_id).
   * Collapses the old listSites + N×getVisitorStats fan-out — matters most for
   * clients far from the US origin. Falls back to listSites at the call site if
   * this endpoint isn't deployed yet.
   */
  async getDashboardOverview() {
    return this.request<{ sites: Site[]; stats: Record<string, SiteStats> }>(
      "/api/v1/dashboard/overview"
    );
  }

  async getSite(siteId: string) {
    return this.request<Site>(`/api/v1/sites/${siteId}`);
  }

  // Permanently delete a site and ALL of its data. Destructive + irreversible.
  async deleteSite(siteId: string) {
    return this.request<void>(`/api/v1/sites/${siteId}`, { method: "DELETE" });
  }

  // Toggle the per-site auto-identify sweep on/off.
  async setAutoIdentify(siteId: string, enabled: boolean) {
    return this.request<Site>(`/api/v1/sites/${siteId}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_identify_enabled: enabled }),
    });
  }

  // Toggle the per-site hot-visitor email ping on/off.
  async setHotAlert(siteId: string, enabled: boolean) {
    return this.request<Site>(`/api/v1/sites/${siteId}`, {
      method: "PATCH",
      body: JSON.stringify({ hot_alert_enabled: enabled }),
    });
  }

  // Set the per-site cookie-consent mode (off | eu | all | cmp).
  async setConsentMode(siteId: string, mode: ConsentMode) {
    return this.request<Site>(`/api/v1/sites/${siteId}`, {
      method: "PATCH",
      body: JSON.stringify({ consent_mode: mode }),
    });
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
      enrichment_status?: string;
      country?: string;
      visitor_type?: string; // "new" | "returning" (by session count)
      known?: boolean; // true = in the owner's known-contacts list
      // Date bounds as "YYYY-MM-DD". *_to is exclusive — pass the day AFTER the
      // chosen end date (see nextDay() on the Visitors page) to include it.
      first_seen_from?: string;
      first_seen_to?: string;
      last_seen_from?: string;
      last_seen_to?: string;
      min_intent?: number;
      sort_by?: string;
    } = {}
  ) {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.page_size) query.set("page_size", String(params.page_size));
    if (params.identity_status) query.set("identity_status", params.identity_status);
    if (params.enrichment_status) query.set("enrichment_status", params.enrichment_status);
    if (params.country) query.set("country", params.country);
    if (params.visitor_type) query.set("visitor_type", params.visitor_type);
    if (params.known !== undefined) query.set("known", String(params.known));
    if (params.first_seen_from) query.set("first_seen_from", params.first_seen_from);
    if (params.first_seen_to) query.set("first_seen_to", params.first_seen_to);
    if (params.last_seen_from) query.set("last_seen_from", params.last_seen_from);
    if (params.last_seen_to) query.set("last_seen_to", params.last_seen_to);
    if (params.min_intent !== undefined) query.set("min_intent", String(params.min_intent));
    if (params.sort_by) query.set("sort_by", params.sort_by);

    return this.request<VisitorListResponse>(
      `/api/v1/visitors/${siteId}?${query.toString()}`
    );
  }

  // Countries (with counts) for this site's visitors — populates the filter
  // dropdown. Counts are faceted: pass the other active filters so each count
  // reflects what the list would actually show (the country filter itself is
  // deliberately excluded server-side).
  async getVisitorCountries(
    siteId: string,
    params: {
      identity_status?: string;
      enrichment_status?: string;
      visitor_type?: string;
      known?: boolean;
      first_seen_from?: string;
      first_seen_to?: string;
      last_seen_from?: string;
      last_seen_to?: string;
      min_intent?: number;
    } = {}
  ) {
    const query = new URLSearchParams();
    if (params.identity_status) query.set("identity_status", params.identity_status);
    if (params.enrichment_status) query.set("enrichment_status", params.enrichment_status);
    if (params.visitor_type) query.set("visitor_type", params.visitor_type);
    if (params.known !== undefined) query.set("known", String(params.known));
    if (params.first_seen_from) query.set("first_seen_from", params.first_seen_from);
    if (params.first_seen_to) query.set("first_seen_to", params.first_seen_to);
    if (params.last_seen_from) query.set("last_seen_from", params.last_seen_from);
    if (params.last_seen_to) query.set("last_seen_to", params.last_seen_to);
    if (params.min_intent !== undefined) query.set("min_intent", String(params.min_intent));
    const qs = query.toString();
    return this.request<VisitorCountry[]>(
      `/api/v1/visitors/${siteId}/countries${qs ? `?${qs}` : ""}`
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

  async getTrafficFit(siteId: string, windowDays = 30) {
    return this.request<TrafficFit>(
      `/api/v1/sites/${siteId}/traffic-fit?window_days=${windowDays}`
    );
  }

  async getSiteKpis(siteId: string, days = 30) {
    return this.request<SiteKpis>(`/api/v1/sites/${siteId}/kpis?days=${days}`);
  }

  async getSiteTimeseries(siteId: string, days = 30) {
    return this.request<SiteTimeseries>(
      `/api/v1/sites/${siteId}/timeseries?days=${days}`
    );
  }

  // Per-user dashboard widget layout (synced across devices). `layout` is null
  // when the user hasn't customised the surface → client uses its default.
  async getWidgetLayout(surface = "visitors") {
    return this.request<{ surface: string; layout: string[] | null }>(
      `/api/v1/auth/widget-layout?surface=${encodeURIComponent(surface)}`
    );
  }

  async saveWidgetLayout(layout: string[], surface = "visitors") {
    return this.request<{ surface: string; layout: string[] }>(
      `/api/v1/auth/widget-layout`,
      { method: "PUT", body: JSON.stringify({ surface, layout }) }
    );
  }

  async getCostSummary(siteId: string, days = 30) {
    return this.request<CostSummary>(
      `/api/v1/costs/${siteId}/summary?days=${days}`
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

  async deleteSegment(siteId: string, segmentId: string) {
    return this.request<void>(`/api/v1/segments/${siteId}/${segmentId}`, {
      method: "DELETE",
    });
  }

  // Campaigns
  async listCampaigns(siteId: string, includeArchived = false) {
    const qs = includeArchived ? "?include_archived=true" : "";
    return this.request<CampaignListResponse>(`/api/v1/campaigns/${siteId}${qs}`);
  }

  async getCampaign(siteId: string, campaignId: string) {
    return this.request<Campaign>(`/api/v1/campaigns/${siteId}/${campaignId}`);
  }

  /** Hide a campaign from the default list (reversible via unarchiveCampaign). */
  async archiveCampaign(siteId: string, campaignId: string) {
    return this.request<Campaign>(
      `/api/v1/campaigns/${siteId}/${campaignId}/archive`,
      { method: "POST" }
    );
  }

  /** Restore an archived campaign back to draft. */
  async unarchiveCampaign(siteId: string, campaignId: string) {
    return this.request<Campaign>(
      `/api/v1/campaigns/${siteId}/${campaignId}/unarchive`,
      { method: "POST" }
    );
  }

  /** Permanently delete a campaign and its touchpoints. */
  async deleteCampaign(siteId: string, campaignId: string) {
    return this.request<void>(`/api/v1/campaigns/${siteId}/${campaignId}`, {
      method: "DELETE",
    });
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

  /**
   * One-click launch ("Start beam"): approve + activate + send in one action.
   * The confirm dialog before calling this is the human-approval gate.
   * Idempotent per recipient — calling again only reaches new segment members.
   */
  async startCampaign(siteId: string, campaignId: string) {
    return this.request<CampaignSendResponse>(
      `/api/v1/campaigns/${siteId}/${campaignId}/start`,
      { method: "POST" }
    );
  }

  /** Send a [TEST]-prefixed preview of the campaign email to an admin address. */
  async testSendCampaign(siteId: string, campaignId: string, email: string) {
    return this.request<{ sent: boolean; to: string }>(
      `/api/v1/campaigns/${siteId}/${campaignId}/test-send`,
      { method: "POST", body: JSON.stringify({ email }) }
    );
  }

  /** Email engagement stats (sent/opened/clicked) + recipients who returned. */
  async getCampaignStats(siteId: string, campaignId: string) {
    return this.request<CampaignStats>(
      `/api/v1/campaigns/${siteId}/${campaignId}/stats`
    );
  }

  // ── Connect-Gmail: send campaign email from the owner's own Gmail ──
  /** Whether the current user has connected a Gmail to send from. */
  async getEmailSenderStatus() {
    return this.request<{ connected: boolean; email: string | null; configured: boolean }>(
      `/api/v1/email/status`
    );
  }

  /** Start the Gmail OAuth flow; returns the Google consent URL to redirect to. */
  async connectGmail() {
    return this.request<{ auth_url: string }>(`/api/v1/email/connect/google`);
  }

  async disconnectGmail() {
    return this.request<{ disconnected: boolean }>(`/api/v1/email/disconnect`, {
      method: "POST",
    });
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

  // Partial site update (PATCH). Used by the offboarding "pause tracking" toggle
  // and any other per-site field. Returns the updated site.
  async updateSite(siteId: string, patch: Partial<SiteUpdate>) {
    return this.request<Site>(`/api/v1/sites/${siteId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
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

  // CRM connectors — push identified visitors OUT to a CRM / webhook
  async listCrmConnections(siteId: string) {
    return this.request<CrmConnection[]>(`/api/v1/crm/${siteId}/connections`);
  }

  async saveGenericWebhook(siteId: string, webhookUrl: string, secret: string) {
    return this.request<CrmConnection>(
      `/api/v1/crm/${siteId}/connections/generic_webhook`,
      {
        method: "PUT",
        body: JSON.stringify({ webhook_url: webhookUrl, secret }),
      }
    );
  }

  async connectCrm(siteId: string, provider: string) {
    return this.request<{ auth_url: string }>(
      `/api/v1/crm/${siteId}/connections/${provider}/connect`,
      { method: "POST" }
    );
  }

  async testCrmConnection(siteId: string, provider: string) {
    return this.request<{ provider: string; is_valid: boolean; message: string }>(
      `/api/v1/crm/${siteId}/connections/${provider}/test`,
      { method: "POST" }
    );
  }

  async pushSegmentToCrm(siteId: string, provider: string, segmentId: string) {
    return this.request<CrmPushResult>(
      `/api/v1/crm/${siteId}/connections/${provider}/push`,
      {
        method: "POST",
        body: JSON.stringify({ segment_id: segmentId }),
      }
    );
  }

  async disconnectCrm(siteId: string, provider: string) {
    return this.request<{ status: string }>(
      `/api/v1/crm/${siteId}/connections/${provider}`,
      { method: "DELETE" }
    );
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

  // Per-visitor identity resolution (one-click Identify on a list row).
  // Burns one paid lookup; backend enforces the daily + monthly budgets.
  async resolveVisitor(siteId: string, visitorId: string) {
    return this.request<{
      status: string;
      message?: string;
      email?: string | null;
      full_name?: string | null;
      skip_reason?: string;
      // Present only on limit outcomes. "monthly_plan" is the upgrade moment;
      // "daily_budget" is BYOK-only (daily caps don't differ by tier).
      limit_kind?: LimitKind;
    }>(`/api/v1/visitors/${siteId}/${visitorId}/resolve`, {
      method: "POST",
    });
  }

  // Deep Research Enrichment
  async enrichVisitor(siteId: string, visitorId: string) {
    return this.request<{
      status: string;
      completeness?: number;
      message: string;
      social_context?: Record<string, unknown>;
      limit_kind?: LimitKind;
    }>(`/api/v1/visitors/${siteId}/${visitorId}/enrich`, {
      method: "POST",
    });
  }

  // OSINT account scan (free stacked engines: user-scanner + holehe)
  async osintScan(siteId: string, visitorId: string, force = false) {
    const qs = force ? "?force=true" : "";
    return this.request<{ status: string; message?: string }>(
      `/api/v1/visitors/${siteId}/${visitorId}/osint-scan${qs}`,
      { method: "POST" },
    );
  }

  // Full social-resolution pipeline (free OSINT + Maigret + rules → paid → Gemini)
  async resolveSocial(siteId: string, visitorId: string, force = false) {
    const qs = force ? "?force=true" : "";
    return this.request<{ status: string; message?: string }>(
      `/api/v1/visitors/${siteId}/${visitorId}/resolve-social${qs}`,
      { method: "POST" },
    );
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

  // ── LinkedIn outreach (via phantommm sidecar) ──────
  /**
   * Register a LinkedIn `li_at` session cookie + User-Agent with the phantommm
   * sidecar. Beam never stores the raw cookie — only the opaque connection id.
   * The cookie is never returned.
   */
  async enableLinkedInOutreach(
    sessionCookie: string,
    userAgent: string,
    label?: string
  ) {
    return this.request<LinkedInOutreachConnectResponse>(
      "/api/v1/social/accounts/linkedin/outreach-connect",
      {
        method: "POST",
        body: JSON.stringify({
          session_cookie: sessionCookie,
          user_agent: userAgent,
          label,
        }),
      }
    );
  }

  /** Whether the caller has a usable LinkedIn outreach connection. */
  async getLinkedInOutreachStatus() {
    return this.request<LinkedInOutreachStatus>(
      "/api/v1/social/accounts/linkedin/outreach-status"
    );
  }

  /**
   * Send LinkedIn connection requests to a campaign's segment audience via
   * phantommm. dryRun defaults ON — pass dryRun: false to send for real.
   */
  async sendLinkedInOutreach(
    siteId: string,
    campaignId: string,
    opts: { dryRun: boolean; limit: number; action: "connect" | "message" }
  ) {
    return this.request<LinkedInOutreachResponse>(
      `/api/v1/campaigns/${siteId}/${campaignId}/linkedin-outreach`,
      {
        method: "POST",
        body: JSON.stringify({
          dry_run: opts.dryRun,
          limit: opts.limit,
          action: opts.action,
        }),
      }
    );
  }

  /** Poll a LinkedIn outreach job's status. */
  async getLinkedInOutreachJob(
    siteId: string,
    campaignId: string,
    jobId: string
  ) {
    return this.request<LinkedInOutreachJob>(
      `/api/v1/campaigns/${siteId}/${campaignId}/linkedin-outreach/${jobId}`
    );
  }

  /**
   * Schedule a durable LinkedIn drip campaign that STARTS after the step's
   * suggested delay, then sends within daily limits. dryRun defaults ON — pass
   * dryRun: false to schedule for real.
   */
  async scheduleLinkedInOutreach(
    siteId: string,
    campaignId: string,
    opts: { dryRun: boolean; limit: number; action: "connect" | "message" }
  ) {
    return this.request<LinkedInScheduleResponse>(
      `/api/v1/campaigns/${siteId}/${campaignId}/linkedin-outreach/schedule`,
      {
        method: "POST",
        body: JSON.stringify({
          dry_run: opts.dryRun,
          limit: opts.limit,
          action: opts.action,
        }),
      }
    );
  }

  /** Fetch a durable LinkedIn drip campaign's status. */
  async getLinkedInCampaign(
    siteId: string,
    campaignId: string,
    phantommmCampaignId: string
  ) {
    return this.request<LinkedInCampaignDetail>(
      `/api/v1/campaigns/${siteId}/${campaignId}/linkedin-outreach/campaign/${phantommmCampaignId}`
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
    // Generation can take a while on the backend (AI provider + model
    // fallbacks). The backend caps itself at ~90s, so abort slightly after
    // that as a safety net — otherwise a network-level stall would leave the
    // "Generating..." button spinning forever (no per-attempt timeout applies
    // to POSTs in fetchWithRetry).
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 100_000);
    try {
      return await this.request<GenerateMultiDraftResponse>(
        "/api/v1/drafts/generate",
        {
          method: "POST",
          body: JSON.stringify({ post_id: postId }),
          signal: controller.signal,
        }
      );
    } finally {
      clearTimeout(timeoutId);
    }
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

  async retryDraft(draftId: string) {
    // Re-sending can be slow (token refresh + platform call), mirror approve's
    // client-side abort so a stalled network doesn't hang the button forever.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);
    try {
      return await this.request<{ id: string; status: DraftStatus; message: string }>(
        `/api/v1/drafts/${draftId}/retry`,
        { method: "POST", signal: controller.signal }
      );
    } finally {
      clearTimeout(timeoutId);
    }
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

  async cancelSubscription(reason?: string) {
    return this.request<CancelSubscriptionResponse>("/api/v1/billing/cancel", {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
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

  // ── Changelog ─────────────────────────────────────────
  async getAdminChangelog(limit = 50, offset = 0) {
    return this.request<ChangelogAdminListResponse>(
      `/api/v1/changelog/admin/entries?limit=${limit}&offset=${offset}`
    );
  }

  async createChangelog(data: ChangelogEntryInput) {
    return this.request<ChangelogEntryAdmin>("/api/v1/changelog/entries", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateChangelog(id: string, data: ChangelogEntryInput) {
    return this.request<ChangelogEntryAdmin>(`/api/v1/changelog/entries/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async publishChangelog(id: string) {
    return this.request<ChangelogEntryAdmin>(`/api/v1/changelog/entries/${id}/publish`, {
      method: "POST",
    });
  }

  async unpublishChangelog(id: string) {
    return this.request<ChangelogEntryAdmin>(`/api/v1/changelog/entries/${id}/unpublish`, {
      method: "POST",
    });
  }

  async deleteChangelog(id: string) {
    return this.request<void>(`/api/v1/changelog/entries/${id}`, { method: "DELETE" });
  }

  async syncChangelog(limit = 30) {
    return this.request<ChangelogSyncResponse>(
      `/api/v1/changelog/sync?limit=${limit}`,
      { method: "POST" }
    );
  }

  async uploadImage(file: File): Promise<{ url: string }> {
    // Multipart — must NOT set Content-Type (browser sets the boundary), so
    // this bypasses the JSON `request` helper.
    const form = new FormData();
    form.append("file", file);

    const send = (token: string | null) =>
      fetch(`${API_BASE}/api/v1/blog/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

    let res = await send(this.getToken());

    // Cached Clerk token expired → fetch a fresh one and retry once.
    if (res.status === 401 && this.clerkTokenGetter) {
      try {
        const fresh = await this.clerkTokenGetter();
        if (fresh) {
          this.setClerkToken(fresh);
          res = await send(fresh);
        }
      } catch {
        // fall through to the error handling below
      }
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Upload failed: ${res.status}`);
    }
    return res.json() as Promise<{ url: string }>;
  }

  // ── Known contacts (the owner's existing-customer list, stored hashed) ──
  async uploadKnownContacts(siteId: string, file: File): Promise<KnownUploadResult> {
    // Multipart — bypass the JSON request helper (browser sets the boundary).
    const form = new FormData();
    form.append("file", file);

    const send = (token: string | null) =>
      fetch(`${API_BASE}/api/v1/sites/${siteId}/known-contacts/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

    let res = await send(this.getToken());
    if (res.status === 401 && this.clerkTokenGetter) {
      try {
        const fresh = await this.clerkTokenGetter();
        if (fresh) {
          this.setClerkToken(fresh);
          res = await send(fresh);
        }
      } catch {
        // fall through to the error handling below
      }
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Upload failed: ${res.status}`);
    }
    return res.json() as Promise<KnownUploadResult>;
  }

  async getKnownCount(siteId: string) {
    return this.request<{ count: number }>(
      `/api/v1/sites/${siteId}/known-contacts/count`
    );
  }

  async clearKnownContacts(siteId: string) {
    return this.request<{ deleted: number }>(
      `/api/v1/sites/${siteId}/known-contacts`,
      { method: "DELETE" }
    );
  }

  // ── AI assistant (Overview "ask Beam anything" box) ────
  async askAI(question: string, siteId?: string) {
    return this.request<{ answer: string }>("/api/v1/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, site_id: siteId ?? null }),
    });
  }
}

export const api = new ApiClient();

export type {
  KnownUploadResult,
  BlogPost,
  BlogPostAdmin,
  BlogPostListResponse,
  BlogPostAdminListResponse,
  BlogPostInput,
  ChangelogEntry,
  ChangelogEntryAdmin,
  ChangelogCategory,
  ChangelogAdminListResponse,
  ChangelogEntryInput,
  ChangelogSyncResponse,
  Site,
  SiteUpdate,
  ConsentMode,
  FeatureRequest,
  FeatureBoardItem,
  FeatureBoardResponse,
  FeatureVoteResult,
  FeatureRequestListResponse,
  Visitor,
  VisitorDetail,
  SocialResolution,
  OsintAccount,
  OsintScan,
  VisitorListResponse,
  VisitorCountry,
  Segment,
  SegmentListResponse,
  Campaign,
  CampaignListResponse,
  CampaignSendSummary,
  CampaignSendResponse,
  CampaignStats,
  ReturnedVisitor,
  BrowserRow,
  SafariCoverage,
  BrowserMetrics,
  BrowserBreakdown,
  CountryShare,
  TrafficFit,
  SiteKpis,
  TimeseriesPoint,
  SiteTimeseries,
  SiteStats,
  CostProviderRow,
  CostCategoryRow,
  CostDayRow,
  CostSummary,
  ApiKeyInfo,
  CrmProvider,
  CrmConnection,
  CrmPushResult,
  Platform,
  DraftStatus,
  SocialAccount,
  LinkedInOutreachConnectResponse,
  LinkedInOutreachStatus,
  LinkedInOutreachResponse,
  LinkedInOutreachJob,
  LinkedInScheduleResponse,
  LinkedInCampaignDetail,
  SocialPost,
  FeedResponse,
  SocialDraft,
  DraftListResponse,
  GenerateMultiDraftResponse,
  EngagementROI,
  BillingPlan,
  BillingInterval,
  LimitKind,
  WaitlistSignup,
  WaitlistListResponse,
  BillingStatus,
  CancelSubscriptionResponse,
} from "./api-types";
