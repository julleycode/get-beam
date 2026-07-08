"""Shared "Powered by Beam" footer for Beam-owned transactional emails.

Growth loop: report emails (weekly digest, alerts) get forwarded to colleagues
and bosses — every forward puts Beam in front of another growth/sales buyer.
The footer is opt-IN (`EmailSender.send(branding=True)`) so a forgotten flag on
a future outreach path can never brand an email a customer sends to THEIR
prospects; forgetting it on a Beam-owned email merely loses a footer.

Pure module: no imports from email_sender (avoids an import cycle) and no DB —
the link is a static landing URL, never a per-customer one, so senders without
a session keep working.
"""

BEAM_FOOTER_URL = (
    "https://getbeam.fyi"
    "?utm_source=email_footer&utm_medium=email&utm_campaign=powered_by"
)


def beam_email_footer() -> str:
    """One small branded line, styled to match the unsubscribe block below it."""
    return (
        '<p style="font-size:12px;color:#999;margin-top:24px;">'
        f'Powered by <a href="{BEAM_FOOTER_URL}" '
        'style="color:#FF3366;text-decoration:none;font-weight:600;">Beam</a>'
        " &mdash; see who&#39;s visiting your site."
        "</p>"
    )
