"""RFC 6811 route-origin validation. Pure, no I/O, fully unit-testable.

Given an announced prefix, the AS announcing it, and the covering ROAs, decide
whether the announcement is authorized by the prefix holder.

**The three-state result is load-bearing, and collapsing it to a boolean is the
mistake this module exists to prevent.** Most of the routing table is simply
unsigned — no ROA has ever been published for it — and that is NOT evidence of
anything wrong. Scoring ``notfound`` as ``invalid`` would down-rank the majority
of perfectly legitimate corporate prefixes, which is worse than not checking at
all. So:

- ``valid``    — a covering ROA authorizes this exact ASN at this length.
- ``invalid``  — covering ROAs EXIST but none of them authorize this
                 announcement (wrong AS, or more specific than ``maxLength``).
                 This is a real, evidenced anomaly: somebody signed a statement
                 about this space and the announcement contradicts it.
- ``notfound`` — no covering ROA at all. Neutral, not negative.

``maxLength`` is the subtle half. A ROA for ``10.0.0.0/8`` with ``maxLength 16``
authorizes announcements from /8 through /16 and forbids a /24 — so a matching
ASN is necessary but not sufficient.
"""

import ipaddress
from typing import Literal, Sequence, TypedDict

OriginState = Literal["valid", "invalid", "notfound"]


class Roa(TypedDict):
    """One validated route-origin authorization."""

    prefix: str
    asn: int
    max_length: int


def validate_origin(
    prefix: str, asn: int | None, roas: Sequence[Roa]
) -> OriginState:
    """RFC 6811 verdict for ``asn`` announcing ``prefix``. Never raises.

    ``roas`` should already be the COVERING set (the caller filters with a
    containment query); a non-covering ROA passed in here is ignored rather than
    trusted, so a sloppy caller degrades to ``notfound`` instead of to a wrong
    verdict.
    """
    try:
        announced = ipaddress.ip_network(prefix, strict=False)
    except (ValueError, TypeError):
        return "notfound"

    covering_found = False
    for roa in roas:
        try:
            roa_net = ipaddress.ip_network(roa["prefix"], strict=False)
            max_length = int(roa["max_length"])
            roa_asn = int(roa["asn"])
        except (KeyError, TypeError, ValueError):
            continue
        if roa_net.version != announced.version:
            continue
        if not (
            roa_net.network_address <= announced.network_address
            and announced.broadcast_address <= roa_net.broadcast_address
        ):
            continue  # does not actually cover the announcement

        # From here on a ROA covers the prefix, so the answer can no longer be
        # "notfound" — the only question left is whether ANY of them authorize it.
        covering_found = True
        if asn is not None and roa_asn == asn and announced.prefixlen <= max_length:
            return "valid"

    return "invalid" if covering_found else "notfound"
