"""Gmail OAuth + send (Connect-Gmail).

Lets a site owner authorise Beam to send campaign email through their own Gmail,
so mail goes out FROM their address with no "via sendgrid.info". Only the
``gmail.send`` scope is requested (send-only — Beam never reads the mailbox);
``openid email`` ride along purely so we can learn the connected address from
the returned id_token without a second API call or a broader scope.

OAuth tokens are Fernet-encrypted at rest by the caller (see the router / sender
that persist ``EmailSenderAccount``). This module is stateless HTTP plumbing.
"""

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

# Send-only + login scopes (openid/email are non-sensitive; they let us read the
# connected address from the id_token). gmail.send is what actually sends.
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.send",
]

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_TIMEOUT = 10.0


class GmailOAuthError(Exception):
    """OAuth exchange/refresh failed. Carries ``invalid_grant`` when the user
    revoked access or changed their password (caller should deactivate + prompt
    a reconnect rather than retry)."""

    def __init__(self, message: str, *, invalid_grant: bool = False) -> None:
        super().__init__(message)
        self.invalid_grant = invalid_grant


@dataclass
class GmailTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    email: str | None = None
    scopes: list[str] = field(default_factory=lambda: list(SCOPES))


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def build_auth_url(state: str) -> str:
    """Consent URL. ``access_type=offline`` + ``prompt=consent`` guarantee a
    refresh_token so we can keep sending after the access token expires."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def _email_from_id_token(id_token: str | None) -> str | None:
    """Extract the email claim from a Google id_token (a JWT). No signature
    verification needed: the token came straight from Google's token endpoint
    over TLS in the same request, so it is already trusted."""
    if not id_token:
        return None
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad to a multiple of 4
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        return claims.get("email")
    except Exception:
        logger.warning("gmail_id_token_parse_failed")
        return None


def _tokens_from_response(data: dict, *, prev_refresh: str | None = None) -> GmailTokens:
    expires_at = None
    if data.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data["expires_in"]))
    return GmailTokens(
        access_token=data["access_token"],
        # A refresh is only returned on first consent; keep the prior one on refresh.
        refresh_token=data.get("refresh_token") or prev_refresh,
        expires_at=expires_at,
        email=_email_from_id_token(data.get("id_token")),
        scopes=(data.get("scope") or " ".join(SCOPES)).split(),
    )


async def exchange_code(code: str) -> GmailTokens:
    """Trade an authorization code for tokens (called on OAuth callback)."""
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TOKEN_ENDPOINT, data=payload)
    except httpx.HTTPError as exc:
        raise GmailOAuthError(f"token endpoint unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise GmailOAuthError(f"exchange failed {resp.status_code}: {resp.text[:200]}")
    return _tokens_from_response(resp.json())


async def refresh_access_token(refresh_token: str) -> GmailTokens:
    """Mint a fresh access token from a stored refresh token."""
    payload = {
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TOKEN_ENDPOINT, data=payload)
    except httpx.HTTPError as exc:
        raise GmailOAuthError(f"token endpoint unreachable: {exc}") from exc
    if resp.status_code != 200:
        body = resp.text[:200]
        # invalid_grant = user revoked access / changed password → don't retry.
        raise GmailOAuthError(
            f"refresh failed {resp.status_code}: {body}",
            invalid_grant="invalid_grant" in body,
        )
    return _tokens_from_response(resp.json(), prev_refresh=refresh_token)


def _build_raw_message(
    from_email: str,
    to_email: str,
    subject: str,
    body_html: str,
    unsubscribe_url: str | None,
) -> str:
    msg = MIMEText(body_html, "html", "utf-8")
    msg["To"] = to_email
    msg["From"] = from_email
    msg["Subject"] = subject
    if unsubscribe_url:
        # Keep parity with the SendGrid path so one-click unsubscribe still works.
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


async def send_message(
    access_token: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_html: str,
    unsubscribe_url: str | None = None,
) -> dict:
    """Send one message through the Gmail API as the authenticated account.

    Raises GmailOAuthError(invalid_grant=True) on 401 so the caller can fall back
    to SendGrid and mark the sender for reconnect; RuntimeError on other errors.
    """
    raw = _build_raw_message(from_email, to_email, subject, body_html, unsubscribe_url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _SEND_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"gmail send unreachable: {exc}") from exc
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 401:
        raise GmailOAuthError(f"gmail send unauthorized: {resp.text[:200]}", invalid_grant=True)
    raise RuntimeError(f"gmail send failed {resp.status_code}: {resp.text[:200]}")
