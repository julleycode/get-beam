# KG-8: corpus IP provenance is last-seen, not identification-time

Owner: visitors-identity / ip-org-quality-pack (WS-B)
Priority: P3 (applies only on the fallback path)

`visitors.ip_address` is overwritten by the aggregator on every rollup, so it is the
visitor MOST RECENT IP, not necessarily the IP at `resolved_at`. The extraction script
PREFERS an events-table derivation at/near `resolved_at` (with the same strict-IPv4 +
private-range + `<> ""` + CF-cutoff predicates) via a per-row COALESCE, falling back to
`visitors.ip_address` when no qualifying event row exists (events retention is 90 days).
On the fallback path the IP may postdate the identification — a visitor who changed networks
contributes a mismatched (ip, org) pair. Report records which rows used the fallback.
