"""Classify a human visit's first-touch referrer as an AI answer-engine citation.

Pure, stateless, DB-free (mirrors the standalone ``agent_classifier.py``). When
an AI answer engine (ChatGPT, Perplexity, Gemini, …) cites a site and a HUMAN
clicks the citation, that click is an ordinary browser visit carrying
``document.referrer = <AI engine host>``. This module maps that host to a short
label so the visit can be attributed to the engine that sent it.

``ai_source`` is ADDITIVE ATTRIBUTION METADATA ONLY. It MUST NOT set
``source_agent_visit_id``, MUST NOT gate emailability, and MUST NOT touch any
Phase 7 guardrail. AI-referred humans are ordinary human visits
(``source_agent_visit_id = NULL``) → emailable via the existing pipeline.

Does NOT import, reference, or mutate any DB model or the agent-detection stack.
"""

from urllib.parse import urlparse

# Registrable-domain (hostname) suffix → attribution label. The referrer host is
# lowercased and stripped of a leading ``www.`` before matching, then compared by
# suffix so subdomains (e.g. ``gemini.google.com``) match their own entry and any
# deeper host still resolves to the right engine.
#
# Deliberately EXCLUDES bare ``google.com`` / ``bing.com`` / ``openai.com``:
# Google AI-Overviews and Bing Copilot answer IN-SERP, so their referrer is
# indistinguishable from ordinary organic search — attributing them would be a
# false positive. Honest coverage limit (precedent: ``_coverage_note``).
AI_REFERRER_DOMAINS: dict[str, str] = {
    "chatgpt.com": "chatgpt",
    "chat.openai.com": "chatgpt",
    "perplexity.ai": "perplexity",
    "gemini.google.com": "gemini",
    "bard.google.com": "gemini",
    "copilot.microsoft.com": "copilot",
    "copilot.cloud.microsoft": "copilot",
    "claude.ai": "claude",
    "you.com": "you",
    "grok.com": "grok",
    "x.ai": "grok",
    "chat.deepseek.com": "deepseek",
    "chat.mistral.ai": "mistral",
}


def _referrer_host(referrer: str) -> str:
    """Extract the lowercased host from a referrer, ``www.`` stripped.

    Tolerates values with no scheme (``chatgpt.com/foo``) by prepending a dummy
    scheme so ``urlparse`` puts the host in ``netloc`` instead of ``path``.
    """
    candidate = referrer if "://" in referrer else f"//{referrer.lstrip('/')}"
    try:
        host = urlparse(candidate).netloc.lower()
    except Exception:
        return ""
    # Drop any userinfo/port that a forged referrer might carry.
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_ai_source(referrer: str | None) -> str | None:
    """Map a first-touch referrer to an AI answer-engine label, or ``None``.

    Returns the attribution label for the first matching known AI host, or
    ``None`` for a missing/empty referrer, direct/social/search/own-domain
    traffic, or any host not in :data:`AI_REFERRER_DOMAINS`.
    """
    if not referrer or not referrer.strip():
        return None
    host = _referrer_host(referrer)
    if not host:
        return None
    for domain, label in AI_REFERRER_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return None
