"""Download the FREE MaxMind GeoLite2-City database.

Sibling of scripts/download_geolite2_asn.py — SAME free license key, different
edition. Run BOTH: City feeds the geo half of resolve_geoip_full (city, lat/lon,
accuracy_radius) and ASN feeds the network label. Installing City alone skips the
ip-api call that is currently the only source of org/isp, which silently drops
the network line.

One-time setup: create a free account at https://www.maxmind.com/en/geolite2/signup,
generate a license key, and set MAXMIND_LICENSE_KEY (or settings.maxmind_license_key).
Then run this to write GeoLite2-City.mmdb to settings.maxmind_city_db_path (default
./data/GeoLite2-City.mmdb) and point MAXMIND_CITY_DB_PATH at it.

MaxMind refreshes GeoLite2 weekly — re-run on deploy or from a weekly cron to keep
it fresh. Until a DB is present, resolve_geoip_full transparently falls back to
ip-api.com.

    python -m scripts.download_geolite2_asn
    python -m scripts.download_geolite2_city
"""
import io
import os
import sys
import tarfile

import httpx

from apps.api.config import settings

_URL = "https://download.maxmind.com/app/geoip_download"


def main() -> int:
    key = settings.maxmind_license_key or os.environ.get("MAXMIND_LICENSE_KEY", "")
    if not key:
        print(
            "MAXMIND_LICENSE_KEY is not set.\n"
            "Get a free key: https://www.maxmind.com/en/geolite2/signup",
            file=sys.stderr,
        )
        return 1

    dest = settings.maxmind_city_db_path or "data/GeoLite2-City.mmdb"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

    print("Downloading GeoLite2-City from MaxMind…")
    resp = httpx.get(
        _URL,
        params={"edition_id": "GeoLite2-City", "license_key": key, "suffix": "tar.gz"},
        timeout=180,
        follow_redirects=True,
    )
    if resp.status_code != 200:
        print(f"Download failed: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return 1

    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith(".mmdb")), None)
        if member is None:
            print("No .mmdb found in the downloaded archive.", file=sys.stderr)
            return 1
        extracted = tar.extractfile(member)
        if extracted is None:
            print("Could not read the .mmdb from the archive.", file=sys.stderr)
            return 1
        with extracted as src, open(dest, "wb") as out:
            out.write(src.read())

    print(f"Wrote {dest} ({os.path.getsize(dest):,} bytes). "
          f"Set MAXMIND_CITY_DB_PATH={dest} to use it. "
          f"Don't forget scripts/download_geolite2_asn.py for the network label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
