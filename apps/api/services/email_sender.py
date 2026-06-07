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

        if self.mock:
            logger.info("email_sent_mock", to=to_email, subject=subject)
            return {"id": "mock_email_id", "status": "sent"}

        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content, Header

        message = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", full_html),
        )
        message.add_header(Header("List-Unsubscribe", f"<{unsubscribe_url}>"))

        try:
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            response = sg.send(message)
            msg_id = response.headers.get("X-Message-Id", "unknown")
            logger.info("email_sent", to=to_email, id=msg_id, status=response.status_code)
            return {"id": msg_id, "status": response.status_code}
        except Exception as e:
            logger.error("email_send_failed", to=to_email, error=str(e))
            raise
