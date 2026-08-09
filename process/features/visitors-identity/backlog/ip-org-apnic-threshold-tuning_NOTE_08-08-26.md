# KG-2: APNIC eyeball-ASN threshold tuning

Owner: visitors-identity / ip-org-quality-pack (WS-E)
Priority: P3

`ip_org_eyeball_min_users` defaults to 50_000. APNIC per-AS population estimates are
advertisement-sampled and noisy at the tail (IMC 2024 "unboxing" critique). 50k is a
judgment above the noise floor, not a measured optimum. Gate G16 proves the threshold is
APPLIED, not that it is RIGHT. Follow-up: tune against the WS-B benchmark corpus once it
exists, folding into item-4 stratified audit.
