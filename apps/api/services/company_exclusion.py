"""Company/domain exclusion list — matcher + per-site loader.

Pure helpers (``normalize_domain``, ``is_freemail``, ``is_public_suffix``,
``validate_exclusion_domain``, ``match_excluded``, ``parse_exclusions_csv``)
plus two async DB helpers (``load_exclusions``, ``excluded_visitor_ids``).

Callers MUST guard every DB helper call with
``if settings.company_exclusion_enabled:`` so the flag-OFF path issues zero
new queries. Logs carry site_id + counts only — never domains or emails.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.site_exclusion import EXCLUSION_REASONS, SiteExclusion
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.models.visitor_email import VisitorEmail

logger = structlog.get_logger()

MAX_IMPORT_BYTES = 1_048_576  # 1 MB
MAX_IMPORT_ROWS = 5000

# Own copy (deliberately not imported from enricher); a unit test asserts this
# is a superset of enricher._FREE_MAIL_DOMAINS.
FREEMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.jp",
    "yahoo.fr", "yahoo.de", "ymail.com", "rocketmail.com",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "outlook.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "proton.me",
    "protonmail.com", "gmx.com", "gmx.de", "gmx.net", "mail.com", "zoho.com",
    "yandex.com", "yandex.ru", "mail.ru", "qq.com", "163.com", "126.com",
    "naver.com", "hanmail.net", "daum.net", "fastmail.com", "hey.com",
    "tutanota.com", "pm.me", "duck.com", "web.de", "t-online.de", "orange.fr",
    "free.fr", "laposte.net", "libero.it", "comcast.net", "verizon.net",
    "att.net", "sbcglobal.net",
})

# Small built-in public-suffix list (no tldextract). Entries equal to one of
# these would exclude a whole TLD, so they are rejected at input.
PUBLIC_SUFFIXES: frozenset[str] = frozenset({
    "com", "net", "org", "edu", "gov", "mil", "int", "io", "co", "ai", "app",
    "dev", "biz", "info", "me", "us", "uk", "de", "fr", "jp", "cn", "au", "ca",
    "in", "vn", "eu", "nl", "es", "it", "br", "ru",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "co.nz", "org.nz", "co.in", "net.in",
    "co.za", "com.br", "com.cn", "com.vn", "com.sg", "com.mx", "com.tr",
    "co.kr", "or.kr", "com.hk", "com.tw", "github.io", "herokuapp.com",
    "vercel.app", "netlify.app", "pages.dev", "workers.dev",
})


def normalize_domain(raw: str | None) -> str | None:
    """Lowercase; strip scheme, credentials, ``www.``, path, port, trailing dot.

    Accepts a bare domain, a URL, or an email address. Returns None when no
    plausible domain remains.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if "@" in s and "://" not in s:
        s = s.rsplit("@", 1)[1]
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    s = s.split(":", 1)[0].strip().strip(".")
    if s.startswith("www."):
        s = s[4:]
    if not s or " " in s or ".." in s:
        return None
    return s


def is_freemail(domain: str) -> bool:
    return domain in FREEMAIL_DOMAINS


def is_public_suffix(domain: str) -> bool:
    return domain in PUBLIC_SUFFIXES


def validate_exclusion_domain(raw: str | None) -> tuple[str | None, str | None]:
    """Return ``(normalized_domain, None)`` or ``(None, error_code)``."""
    d = normalize_domain(raw)
    if d is None:
        return None, "invalid_domain"
    if len(d) > 253 or len(d.split(".")) < 2:
        return None, "invalid_domain"
    if is_public_suffix(d):
        return None, "public_suffix"
    if is_freemail(d):
        return None, "freemail_domain"
    return d, None


def _parent_walk(domain: str) -> Iterable[str]:
    """``a.b.acme.com`` -> ``a.b.acme.com``, ``b.acme.com``, ``acme.com``.

    Stops at 2 labels (never yields a bare TLD).
    """
    labels = domain.split(".")
    for i in range(0, max(len(labels) - 1, 0)):
        yield ".".join(labels[i:])


def match_excluded(domains: Iterable[str | None], exclusions: dict[str, str]) -> str | None:
    """Pure: first matching reason for any domain (after parent walk), else None."""
    if not exclusions:
        return None
    for raw in domains:
        d = normalize_domain(raw)
        if not d:
            continue
        for cand in _parent_walk(d):
            reason = exclusions.get(cand)
            if reason is not None:
                return reason
    return None


