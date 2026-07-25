"""Which sites get the loosened all-US resolution eligibility.

Sites whose url hostname matches ``settings.resolve_all_us_domains`` (default
the owner's own getbeam.fyi) resolve every US visitor regardless of intent
score. All other sites keep the intent >= RESOLUTION_MIN_INTENT gate so
customer provider budgets aren't burned on low-intent traffic.
"""

from urllib.parse import urlparse

from apps.api.config import settings


def _hostname(url: str | None) -> str:
    if not url:
        return ""
    raw = url if "://" in url else f"https://{url}"
    host = (urlparse(raw).hostname or "").lower()
    return host.removeprefix("www.")


def site_resolves_all_us(site_url: str | None) -> bool:
    """True when the site's url hostname is in resolve_all_us_domains."""
    domains = {
        d.strip().lower().removeprefix("www.")
        for d in settings.resolve_all_us_domains.split(",")
        if d.strip()
    }
    return bool(domains) and _hostname(site_url) in domains
