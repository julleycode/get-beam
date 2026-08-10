# KG-6: WS-D fix does not reach live reads for 30-75 days

Owner: visitors-identity / ip-org-quality-pack (WS-D)
Priority: P2

Two caches sit in front of `_extract_domain` output: the Redis `company_ip` cache (30d TTL)
and `company_graph` staleness re-validation (`company_graph_staleness_days`, default 75).
Both keep serving OLD-logic values on the live rDNS read path until they expire. Cache
invalidation is OUT of scope for the quality pack (needs its own gates + a decision on which
cache is authoritative). Already-written `company_graph` / `visitors.company_domain` /
`companies` rows are likewise NOT rewritten. No gate proves live-path behavior before caches
expire. Follow-up: targeted invalidation of public-suffix-shaped domain entries.
