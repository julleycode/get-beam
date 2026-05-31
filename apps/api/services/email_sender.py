import structlog

from apps.api.config import settings

logger = structlog.get_logger()


class EmailSender:
    def __init__(self) -> None:
        self.mock = settings.mock_external_apis

    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        from_name: str = "Beam",
        from_email: str = "noreply@getbeam.fyi",
        unsubscribe_url: str | None = None,
    ) -> dict:
        if not unsubscribe_url:
            unsubscribe_url = f"{settings.api_base_url}/unsubscribe?email={to_email}"

        full_html = f"""{body_html}
<br/><br/>
<p style="font-size:12px;color:#999;">
    <a href="{unsubscribe_url}">Unsubscribe</a> from future emails.
</p>"""

        if self.mock:
            logger.info("email_sent_mock", to=to_email, subject=subject)
            return {"id": "mock_email_id", "status": "sent"}

        import resend

        resend.api_key = settings.resend_api_key

        params = {
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": full_html,
            "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        }

        try:
            result = resend.Emails.send(params)
            logger.info("email_sent", to=to_email, id=result.get("id"))
            return result
        except Exception as e:
            logger.error("email_send_failed", to=to_email, error=str(e))
            raise
