# KG-9: production lookup SQL has a non-total row order

Owner: visitors-identity / ip-org-quality-pack (WS-B, new this cycle)
Priority: P2

`_LOOKUP_SQL` (ip_org_lookup.py:52-56) and `_V2_ROUTE_ORIGIN_SQL` (:94-100) both
`ORDER BY masklen(prefix) DESC LIMIT 1` with NO tie-break, and `prefix` carries no unique
constraint while `parse_pfx2as` does not dedupe — so duplicate equal-length prefixes make
the production row choice nondeterministic. The quality pack fixes this ONLY in the
measurement script own queries (adding `, id`); the LIVE lookup path is untouched because it
needs its own gate (touches the hot path). The measure script duplicate-prefix probe gates
the v1==v2 invariant on a zero result precisely because of this. Follow-up: add a
deterministic `, id` (or a unique constraint) to the production lookup SQL under its own gate.
