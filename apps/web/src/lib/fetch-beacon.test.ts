import { describe, it, expect } from "vitest";
import {
  matchFetchBeacon,
  matchOnDemandUa,
  isTopLevelDocumentPath,
  extractToken,
  ON_DEMAND_UA_TOKENS,
} from "./fetch-beacon";

// AC-H5-10: the middleware fires the beacon ONLY on a GET + recognized
// on-demand fetcher UA + top-level document path — never on static assets,
// RSC prefetches, /api, or /trpc; never on non-fetcher / index-crawler UAs.

const SITE = "site_abc";
const CHATGPT = "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)";

function match(
  overrides: Partial<{
    method: string;
    userAgent: string | null;
    pathname: string;
    search: string;
  }> = {}
) {
  return matchFetchBeacon({
    method: overrides.method ?? "GET",
    userAgent: overrides.userAgent ?? CHATGPT,
    pathname: overrides.pathname ?? "/pricing",
    search: overrides.search ?? "",
    siteId: SITE,
  });
}

describe("matchOnDemandUa", () => {
  it.each([...ON_DEMAND_UA_TOKENS])("matches on-demand token %s (case-insensitive)", (tok) => {
    expect(matchOnDemandUa(`something ${tok.toUpperCase()} else`)).toBe(true);
  });

  it.each([
    "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)", // index crawler
    "Mozilla/5.0 (compatible; Googlebot/2.1)",
    "Google-CloudVertexBot", // H5 google vendor is index-tier — must NOT fire
    "curl/7.88.1",
    "Mozilla/5.0 (Macintosh) Chrome/120.0", // real human browser
  ])("does not match non-on-demand UA %s", (ua) => {
    expect(matchOnDemandUa(ua)).toBe(false);
  });

  it("returns false for null/empty UA", () => {
    expect(matchOnDemandUa(null)).toBe(false);
    expect(matchOnDemandUa("")).toBe(false);
    expect(matchOnDemandUa(undefined)).toBe(false);
  });
});

describe("isTopLevelDocumentPath", () => {
  it.each(["/", "/pricing", "/blog/post-1", "/pricing-overview/p1abc"])(
    "accepts document path %s",
    (p) => expect(isTopLevelDocumentPath(p, "")).toBe(true)
  );

  it.each([
    ["/api", ""],
    ["/api/v1/agents/site", ""],
    ["/trpc", ""],
    ["/trpc/foo", ""],
    ["/_next/static/chunk.js", ""],
    ["/favicon.ico", ""],
    ["/robots.txt", ""],
    ["/sitemap.xml", ""],
    ["/styles.css", ""],
    ["/pricing", "?_rsc=abcd"], // RSC prefetch marker
  ])("rejects non-document path %s%s", (p, s) => {
    expect(isTopLevelDocumentPath(p, s)).toBe(false);
  });
});

describe("extractToken", () => {
  it("extracts the mint token from a tokenized probe path", () => {
    expect(extractToken("/pricing-overview/p1abc2xy")).toBe("p1abc2xy");
  });
  it("returns null for non-token paths", () => {
    expect(extractToken("/pricing-overview")).toBeNull();
    expect(extractToken("/pricing")).toBeNull();
    expect(extractToken("/pricing-overview/BADTOKEN")).toBeNull();
  });
});

describe("matchFetchBeacon (full truth table)", () => {
  it("fires on GET + on-demand UA + document path", () => {
    const p = match({ pathname: "/pricing" });
    expect(p).not.toBeNull();
    expect(p).toMatchObject({ site_id: SITE, user_agent: CHATGPT, path: "/pricing", token: null });
  });

  it("carries the decoded token for the probe page", () => {
    const p = match({ pathname: "/pricing-overview/p1abc" });
    expect(p?.token).toBe("p1abc");
  });

  it.each(["POST", "HEAD", "OPTIONS"])("does not fire on non-GET method %s", (m) => {
    expect(match({ method: m })).toBeNull();
  });

  it("does not fire for an index-crawler UA (gptbot)", () => {
    expect(match({ userAgent: "GPTBot/1.0" })).toBeNull();
  });

  it("does not fire for a human browser UA", () => {
    expect(match({ userAgent: "Mozilla/5.0 Chrome/120" })).toBeNull();
  });

  it.each([
    ["/api/v1/agents/x", ""],
    ["/trpc/foo", ""],
    ["/_next/static/x.js", ""],
    ["/logo.png", ""],
    ["/pricing", "?_rsc=1"],
  ])("does not fire on non-document request %s%s even with on-demand UA", (p, s) => {
    expect(match({ pathname: p, search: s })).toBeNull();
  });
});
