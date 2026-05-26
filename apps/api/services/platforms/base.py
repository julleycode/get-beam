"""Abstract base for every platform integration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
