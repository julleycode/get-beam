"""Ad-provider registry.

Mirrors services/crm/__init__.py's connector-registry pattern: one class per
provider, resolved by name. Phase 1 registers all three; only meta/google are
READY (see services/ads/base.py).
"""

from apps.api.services.ads.base import READY, AdsProvider
from apps.api.services.ads.google import GoogleAdsProvider
from apps.api.services.ads.linkedin import LinkedInAdsProvider
from apps.api.services.ads.meta import MetaAdsProvider

_PROVIDERS: dict[str, type[AdsProvider]] = {
    "meta": MetaAdsProvider,
    "google": GoogleAdsProvider,
    "linkedin": LinkedInAdsProvider,
}


def get_provider(name: str) -> AdsProvider:
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown or unsupported ad provider: {name}")
    return cls()


def supported_providers() -> set[str]:
    return set(_PROVIDERS.keys())


def is_ready(name: str) -> bool:
    return READY.get(name, False)
