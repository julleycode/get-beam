"""Classify a live-traffic User-Agent as a known AI-agent vendor visit.

Pure, stateless, DB-free. Distinct from ``bot_filter.py``'s drop-only concern:
this module recognizes a small allowlist of AI-agent vendor tokens (OpenAI,
Anthropic, Perplexity, ByteSpider) and returns a classification so the ingest
path (Phase 2) can persist them as agent visits instead of silently dropping
them. Everything else — generic bots, scrapers, curl, non-allowlisted AI
vendors — returns ``None`` and stays ``bot_filter.py``'s drop-only concern
(unchanged in this phase).

Does NOT import, reference, or mutate ``bot_filter.py._BOT_PATTERN`` — the
classifier is additive and independent (confirmed via RESEARCH). Reconciling the
drop-vs-classify ordering is explicitly Phase 2's filter-ordering requirement
(SPEC AC4), not this module's job.
"""

from typing import NamedTuple

# Known AI-agent vendor tokens (all lowercase). The UA is lowercased before
# comparison, so matching is case-insensitive. Non-OpenAI/Anthropic/Perplexity/
# ByteSpider vendors (e.g. bedrock-agentcore, agentcore, shap-user) are
# intentionally drop-only for v1 — v1 backlog per SPEC Resolved Open Question 6.
_VENDOR_TOKENS: dict[str, frozenset[str]] = {
    "openai": frozenset({"gptbot", "chatgpt-user", "oai-searchbot"}),
    "anthropic": frozenset({"claudebot", "anthropic-ai", "claude-user", "claude-searchbot"}),
    "perplexity": frozenset({"perplexitybot", "perplexity-user"}),
    "bytespider": frozenset({"bytespider"}),
    # Google/Gemini (Handoff Detection H5, D-A). Added conservatively: the exact
    # live Gemini/Google *on-demand* fetch UA token is UNVERIFIED (KG-3). The
    # only documented Google user/owner-triggered fetcher is
    # ``Google-CloudVertexBot`` (fetches sites on demand for Vertex AI Agents) —
    # allowlisted here but kept INDEX-tier (NOT in _ON_DEMAND_TOKENS) so a
    # crawler is never mislabeled as a live human-behind-the-agent fetch. Deliberately
    # NOT ``google-extended``/``applebot-extended`` — those are robots.txt AI-control
    # directives, not real fetch UAs (see test_agent_classifier AC13 exclusion), and
    # must never classify. Promote to on-demand only after a real fetch UA is
    # confirmed from live logs (KG-3 backlog stub).
    "google": frozenset({"google-cloudvertexbot"}),
}

# Verification tiers. Phase 1 always returns "ua-only"; Phase 4 adds the other
# tiers. Forward-declared contract for Phase 4 to import and validate against —
# not consumed for validation within Phase 1.
VERIFICATION_METHODS: tuple[str, ...] = ("ua-only", "ip-verified", "rdns-verified")

# On-demand vs index tier split (Handoff Detection H1). "on-demand" tokens are
# live-fetch-on-user-query bots — a real human is behind the request right now
# (the signal every downstream handoff-correlation phase depends on). Everything
# else in _VENDOR_TOKENS is an "index"/crawler token.
#
# Conservative asymmetry: only tokens KNOWN to be user-driven live fetches are
# on-demand; the default (else-branch) is "index". Mislabeling a crawler as
# on-demand would fabricate a human-intent signal, so the safe default is index.
# Notably ``claude-searchbot`` is on-demand (Anthropic's live user-query fetch,
# analogous to oai-searchbot/perplexity-user) while ``anthropic-ai`` — a distinct
# token in the same "anthropic" vendor set — is the crawler/index token.
_ON_DEMAND_TOKENS: frozenset[str] = frozenset({
    "chatgpt-user", "oai-searchbot", "claude-user", "claude-searchbot", "perplexity-user",
})


def classify_tier(raw_ua_token: str) -> str:
    """Return "on-demand" or "index" for a known vendor token.

    Total function over the 10 tokens in ``_VENDOR_TOKENS`` — every token has
    an explicit tier (see the completeness test ``test_tier_map_covers_all_vendor_tokens``).
    Callers must only pass a token already confirmed non-None by ``classify_agent()``.
    """
    return "on-demand" if raw_ua_token in _ON_DEMAND_TOKENS else "index"


class AgentClassification(NamedTuple):
    vendor: str
    product_or_ua_token: str
    verification_method: str


def classify_agent(user_agent: str | None) -> AgentClassification | None:
    """Classify a User-Agent string as a known AI-agent vendor visit.

    Returns an ``AgentClassification`` (with ``verification_method="ua-only"``)
    for the first matching vendor token, or ``None`` for a missing/empty UA or a
    UA that matches no known vendor token.
    """
    if not user_agent or not user_agent.strip():
        return None
    ua = user_agent.lower()
    for vendor, tokens in _VENDOR_TOKENS.items():
        for token in tokens:
            if token in ua:
                return AgentClassification(
                    vendor=vendor,
                    product_or_ua_token=token,
                    verification_method="ua-only",
                )
    return None
