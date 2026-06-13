"""Maigret username→profile engine (stage B of the social-resolution pipeline).

Maigret checks a username against 3000+ sites and returns real profile URLs. It
is a USERNAME engine (not email), so it lives here — the pipeline derives
username candidates and calls `search_usernames`. Heavy dep; imported lazily and
degrades to [] if missing.

Maigret prints `[+]/[-]` lines via its notifier; we redirect that to a throwaway
buffer to keep prod logs clean.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import time

import structlog

from apps.api.services.osint_scanner import OsintAccount

logger = structlog.get_logger()

_db = None  # MaigretDatabase, loaded once (parsing 3000+ sites is expensive)


def is_available() -> bool:
    try:
        import maigret  # noqa: F401

        return True
    except Exception:
        return False


def _load_db():
    global _db
    if _db is None:
        import maigret
        from maigret.sites import MaigretDatabase

        data = os.path.join(os.path.dirname(maigret.__file__), "resources", "data.json")
        _db = MaigretDatabase().load_from_path(data)
    return _db


async def search_usernames(
    candidates: list[dict],
    *,
    top_sites: int,
    per_username_timeout: float,
    deadline: float,
    parse: bool = True,
    max_connections: int = 20,
) -> list[OsintAccount]:
    """Run Maigret for each candidate username; map CLAIMED hits → OsintAccount.

    Bounded by the overall `deadline` (stops scheduling new usernames past it).
    Never raises — logs and returns whatever was gathered.
    """
    if not candidates:
        return []
    try:
        import maigret
        from maigret.notify import QueryNotifyPrint
    except Exception as e:
        logger.warning("maigret_import_failed", err=str(e))
        return []

    try:
        db = _load_db()
        site_dict = db.ranked_sites_dict(top=top_sites)
    except Exception as e:
        logger.warning("maigret_db_load_failed", err=str(e))
        return []

    m_logger = logging.getLogger("maigret")
    m_logger.setLevel(logging.CRITICAL)
    notify = QueryNotifyPrint(color=False)

    accounts: list[OsintAccount] = []
    seen_urls: set[str] = set()

    for cand in candidates:
        if time.monotonic() >= deadline:
            break
        username = cand["username"]
        try:
            # maigret.search runs all sites concurrently internally; redirect its
            # notifier prints to a buffer. Cap each username generously.
            with contextlib.redirect_stdout(io.StringIO()):
                results = await asyncio.wait_for(
                    maigret.search(
                        username=username,
                        site_dict=site_dict,
                        logger=m_logger,
                        query_notify=notify,
                        timeout=int(per_username_timeout),
                        no_progressbar=True,
                        id_type="username",
                        is_parsing_enabled=parse,
                        max_connections=max_connections,
                    ),
                    timeout=max(5.0, deadline - time.monotonic()),
                )
        except Exception:
            continue

        for site, info in (results or {}).items():
            status = info.get("status")
            if not getattr(status, "is_found", False):
                continue
            url = info.get("url_user")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            extra = {"username": username, "cand_source": cand.get("source", "name")}
            # When parsing is on, Maigret extracts real profile fields — pull a
            # useful subset in as confirmation (a parsed page ≠ soft-404).
            ids = getattr(status, "ids_data", None) or {}
            if isinstance(ids, dict):
                for k in ("name", "fullname", "full_name", "bio", "location",
                          "image", "created_at", "gender"):
                    if ids.get(k):
                        extra[k] = ids[k]
                if any(k in extra for k in ("name", "fullname", "full_name", "bio")):
                    extra["parsed"] = True
            accounts.append(
                OsintAccount(
                    site_name=site,
                    category="social",
                    url=url,
                    # A parsed hit (real data extracted) is stronger than a bare
                    # status check — promote known→confirmed, guess→likely.
                    kind="profile",
                    confidence=(
                        "confirmed" if extra.get("parsed") and cand.get("known")
                        else "likely" if cand.get("known") or extra.get("parsed")
                        else "guess"
                    ),
                    source_engine="maigret",
                    extra=extra,
                )
            )

    logger.info("maigret_search_done", candidates=len(candidates), hits=len(accounts))
    return accounts
