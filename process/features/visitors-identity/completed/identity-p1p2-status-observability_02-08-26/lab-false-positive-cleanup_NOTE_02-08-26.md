# Lab cleanup — false-positive RB2B identity

**Visitor:** `407a701d-ade4-4593-9078-5b665d48ba80`  
**Issue:** Private Relay IP + name/email mismatch saved as identified via rb2b (pre-P0).

## One-shot SQL (Lab only — review before run)

```sql
-- Inspect
SELECT v.visitor_id, v.identity_status, v.ip_address, iv.email, iv.full_name, iv.resolution_provider
FROM visitors v
LEFT JOIN identified_visitors iv
  ON iv.site_id = v.site_id AND iv.visitor_id = v.visitor_id
WHERE v.visitor_id = '407a701d-ade4-4593-9078-5b665d48ba80';

-- Clear identity + mark privacy-filtered (preferred for relay IPs)
DELETE FROM identified_visitors
WHERE visitor_id = '407a701d-ade4-4593-9078-5b665d48ba80';

UPDATE visitors
SET identity_status = 'vpn_filtered',
    enrichment_status = 'pending'
WHERE visitor_id = '407a701d-ade4-4593-9078-5b665d48ba80';
```

Do **not** run against production without owner sign-off.
