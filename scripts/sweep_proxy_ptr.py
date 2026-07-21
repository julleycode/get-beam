"""Offline reverse-DNS sweep — scrub proxy visitors the ingest ASN filter misses.

Some proxies (Sprious/Rayobyte, Oxylabs pools) announce IPs from a RESIDENTIAL
parent ASN, so `is_datacenter_ip` keeps them at ingest — only the reverse-DNS
hostname (`*.static.sprious.com`) unmasks them. This job resolves every stored
visitor IP, forward-confirms the ones ending in a known proxy domain, and
deletes those visitors (+ their events / identifications / resolution logs). It
also seeds the `ip_datacenter:` Redis cache so ongoing hits from those IPs drop
at ingest for free. See apps/api/services/proxy_ptr_sweep.py.

Dry-run by DEFAULT (this deletes data). Pass --apply to actually scrub.

USAGE (from repo root; uses settings.database_url — root .env = PROD!)
---------------------------------------------------------------------
    python -m scripts.sweep_proxy_ptr              # dry-run: list proxy IPs, delete nothing
    python -m scripts.sweep_proxy_ptr --apply      # delete matched visitors + seed cache
"""

import argparse
import asyncio

import apps.api.main  # noqa: F401  — registers every model on Base.metadata
from apps.api.services.proxy_ptr_sweep import sweep_proxy_visitors


async def run(apply: bool) -> None:
    result = await sweep_proxy_visitors(dry_run=not apply)
    status = result.get("status")

    if status == "locked":
        print("Another sweep is already running (advisory lock held). Try later.")
        return
    if status == "no_ips":
        print("No visitor IPs to check.")
        return

    matches = result.get("matches", {})
    print(f"Proxy IPs found: {result.get('proxy_ips', 0)}")
    for ip, host in sorted(matches.items()):
        print(f"  {ip:16} -> {host}")

    if status == "dry_run":
        print(f"\nDRY RUN — would delete {result.get('would_delete_visitors', 0)} "
              f"visitor(s). Re-run with --apply to scrub.")
    elif status == "ok":
        print(f"\nDeleted {result.get('deleted_visitors', 0)} visitor(s); "
              f"seeded {result.get('proxy_ips', 0)} IP(s) into the ingest drop cache.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete matched proxy visitors (default: dry-run).",
    )
    args = ap.parse_args()
    asyncio.run(run(args.apply))
