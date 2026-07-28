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

import re
from typing import NamedTuple

# Known AI-agent vendor tokens (all lowercase). The UA is lowercased before
# comparison, so matching is case-insensitive. Non-OpenAI/Anthropic/Perplexity/
# ByteSpider vendors (e.g. bedrock-agentcore, agentcore, shap-user) are
# intentionally drop-only for v1 — v1 backlog per SPEC Resolved Open Question 6.
#
# Ordered tuples, NOT sets: a UA can contain more than one token (a spoofed
# "GPTBot ChatGPT-User" string, say), and set iteration order follows string
# hashes, which Python randomizes per process. That would make the returned
# token — and therefore the tier — differ between restarts for the same input,
# so the same evidence would not classify the same way twice.
#
# Within a vendor, longest token first, so the most specific match wins:
# ``chatgpt-user`` is decided before the shorter ``gptbot`` can claim it.
_VENDOR_TOKENS: dict[str, tuple[str, ...]] = {
    "openai": ("oai-searchbot", "chatgpt-user", "gptbot"),
    "anthropic": ("claude-searchbot", "anthropic-ai", "claude-user", "claudebot"),
    "perplexity": ("perplexity-user", "perplexitybot"),
    "bytespider": ("bytespider",),
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
    "google": ("google-cloudvertexbot",),
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
#
# The three ``*-user`` tokens are the only per-query fetches their vendors
# document. The ``*-searchbot`` tokens are NOT: OpenAI describes OAI-SearchBot as
# "used to surface websites in search results in ChatGPT's search features" — an
# automatic crawler, not a live fetch — and Anthropic describes Claude-SearchBot
# as crawling to build an indexed corpus for search. Both are index-tier.
# ``anthropic-ai`` is the crawler token of the same "anthropic" vendor set.
_ON_DEMAND_TOKENS: frozenset[str] = frozenset({
    "chatgpt-user", "claude-user", "perplexity-user",
})


# Bot User-Agents conventionally carry a self-describing URL in a comment, e.g.
# ``Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)``. That URL
# is not a product token, and matching against it means any UA whose comment URL
# merely mentions a vendor — a scanner advertising ``/gptbot-detector``, say —
# would be classified as that vendor. Genuine agents still match on the product
# token itself, which sits outside the URL.
_URL_RE = re.compile(r"\w+://\S*")

# Token boundary: a vendor token must not be a fragment of a longer run of
# token characters. Hyphens are part of the tokens themselves (``chatgpt-user``),
# so the boundary class is letters/digits/hyphen/underscore/dot rather than the
# regex ``\b`` word boundary, which would treat a hyphen as a separator.
_TOKEN_CHARS = r"[A-Za-z0-9._-]"


def _strip_urls(ua: str) -> str:
    """Remove self-describing URLs from a UA before token matching."""
    return _URL_RE.sub(" ", ua)


def _contains_token(ua: str, token: str) -> bool:
    """True iff ``token`` appears in ``ua`` as a whole token, not a fragment."""
    pattern = rf"(?<!{_TOKEN_CHARS}){re.escape(token)}(?!{_TOKEN_CHARS})"
    return re.search(pattern, ua) is not None


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
    ua = _strip_urls(user_agent.lower())
    for vendor, tokens in _VENDOR_TOKENS.items():
        for token in tokens:
            if _contains_token(ua, token):
                return AgentClassification(
                    vendor=vendor,
                    product_or_ua_token=token,
                    verification_method="ua-only",
                )
    return None
