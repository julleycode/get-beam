# KG-1: Public Suffix List refresh cadence

Owner: visitors-identity / ip-org-quality-pack (WS-D)
Priority: P3

The vendored `apps/api/data/public_suffix_list.dat` (fetched 2026-08-08 from
https://publicsuffix.org/list/public_suffix_list.dat) goes stale over weeks.
`registrable_domain` is correct against the vendored snapshot only (gate G13 proves
that, not currency). No runtime fetch by design (avoids a failure mode + moving test
surface). Follow-up: a periodic re-vendor job or a documented manual refresh cadence.
