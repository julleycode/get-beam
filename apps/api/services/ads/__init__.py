"""Ad-audience provider layer (Meta / Google / LinkedIn)."""

from apps.api.services.ads.base import READY
from apps.api.services.ads.factory import get_provider, is_ready, supported_providers

__all__ = ["READY", "get_provider", "is_ready", "supported_providers"]
