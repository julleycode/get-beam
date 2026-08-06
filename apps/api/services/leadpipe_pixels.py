"""Provision a Leadpipe pixel for one domain.

A Leadpipe pixel is bound 1-1 to a domain: ``POST /v1/data/pixels`` answers
``409 {"error": {"message": "Pixel already exists for this domain"}}`` on a
duplicate, and that 409 body does NOT carry the existing id (verified against a
live org 06-08-26). So "make sure this domain has a pixel and tell me its id"
takes two calls in the worst case: POST, then a list lookup on 409.

Kept out of the identity waterfall on purpose — this is onboarding-time
provisioning, not resolution. The waterfall only ever READS
(``LeadpipeMixin._leadpipe_active_domains``).
"""

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

LEADPIPE_API_BASE = "https://api.aws53.cloud"
_TIMEOUT = 15.0


async def ensure_pixel_for_domain(domain: str) -> str | None:
    """Return the Leadpipe pixel id for ``domain``, creating it if absent.

    Returns ``None`` — never raises — when Leadpipe cannot answer (no key,
    expired org, network failure). The caller is the install-snippet endpoint:
    a vendor outage must degrade to "snippet without the vendor tag", never to
    a failed snippet fetch, because the customer still needs Beam's own pixel.
    """
    if not domain:
        return None
    if not settings.leadpipe_pixel_autoprovision_enabled:
        # Off by default: this is the only Leadpipe path that WRITES at the
        # vendor, and a pixel consumes org quota and cannot be moved later.
        return None
    if not (settings.leadpipe_api_key and settings.leadpipe_enabled):
        return None

    if settings.mock_external_apis:
        # Deterministic per-domain fake so dev/tests/demo run keyless and two
        # calls for the same domain agree, exactly as the real API does.
        return f"mock-pixel-{domain.replace('.', '-')}"

    headers = {"X-API-Key": settings.leadpipe_api_key}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{LEADPIPE_API_BASE}/v1/data/pixels",
                headers={**headers, "Content-Type": "application/json"},
                json={"domain": domain, "name": domain},
            )

            if resp.status_code == 201:
                pixel_id = (resp.json().get("data") or {}).get("id")
                if pixel_id:
                    logger.info("leadpipe_pixel_created", domain=domain)
                    return pixel_id
                logger.warning("leadpipe_pixel_created_without_id", domain=domain)
                return None

            if resp.status_code != 409:
                # 401 bad key, 403 expired org, 5xx — all "ask again later".
                logger.warning(
                    "leadpipe_pixel_create_failed",
                    domain=domain,
                    status=resp.status_code,
                )
                return None

            # 409: the pixel exists but the error body withholds its id, so the
            # only way to learn it is to list and match on domain.
            listed = await client.get(
                f"{LEADPIPE_API_BASE}/v1/data/pixels", headers=headers
            )
            if listed.status_code != 200:
                logger.warning(
                    "leadpipe_pixel_lookup_failed",
                    domain=domain,
                    status=listed.status_code,
                )
                return None

            body = listed.json()
            rows = body.get("data", []) if isinstance(body, dict) else []
            wanted = domain.lower()
            for row in rows:
                if (row.get("domain") or "").lower() == wanted:
                    logger.info("leadpipe_pixel_adopted", domain=domain)
                    return row.get("id")

            # 409 said it exists, the list says it does not. Another org owns the
            # domain, or the list is scoped differently — either way, guessing an
            # id here would embed a pixel that collects into someone else's org.
            logger.warning("leadpipe_pixel_409_but_absent_from_list", domain=domain)
            return None
    except Exception as exc:
        logger.warning(
            "leadpipe_pixel_provision_error", domain=domain, error=type(exc).__name__
        )
        return None
