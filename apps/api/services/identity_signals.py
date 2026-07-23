"""Corroborating identity signals from outbound email engagement (owned-data-layer).

SendGrid open/click events → the ``identity_signals`` table. STRICTLY
corroborating: ``corroborate_identity`` only bumps confidence on an
ALREADY-matched identity. This module has ZERO write access to
``IdentifiedVisitor`` — it imports no ``_save_identified`` / no IdentifiedVisitor
insert/update path, so it structurally cannot create or upgrade an identity on
its own (read-only SELECTs on IdentifiedVisitor/Visitor for the write gate are
the only references, and they never mutate).

Every write passes ALL 4 gates first (datacenter IP, proxy/VPN, suppression,
do_not_resolve sticky). Any gate failure is a silent skip — never raises — so
the SendGrid webhook always 200s back. Email is stored ciphertext + blind index
only (same pattern as beam_identity_graph); plaintext email is never persisted.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.identity_signal import IdentitySignal
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.company_resolver import (
    check_ip_privacy,
    is_datacenter_ip,
    is_proxy_or_vpn,
)
from apps.api.services.pii_crypto import email_hash, encrypt_pii, normalize_email
from apps.api.services.suppression import is_email_suppressed

logger = structlog.get_logger()

# Base confidence at write time (decayed at read time, never mutated in place).
_BASE_CONFIDENCE = {
    "sendgrid_open": 0.45,
    "sendgrid_click": 0.6,
}

# Halve confidence every 30 days.
_DECAY_HALF_LIFE_DAYS = 30.0


def decay_confidence(
    base_confidence: float,
    created_at: datetime,
    now: datetime | None = None,
) -> float:
    """Pure, deterministic read-time decay: halve every 30 days.

    decayed = base * 0.5 ** (age_days / 30). Timezone-tolerant. Age is clamped
    at >= 0 so a future timestamp never inflates confidence."""
    now = now or datetime.now(timezone.utc)
    ca = created_at
    if ca.tzinfo is None:
        ca = ca.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ca).total_seconds() / 86400.0)
    return base_confidence * (0.5 ** (age_days / _DECAY_HALF_LIFE_DAYS))


async def _visitor_do_not_resolve(db: AsyncSession, email: str) -> bool:
    """True if any visitor this email maps to has do_not_resolve=True.

    No standalone reusable email→visitor helper exists (confirmed at VALIDATE);
    this inlines the same join used by suppression._cascade_suppress (email →
    IdentifiedVisitor (site_id, visitor_id)), then checks Visitor.do_not_resolve.
    READ-ONLY — no writes."""
    norm = normalize_email(email)
    if not norm:
        return False
    id_rows = (
        await db.execute(
            select(IdentifiedVisitor.site_id, IdentifiedVisitor.visitor_id).where(
                func.lower(IdentifiedVisitor.email) == norm
            )
        )
    ).all()
    for site_id, visitor_id in id_rows:
        dnr = (
            await db.execute(
                select(Visitor.do_not_resolve).where(
                    Visitor.site_id == site_id,
                    Visitor.visitor_id == visitor_id,
                )
            )
        ).scalar_one_or_none()
        if dnr is True:
            return True
    return False


async def record_signal(
    db: AsyncSession,
    site_id: str,
    ip: str,
    email: str,
    signal_type: str,
) -> None:
    """Persist a corroborating signal AFTER all 4 write gates pass.

    Gates (silent skip on any failure — never raises):
      1. datacenter/CDN IP (SendGrid infra, image-proxy opens)
      2. proxy/VPN/Tor/hosting IP
      3. suppression list (do_not_email)
      4. do_not_resolve sticky on the mapped visitor(s)
    """
    try:
        if signal_type not in _BASE_CONFIDENCE:
            return
        if not ip or not email or not site_id:
            return

        # Gate 1: datacenter/CDN IP.
        if await is_datacenter_ip(ip):
            logger.info("identity_signal_skip_datacenter", signal_type=signal_type)
            return
        # Gate 2: proxy / VPN / Tor / hosting.
        if is_proxy_or_vpn(await check_ip_privacy(ip)):
            logger.info("identity_signal_skip_proxy_vpn", signal_type=signal_type)
            return
        # Gate 3: suppression list.
        if await is_email_suppressed(db, email, "do_not_email"):
            logger.info("identity_signal_skip_suppressed", signal_type=signal_type)
            return
        # Gate 4: do_not_resolve sticky.
        if await _visitor_do_not_resolve(db, email):
            logger.info("identity_signal_skip_do_not_resolve", signal_type=signal_type)
            return

        db.add(
            IdentitySignal(
                site_id=site_id,
                ip=ip,
                email_ciphertext=encrypt_pii(email),
                email_bidx=email_hash(email),
                signal_type=signal_type,
                base_confidence=_BASE_CONFIDENCE[signal_type],
            )
        )
        await db.commit()
        logger.info(
            "identity_signal_recorded",
            signal_type=signal_type,
            email_domain=email.split("@")[-1] if "@" in email else None,
        )
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.debug("identity_signal_record_failed", error=str(exc))


async def corroborate_identity(
    db: AsyncSession, ip: str, email: str
) -> float | None:
    """Return a decayed confidence bump from matching signals, or None.

    Matches signals by ip OR email_bidx. READ-ONLY join helper — it NEVER
    creates or upgrades an IdentifiedVisitor. Intended to be called only from
    inside the waterfall's confidence-scoring step, after a fingerprint/cookie
    match already produced a candidate identity."""
    try:
        conds = []
        if ip:
            conds.append(IdentitySignal.ip == ip)
        if email:
            conds.append(IdentitySignal.email_bidx == email_hash(email))
        if not conds:
            return None
        from sqlalchemy import or_

        rows = (
            await db.execute(
                select(IdentitySignal).where(or_(*conds))
            )
        ).scalars().all()
        if not rows:
            return None
        now = datetime.now(timezone.utc)
        best = max(
            decay_confidence(r.base_confidence, r.created_at, now) for r in rows
        )
        return best
    except Exception as exc:
        logger.debug("corroborate_identity_failed", error=str(exc))
        return None
