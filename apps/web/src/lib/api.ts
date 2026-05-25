const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_token", token);
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem("auth_token");
    }
    return this.token;
  }

  clearToken() {
    this.token = null;
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

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      this.clearToken();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
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
    return this.request<{ id: string; email: string; full_name: string | null }>(
      "/api/v1/auth/me"
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
    a.download = `retargetagent-pixel-${siteId}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  getWordPressPluginUrl(siteId: string): string {
    return `${API_BASE}/api/v1/sites/${siteId}/wordpress-plugin`;
  }

  // Exports
  getExportUrl(siteId: string, segmentId: string, platform: string): string {
    return `${API_BASE}/api/v1/exports/${siteId}/${segmentId}?platform=${platform}`;
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

  // Tier 2 Enrichment
  async enrichVisitor(siteId: string, visitorId: string) {
    return this.request<{
      status: string;
      completeness?: number;
      message: string;
    }>(`/api/v1/visitors/${siteId}/${visitorId}/enrich`, {
      method: "POST",
    });
  }
}

export const api = new ApiClient();

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
