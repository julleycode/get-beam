# KG-5: RIR ingest leg has no skip-ratio guard

Owner: visitors-identity / ip-org-quality-pack (WS-A)
Priority: P3

`refresh_rir_allocations` (ip_org_rir_ingest.py) tracks NO skipped count and has NO
offered-row denominator (its summary is sources_ok/sources_failed/allocations/rows;
parse_delegated_extended silently `continue`s on unparseable records). So the WS-A
silent-collapse skip-ratio guard covers the CAIDA leg ONLY. Measured RIR skip rate at
Phase-3 EVL was 0%, so current exposure is nil — but it is unguarded. Follow-up: add an
offered-row denominator + skipped counter to the RIR job, then extend the guard.
