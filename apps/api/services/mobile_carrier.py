"""Is this address a mobile-carrier connection?

WHY A SEPARATE MODULE. Mobile carriers register enormous blocks under a single
registration point, so a "high confidence" mobile address routinely geolocates to
a city the human has never visited — both providers agree, and both are wrong the
same way. That is the one failure the two-provider cross-check structurally cannot
catch, so the reveal downgrades every mobile connection to a country card.

This does NOT live in ``company_resolver.py``: ``classify_org_kind`` is frozen —
the ip-org fusion pipeline, ``resolve_org_domain`` and the org-kind classification
table all consume its taxonomy, and widening it to add a "mobile" kind would move
data those consumers depend on. It does not live inline in ``onboarding_canary.py``
either: an ASN table plus regexes would bury the reveal-assembly logic, and both
routers plus two test modules want this in isolation.

BIAS: prefer the false-positive downgrade. A false negative shows a map that may
be wrong (the failure we are here to prevent); a false positive shows a correct
country card instead of a correct map (a smaller claim, still true). So matching
is deliberately liberal — but only by EXPLICIT brand, never by a token as broad
as "telecom", which would sweep in every fixed-line ISP on earth.

Zero imports from ``company_resolver`` — asserted by the unit test, not by
convention.
"""

import re

# ASN parsed locally rather than imported, so the no-import purity gate holds.
_AS_RE = re.compile(r"AS(\d+)", re.IGNORECASE)

_MOBILE_ASNS: frozenset[int] = frozenset(
    {
        45899,  # VNPT / Vinaphone (VN)
        24086,  # Viettel Mobile (VN)
        45204,  # Mobifone / VMS (VN)
        63565,  # FPT — mobile/wireless block (VN)
        # NOT 18403: that is FPT Telecom's FIXED-LINE residential ASN — it is the
        # very address in geoip_crosscheck.py's incident docstring. Listing it
        # would downgrade every FPT home connection in the country.
        21928,  # T-Mobile USA
        6167,   # Verizon Wireless (Cellco Partnership)
        20057,  # AT&T Mobility
    }
)

# Generic mobile tokens plus an EXPLICIT brand list. "telecom" is deliberately
# NOT a generic token — see the module bias note.
_MOBILE_RE = re.compile(
    r"\b("
    r"mobile|cellular|wireless|gsm|lte|4g|5g"
    r"|viettel|mobifone|vinaphone|t-mobile|verizon wireless|at&t mobility"
    r")\b",
    re.IGNORECASE,
)


def is_mobile_carrier(ip: str, geo) -> bool:
    """``True`` when this looks like a phone connection. Never raises.

    ``geo`` is duck-typed: only ``as_str``, ``org`` and ``isp`` are read, so a
    test double needs nothing else. Any malformed input yields ``False``.
    """
    try:
        as_str = str(getattr(geo, "as_str", "") or "")
        match = _AS_RE.search(as_str)
        if match and int(match.group(1)) in _MOBILE_ASNS:
            return True

        for field in ("org", "isp"):
            value = str(getattr(geo, field, "") or "")
            if value and _MOBILE_RE.search(value):
                return True
    except Exception:  # noqa: BLE001 — a reveal must never 500 on a label
        return False

    return False
