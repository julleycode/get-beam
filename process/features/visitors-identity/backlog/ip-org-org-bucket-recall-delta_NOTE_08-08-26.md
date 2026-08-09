# KG-7: no pre-C/E coverage baseline exists

Owner: visitors-identity / ip-org-quality-pack (WS-B)
Priority: P3

WS-C family inheritance and WS-E APNIC pre-check both NARROW the `org` bucket; WS-B runs
LAST and therefore measures only the post-change world. The precision report records
coverage %/None-rate as a FORWARD baseline; the recall DELTA caused by C and E is unmeasured.
Follow-up: if a before/after is wanted, snapshot coverage on a corpus BEFORE re-ingesting
with C+E, or reconstruct via the as2org_org_id family grouping.
