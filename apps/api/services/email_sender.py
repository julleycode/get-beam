import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailSender:
    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        from_name: str = "Beam",
        from_email: str = "hello@getbeam.fyi",
        unsubscribe_url: str | None = None,
    ) -> dict:
        if not unsubscribe_url:
            unsubscribe_url = f"{settings.api_base_url}/unsubscribe?email={to_email}"

        full_html = f"""{body_html}
<br/><br/>
<p style="font-size:12px;color:#999;">
    <a href="{unsubscribe_url}">Unsubscribe</a> from future emails.
</p>"""

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject,
            "content": [{"type": "text/html", "value": full_html}],
            "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        }

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
                logger.info("email_sent", to=to_email, id=msg_id, status=response.status_code)
                return {"id": msg_id, "status": response.status_code}

            logger.error(
                "email_send_failed",
                to=to_email,
                status=response.status_code,
                body=response.text[:500],
            )
            raise RuntimeError(f"SendGrid {response.status_code}: {response.text[:200]}")

        except httpx.HTTPError as e:
            logger.error("email_send_failed", to=to_email, error=str(e))
            raise
