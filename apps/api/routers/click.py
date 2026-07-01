"""Email click-tracking redirect — the ESP-compatible, day-zero de-anon link.

A customer drops a Beam link into their OWN ESP emails (Klaviyo/Mailchimp/etc.)
with a per-recipient token merge field:

    https://api.getbeam.fyi/c/{site_id}?t={{ beam_token }}&u=https://theirsite.com/x

A recipient click hits this endpoint on the REAL device (residential IP, and —
unlike an email OPEN — not proxied by Apple Mail Privacy), so we bind their email
to their Beam visitor cookie and then 302 to the destination. When they next land
on the Beam-pixel'd site, the durable _rta_svid cookie set here reconciles them
(own-data P1) and the resolver picks up the captured email for free.

PII-safe: the token is the Fernet-encrypted email (opaque) — the plaintext email
never appears in the URL. Open-redirect-safe: only ever redirects to the site's
own host, never a foreign domain.
"""
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.link_decorator import decode_bid
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


def _bare_host(netloc: str) -> str:
    """Lowercased host from a URL netloc, minus userinfo/port and a www. prefix."""
    h = netloc.lower().split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def build_click_url(api_base: str, site_id: str, dest_url: str, email: str) -> str:
    """Build one recipient's Beam click-tracking link. The email is carried as the
    opaque Fernet _bid token (never plaintext). The customer imports these per-
    recipient links (or the token as an ESP profile property) into their ESP."""
    from urllib.parse import quote

    from apps.api.services.link_decorator import generate_bid

    token = generate_bid(email)
    return f"{api_base.rstrip('/')}/c/{site_id}?t={token}&u={quote(dest_url, safe='')}"


def svid_cookie_name(site_id: str) -> str:
    """Per-site durable cookie name — must match events.py so a click and a pixel
    visit share the same _rta_svid and reconcile (own-data P1)."""
    return "_rta_svid_" + "".join(c for c in site_id if c.isalnum() or c == "_")


def safe_dest(dest: str, site_url: str) -> str:
    """Return `dest` only if it's an http(s) URL on the site's own host (or a
    subdomain); otherwise fall back to the site homepage. Prevents Beam from being
    turned into an open redirector / phishing hop."""
    if not (dest.startswith("https://") or dest.startswith("http://")):
        return site_url
    # Browsers treat backslash as '/' in the authority (WHATWG URL) but Python's
    # urlsplit does not — a parser differential that would let
    # "https://evil.com\.acme.com" pass the host check below. Reject any backslash,
    # whitespace, or control char so the parser can't disagree with the browser.
    if any(c in dest for c in "\\ \t\n\r") or any(ord(c) < 0x20 for c in dest):
        return site_url
    site_host = _bare_host(urlsplit(site_url).netloc)
    dest_host = _bare_host(urlsplit(dest).netloc)
    if site_host and dest_host and (dest_host == site_host or dest_host.endswith("." + site_host)):
        return dest
    return site_url


@router.get("/{site_id}")
@limiter.limit("120/minute")
async def click_redirect(
    site_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    site_url = (
        await db.execute(select(Site.url).where(Site.site_id == site_id))
    ).scalar_one_or_none()
    if not site_url:
        raise HTTPException(status_code=404, detail="Unknown site")

    dest = safe_dest(request.query_params.get("u") or "", site_url)

    token = request.query_params.get("t")
    email = decode_bid(token) if token else None
    email = email.strip().lower() if email else None
    if email and "@" not in email:
        email = None

    # Bind the recipient's email to their Beam visitor. Reuse the durable per-site
    # cookie (P1): if they visited the pixel'd site before, we already know their
    # visitor_id. Otherwise, with a valid email, derive a STABLE per-email id (not
    # a fresh uuid) so a forwarded link replayed cookielessly dedupes on the unique
    # constraint instead of inserting a new row each time — and set it as the cookie
    # so the later pixel visit reconciles this person.
    cookie_name = svid_cookie_name(site_id)
    cookie_vid = request.cookies.get(cookie_name)
    visitor_id = cookie_vid
    if email and not visitor_id:
        from apps.api.services.pii_crypto import email_hash

        visitor_id = "ec" + email_hash(email)[:30]

    if email and visitor_id:
        try:
            from apps.api.services.pii_crypto import email_hash, encrypt_pii

            await db.execute(
                pg_insert(VisitorEmail)
                .values(
                    site_id=site_id,
                    visitor_id=visitor_id,
                    email=email,
                    source="email_click",
                    email_ciphertext=encrypt_pii(email),
                    email_bidx=email_hash(email),
                )
                .on_conflict_do_nothing(constraint="uq_visitor_email_site_vid_email")
            )
            await db.commit()
            logger.info(
                "email_click_captured",
                site_id=site_id,
                visitor_id=visitor_id[:8],
                email_domain=email.split("@")[-1],
            )
        except Exception as exc:
            logger.warning("email_click_capture_failed", error=str(exc))

    resp = RedirectResponse(url=dest, status_code=302)
    # Set the durable cookie only when we minted an id (no prior cookie + a valid
    # email); a bare/invalid click just redirects with no state.
    if not cookie_vid and visitor_id:
        resp.set_cookie(
            key=cookie_name,
            value=visitor_id,
            max_age=365 * 86400,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
        )
    return resp
