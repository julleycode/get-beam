"""PII-safe logging helpers.

CLAUDE.md: "Never store PII in logs". Any structlog call that includes an
email address must pass it through mask_email() first.
"""


def mask_email(email: str | None) -> str | None:
    """Mask an email address for logging (PII): first 2 chars + domain only."""
    if not email:
        return email
    local, _, domain = email.partition("@")
    masked = f"{local[:2]}***"
    return f"{masked}@{domain}" if domain else masked
