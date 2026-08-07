"""Rebuild the self-hosted IP→org table from the public CAIDA snapshots.

Thin CLI over ``ip_org_ingest.refresh_ip_org_dataset`` — the scheduler job calls
the exact same function, so on-demand and scheduled runs cannot drift.

Dry run is the DEFAULT (matching ``backfill_enrichment`` and
``sweep_proxy_ptr``): a dry run downloads and parses the datasets and prints the
counts, but never touches the table. That is the right first thing to run against
a live dataset, because the only way a parse regression shows up is in the row
counts.

    .venv/bin/python3.11 scripts/refresh_ip_org.py              # dry run
    .venv/bin/python3.11 scripts/refresh_ip_org.py --apply      # load + swap

``--apply`` is guarded to LOCAL databases only. The load path does
``DROP TABLE ip_org_prefixes``, and this repo's ``.env`` points
``DATABASE_URL`` at the managed production database — so an ``--apply`` run
from a normal dev shell would drop and rebuild a production table with no
prompt. ``--allow-remote`` is the deliberate override.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import structlog

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.services.ip_org_ingest import refresh_ip_org_dataset  # noqa: E402

logger = structlog.get_logger()

#: Hosts treated as a developer's own machine. Everything else — including any
#: managed/pooler hostname — is remote.
LOCAL_HOSTS: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
)


def is_local_db_url(url: str) -> bool:
    """True if ``url``'s host is a local database. Pure; never raises.

    Fail-CLOSED: an unparseable or hostless DSN returns False. "I could not tell
    where this points" must not read as "it is safe to drop a table there".
    """
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    return host.lower().strip("[]") in LOCAL_HOSTS


async def _main(apply: bool) -> int:
    status = await refresh_ip_org_dataset(dry_run=not apply)
    print(json.dumps(status, indent=2, default=str))
    return 0 if status.get("status") in ("ok", "dry_run", "locked") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually load and swap the table (default is a dry run)",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit --apply against a non-local database (drops a live table)",
    )
    args = parser.parse_args()

    # Dry run stays unguarded: it is read-only and never touches the database.
    if args.apply and not args.allow_remote:
        from apps.api.config import settings

        if not is_local_db_url(settings.database_url):
            host = urlsplit(settings.database_url).hostname or "<unparseable>"
            logger.error(
                "ip_org_refresh_refused_remote_database",
                host=host,
                reason="--apply drops and rebuilds ip_org_prefixes; refusing "
                "to do that against a non-local database",
                remedy="export DATABASE_URL to a local DSN, or pass "
                "--allow-remote if this is genuinely intended",
            )
            raise SystemExit(1)

    raise SystemExit(asyncio.run(_main(apply=args.apply)))
