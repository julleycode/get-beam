"""Registrable-domain extraction via the vendored Public Suffix List (WS-D).

Replaces ``company_resolver._extract_domain``'s hardcoded 8-entry two-part-TLD
set with the real Public Suffix List, so multi-part suffixes (``co.uk``,
``gov.br``, ``com.au`` …) resolve to the correct registrable domain instead of
being guessed from a short static table.

Vendored, not fetched: ``apps/api/data/public_suffix_list.dat`` is committed and
read once (``@lru_cache``). The PSL changes on the order of weeks, so a runtime
fetch would add a failure mode and a moving test surface for a barely-moving
file; the refresh cadence is a documented known-gap (KG-1).

**ICANN section ONLY (Q10).** Only rules between ``// ===BEGIN ICANN DOMAINS===``
and ``// ===END ICANN DOMAINS===`` are loaded. The PRIVATE section carries
cloud-tenant suffixes (``compute.amazonaws.com``, ``cloudapp.azure.com``,
``*.herokuapp.com``); loading them would make an EC2 rDNS host resolve to its
own long tenant name instead of collapsing to ``amazonaws.com``, bypassing the
resolver's ISP/cloud filter — a false-positive generator on the exact surface
the filter exists for.

Pure module: no network, no new dependency, one cached file read.
"""

from functools import lru_cache
from pathlib import Path

_PSL_PATH = Path(__file__).resolve().parent.parent / "data" / "public_suffix_list.dat"

_ICANN_BEGIN = "// ===BEGIN ICANN DOMAINS==="
_ICANN_END = "// ===END ICANN DOMAINS==="


@lru_cache(maxsize=1)
def _load_rules() -> tuple[frozenset[str], frozenset[str]]:
    """Load the ICANN-section PSL rules once.

    Returns ``(rules, exceptions)`` where ``exceptions`` holds the ``!``-prefixed
    rules with the ``!`` stripped. Blank lines and ``//`` comments are skipped,
    and every rule outside the ICANN markers is ignored (Q10).
    """
    rules: set[str] = set()
    exceptions: set[str] = set()
    in_icann = False
    try:
        text = _PSL_PATH.read_text(encoding="utf-8")
    except OSError:
        # A missing vendored file is a hard misconfiguration, but returning empty
        # rule sets degrades gracefully to the implicit "*" rule rather than
        # raising on the live rDNS path.
        return frozenset(), frozenset()
    for raw in text.splitlines():
        line = raw.strip()
        if line == _ICANN_BEGIN:
            in_icann = True
            continue
        if line == _ICANN_END:
            in_icann = False
            continue
        if not in_icann or not line or line.startswith("//"):
            continue
        if line.startswith("!"):
            exceptions.add(line[1:].lower())
        else:
            rules.add(line.lower())
    return frozenset(rules), frozenset(exceptions)


def _rule_matches(rule_labels: list[str], host_labels: list[str]) -> bool:
    """True if ``rule_labels`` matches the rightmost of ``host_labels``.

    A ``*`` in a rule matches exactly one label. The rule must not have more
    labels than the host.
    """
    m = len(rule_labels)
    n = len(host_labels)
    if m > n:
        return False
    for i in range(m):
        r = rule_labels[m - 1 - i]
        h = host_labels[n - 1 - i]
        if r != "*" and r != h:
            return False
    return True


def registrable_domain(hostname: str) -> str | None:
    """Return the registrable domain (public suffix + exactly one more label).

    ``mail.google.com`` → ``google.com``; ``foo.bar.gov.br`` → ``bar.gov.br``;
    ``x.co.za`` → ``x.co.za``. Returns ``None`` when the hostname IS a public
    suffix with nothing in front of it, when it has fewer labels than the
    matching rule requires, or when it is empty/single-label/malformed.

    Standard PSL algorithm: the prevailing rule is the longest matching normal
    rule, unless a matching exception rule exists (an exception's public suffix is
    the rule minus its leftmost label). No matching rule falls back to the
    implicit ``*`` rule (rightmost single label is the suffix).
    """
    if not hostname:
        return None
    host = hostname.strip().rstrip(".").lower()
    if not host:
        return None
    labels = host.split(".")
    if len(labels) < 2 or any(lbl == "" for lbl in labels):
        return None

    rules, exceptions = _load_rules()
    n = len(labels)

    # Exception rules take priority over all normal rules.
    exc_best: list[str] | None = None
    for ex in exceptions:
        el = ex.split(".")
        if _rule_matches(el, labels) and (
            exc_best is None or len(el) > len(exc_best)
        ):
            exc_best = el

    if exc_best is not None:
        # Public suffix = exception rule minus its leftmost label.
        suffix_len = len(exc_best) - 1
    else:
        best: list[str] | None = None
        for rule in rules:
            rl = rule.split(".")
            if _rule_matches(rl, labels) and (best is None or len(rl) > len(best)):
                best = rl
        # No matching rule → implicit "*" rule → suffix is the last label.
        suffix_len = len(best) if best is not None else 1

    # Host must have at least one label in front of the public suffix.
    if n <= suffix_len:
        return None
    return ".".join(labels[n - suffix_len - 1 :])
