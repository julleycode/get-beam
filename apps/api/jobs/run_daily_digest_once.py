"""Run-and-exit entrypoint for the daily activity digest.

Two uses:

1. Manual verification — send today's digest right now, without waiting for the
   cron hour:  ``python -m apps.api.jobs.run_daily_digest_once``
   (This SENDS REAL EMAIL unless MOCK_EXTERNAL_APIS=true.)
2. A Railway cron service, if the digest should survive API restarts:
       Start command:  python -m apps.api.jobs.run_daily_digest_once
       Cron schedule:  0 13 * * *
   In that setup leave ``daily_digest_enabled`` false so the in-process
   APScheduler job stays off — though the advisory lock inside
   ``send_daily_digests`` means running both can't double-send anyway.

The 20h per-site throttle applies here too: a site that already got today's
digest is skipped.
"""

import asyncio
import importlib
import pkgutil

import structlog

# Register every ORM model before any query compiles. The running API imports
# these via its routers; this standalone entrypoint must do it explicitly, or
# select(Site) fails resolving relationships.
import apps.api.models as _models_pkg
for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"apps.api.models.{_m.name}")

from apps.api.services.daily_digest import send_daily_digests

logger = structlog.get_logger()


async def _main() -> None:
    logger.info("cron_daily_digest_started")
    try:
        sent = await send_daily_digests()
        logger.info("cron_daily_digest_done", sent=sent)
    except Exception:
        logger.exception("cron_daily_digest_crashed")
        raise


if __name__ == "__main__":
    asyncio.run(_main())