def parse_exclusions_csv(data: bytes) -> tuple[list[dict], list[dict]]:
    """Parse ``domain,company_name,reason[,note]`` CSV (header optional).

    Returns ``(valid_rows, errors)``; caps at MAX_IMPORT_ROWS data rows (the
    excess is reported as one ``too_many_rows`` error). Size cap is enforced by
    the caller before decoding. Duplicate domains: last row wins.
    """
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    valid: dict[str, dict] = {}
    errors: list[dict] = []
    row_no = 0
    data_rows = 0
    for row in reader:
        row_no += 1
        if not row or all(not c.strip() for c in row):
            continue
        if row_no == 1 and row[0].strip().lower() == "domain":
            continue
        data_rows += 1
        if data_rows > MAX_IMPORT_ROWS:
            errors.append({"row": row_no, "error": "too_many_rows"})
            break
        domain, err = validate_exclusion_domain(row[0])
        if err:
            errors.append({"row": row_no, "error": err})
            continue
        company = (row[1].strip() if len(row) > 1 else "") or None
        reason = (row[2].strip().lower() if len(row) > 2 else "") or "other"
        if reason not in EXCLUSION_REASONS:
            errors.append({"row": row_no, "error": "invalid_reason"})
            continue
        note = (row[3].strip() if len(row) > 3 else "") or None
        valid[domain] = {
            "domain": domain,
            "company_name": company[:200] if company else None,
            "reason": reason,
            "note": note[:500] if note else None,
        }
    return list(valid.values()), errors


async def load_exclusions(db: AsyncSession, site_id: str) -> dict[str, str]:
    """``{domain: reason}`` for one site (<= a few thousand rows)."""
    rows = (
        await db.execute(
            select(SiteExclusion.domain, SiteExclusion.reason).where(
                SiteExclusion.site_id == site_id
            )
        )
    ).all()
    return {d: r for d, r in rows}


async def excluded_visitor_ids(
    db: AsyncSession, site_id: str, visitor_ids: Iterable[str]
) -> dict[str, str]:
    """``{visitor_id: reason}`` for the input ids that are company-excluded.

    Matches each visitor's ``Visitor.company_domain`` plus every captured email
    domain (``VisitorEmail`` + ``IdentifiedVisitor.email``). A merged visitor is
    evaluated together with its canonical visitor (``canonical_visitor_id``), so
    excluding either side excludes both. Visitors with no domain never match.
    """
    ids = list(dict.fromkeys(v for v in visitor_ids if v))
    if not ids:
        return {}
    exclusions = await load_exclusions(db, site_id)
    if not exclusions:
        return {}

    vrows = (
        await db.execute(
            select(Visitor.visitor_id, Visitor.company_domain, Visitor.canonical_visitor_id).where(
                Visitor.site_id == site_id, Visitor.visitor_id.in_(ids)
            )
        )
    ).all()
    group: dict[str, str] = {vid: vid for vid in ids}
    for vid, _cd, canon in vrows:
        if canon:
            group[vid] = canon
    all_ids = set(ids) | set(group.values())
    # Canonical rows may not be in the input list — fetch their company_domain.
    domains: dict[str, set[str]] = {}
    crow = (
        await db.execute(
            select(Visitor.visitor_id, Visitor.company_domain).where(
                Visitor.site_id == site_id, Visitor.visitor_id.in_(all_ids)
            )
        )
    ).all()
    for vid, cd in crow:
        if cd:
            domains.setdefault(vid, set()).add(cd)
    erows = (
        await db.execute(
            select(VisitorEmail.visitor_id, VisitorEmail.email).where(
                VisitorEmail.site_id == site_id, VisitorEmail.visitor_id.in_(all_ids)
            )
        )
    ).all()
    irows = (
        await db.execute(
            select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id.in_(all_ids),
                IdentifiedVisitor.email.is_not(None),
            )
        )
    ).all()
    for vid, email in list(erows) + list(irows):
        if email and "@" in email:
            domains.setdefault(vid, set()).add(email.rsplit("@", 1)[1])

    out: dict[str, str] = {}
    for vid in ids:
        canon = group[vid]
        cand = domains.get(vid, set()) | domains.get(canon, set())
        reason = match_excluded(cand, exclusions)
        if reason is not None:
            out[vid] = reason
    return out


def log_applied(site_id: str | None, surface: str, excluded_count: int) -> None:
    """The ONE log event for this feature: site_id + surface + count only."""
    logger.info(
        "company_exclusion_applied",
        site_id=site_id,
        surface=surface,
        excluded_count=excluded_count,
    )


async def filter_visitor_ids(
    db: AsyncSession, site_id: str, visitor_ids: list[str], surface: str
) -> list[str]:
    """Drop excluded ids (order preserved). Caller guards with the flag."""
    excluded = await excluded_visitor_ids(db, site_id, visitor_ids)
    if excluded:
        log_applied(site_id, surface, len(excluded))
    return [v for v in visitor_ids if v not in excluded]


class CompanyExcludedError(Exception):
    """A visitor-keyed draft targets a company-excluded visitor (HTTP 409)."""


async def draft_is_company_excluded(db: AsyncSession, draft) -> bool:
    """True iff the draft is visitor-keyed and its visitor is excluded.

    Fail-open (no lookup) when the draft carries no ``site_id`` — such a draft
    cannot be posted anyway. Caller guards with the flag.
    """
    visitor_id = getattr(draft, "visitor_id", None)
    if not visitor_id:
        return False
    site_id = getattr(draft, "site_id", None)
    if not site_id:
        log_applied(None, "draft_no_site_fail_open", 0)
        return False
    if await excluded_visitor_ids(db, site_id, [visitor_id]):
        log_applied(site_id, "draft_send", 1)
        return True
    return False
