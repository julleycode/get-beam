"""Download the FREE MaxMind GeoLite2-ASN database.

One-time setup: create a free account at https://www.maxmind.com/en/geolite2/signup,
generate a license key, and set MAXMIND_LICENSE_KEY (or settings.maxmind_license_key).
Then run this to write GeoLite2-ASN.mmdb to settings.maxmind_asn_db_path (default
./data/GeoLite2-ASN.mmdb) and point MAXMIND_ASN_DB_PATH at it.

MaxMind refreshes GeoLite2 weekly — re-run on deploy or from a weekly cron to keep
it fresh. Until a DB is present, is_datacenter_ip transparently falls back to IPinfo.

    python -m scripts.download_geolite2_asn
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

    dest = settings.maxmind_asn_db_path or "data/GeoLite2-ASN.mmdb"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

    print("Downloading GeoLite2-ASN from MaxMind…")
    resp = httpx.get(
        _URL,
        params={"edition_id": "GeoLite2-ASN", "license_key": key, "suffix": "tar.gz"},
        timeout=120,
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
          f"Set MAXMIND_ASN_DB_PATH={dest} to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
