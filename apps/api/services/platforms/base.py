"""Abstract base for every platform integration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for HTTP errors worth retrying (5xx, 429)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False


# Shared retry policy for platform write ops (post_comment): 3 attempts,
# exponential backoff (1→10s), retry only transient HTTP errors, then re-raise.
post_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_is_transient_error),
    reraise=True,
)


@dataclass
class FeedPost:
    """Normalized post from any platform."""
    platform_post_id: str
    author_name: str
    author_username: str
    content: str
    post_url: str
    posted_at: datetime
    author_avatar_url: Optional[str] = None
    media_urls: list[str] = field(default_factory=list)


@dataclass
class InboxMessage:
    """Normalized DM / inbox message from any platform."""
    platform_message_id: str
    sender_name: str
    sender_username: str
    content: str
    received_at: datetime
    sender_avatar_url: Optional[str] = None


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = field(default_factory=list)
    platform_user_id: str = ""
    username: str = ""


class PlatformService(ABC):
    """Every platform must implement these methods."""

    # ── OAuth ────────────────────────────────────────────
    @abstractmethod
    async def get_auth_url(self, state: str) -> str:
        """Return the URL to redirect the user to for OAuth consent."""
        ...

    @abstractmethod
    async def exchange_code(self, code: str, state: str = "") -> OAuthTokens:
        """Exchange an OAuth authorization code for tokens.

        Args:
            code: The authorization code from OAuth callback.
            state: The OAuth state parameter (needed for PKCE platforms
                   like Twitter and TikTok to retrieve code_verifier).
        """
        ...

    @abstractmethod
    async def refresh_tokens(self, refresh_token: str) -> OAuthTokens:
        """Refresh an expired access token."""
        ...

    # ── Read ─────────────────────────────────────────────
    @abstractmethod
    async def fetch_feed(
        self, access_token: str, *, limit: int = 20
    ) -> list[FeedPost]:
        """Fetch recent posts from connections / home feed."""
        ...

    async def fetch_inbox(
        self, access_token: str, *, limit: int = 20
    ) -> list[InboxMessage]:
        """Fetch recent DMs. Default: not supported (Phase 2)."""
        return []

    # ── Write ────────────────────────────────────────────
    @abstractmethod
    async def post_comment(
        self, access_token: str, platform_post_id: str, text: str
    ) -> str:
        """Post a comment on a post. Returns the new comment's platform ID."""
        ...

    async def send_reply(
        self, access_token: str, platform_message_id: str, text: str
    ) -> str:
        """Reply to a DM. Default: not supported (Phase 2)."""
        raise NotImplementedError("DM replies not yet supported on this platform")
