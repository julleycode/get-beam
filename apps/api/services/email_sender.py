from html import escape
from urllib.parse import quote

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.email_branding import beam_email_footer
from apps.api.services.link_decorator import generate_unsubscribe_token
from apps.api.services.pii import mask_email as _mask_email
from apps.api.services.suppression import is_email_suppressed

logger = structlog.get_logger()

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailSender:
    async def _is_suppressed(self, db: AsyncSession, to_email: str) -> bool:
        """True if this address must not be emailed — either an IdentifiedVisitor
        row carries the do_not_email flag, OR the address is on the suppression
        list (covers addresses opted out after they were first identified).

        Case-insensitive match: stored emails may be mixed case while input is
        typically lowercased, so compare lower() to lower().
        """
        result = await db.execute(
            select(IdentifiedVisitor.id)
            .where(
                func.lower(IdentifiedVisitor.email) == to_email.strip().lower(),
                IdentifiedVisitor.do_not_email.is_(True),
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return True
        # The suppression list catches an address opted out AFTER it was first
        # identified — a row created later won't carry the flag. Blind-index
        # hash match; the 'all' scope is covered too.
        return await is_email_suppressed(db, to_email, "do_not_email")

    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        from_name: str = "Beam",
        from_email: str = "hello@getbeam.fyi",
        reply_to: str | None = None,
        unsubscribe_url: str | None = None,
        db: AsyncSession | None = None,
        branding: bool = False,
    ) -> dict | None:
        # Suppression check (do_not_email set by unsubscribe + bounce webhook).
        # `db` is optional so purely transactional callers without a session
        # (waitlist invites, admin notifications — recipients who are not
        # visitors) keep working unchanged; any visitor-targeted or campaign
        # send MUST pass a session to get the check. Returns None (falsy) when
        # the send is skipped.
        if db is not None and await self._is_suppressed(db, to_email):
            logger.info("email_suppressed", to=_mask_email(to_email))
            return None

        if not unsubscribe_url:
            token = generate_unsubscribe_token(to_email)
            unsubscribe_url = f"{settings.api_base_url}/unsubscribe?t={quote(token, safe='')}"

        # branding is opt-IN: only Beam-owned emails TO our customers pass True.
        # Campaign sends (a customer's outreach to THEIR prospects) never do —
        # the default keeps any future caller safe by omission.
        footer = beam_email_footer() if branding else ""
        full_html = f"""{body_html}
<br/><br/>
{footer}<p style="font-size:12px;color:#999;">
    <a href="{escape(unsubscribe_url, quote=True)}">Unsubscribe</a> from future emails.
</p>"""

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject,
            "content": [{"type": "text/html", "value": full_html}],
            "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        }
        # Reply-To = the customer's own inbox so a recipient's reply reaches them,
        # not Beam's shared from-address. (The From/DKIM stays Beam until the
        # Connect-Gmail work lands; this is the interim personalization.)
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    SENDGRID_API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.sendgrid_api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code in (200, 201, 202):
                msg_id = response.headers.get("X-Message-Id", "unknown")
                logger.info("email_sent", to=_mask_email(to_email), id=msg_id, status=response.status_code)
                return {"id": msg_id, "status": response.status_code}

            logger.error(
                "email_send_failed",
                to=_mask_email(to_email),
                status=response.status_code,
                body=response.text[:500],
            )
            raise RuntimeError(f"SendGrid {response.status_code}: {response.text[:200]}")

        except httpx.HTTPError as e:
            logger.error("email_send_failed", to=_mask_email(to_email), error=str(e))
            raise
