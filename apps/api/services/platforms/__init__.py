from apps.api.models.social_account import Platform
from apps.api.services.platforms.base import PlatformService
from apps.api.services.platforms.facebook import FacebookService
from apps.api.services.platforms.instagram import InstagramService
from apps.api.services.platforms.linkedin import LinkedInService
from apps.api.services.platforms.tiktok import TikTokService
from apps.api.services.platforms.twitter import TwitterService


def get_platform_service(platform: Platform) -> PlatformService:
    """Factory: return the right service for a given platform."""
    services: dict[Platform, type[PlatformService]] = {
        Platform.twitter: TwitterService,
        Platform.facebook: FacebookService,
        Platform.instagram: InstagramService,
        Platform.linkedin: LinkedInService,
        Platform.tiktok: TikTokService,
    }
    service_cls = services.get(platform)
    if service_cls is None:
        raise ValueError(f"Unsupported platform: {platform}")
    return service_cls()
