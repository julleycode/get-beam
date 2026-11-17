---
name: report:prod-pii-encryption-key-empty
description: "Prod Railway PII_ENCRYPTION_KEY resolves empty at runtime. Whether PII is actually stored plaintext depends on ENCRYPTION_KEY (code falls back to it) — must verify. Covers why validate_production missed it, the 07-08-26 backfill question, seed-script relaxation revert, and fix sketch."
date: 26-10-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
  phase: seed-verified-tinyfish-followup
---

# Prod `PII_ENCRYPTION_KEY` is empty — PII-at-rest encryption unverified (26-10-26)

**Status: RESOLVED (14-11-26) — no plaintext at rest; fallback key works. Residual: fragile config (P2).**

## 0. Resolution (verified read-only on prod, 14-11-26)

- `PII_ENCRYPTION_KEY` is empty on Railway, **but `ENCRYPTION_KEY` is a valid Fernet key**, so
  `pii_crypto._get_fernet()` uses it — encryption has been working via the fallback.
- All 11 `*_ciphertext` columns on prod: **0 non-Fernet values** — no plaintext PII stored
  (this also clears the §4 07-08-26 backfill question).
- Remaining risk = fragile config: PII encryption silently depends on the general `ENCRYPTION_KEY`,
  and `validate_production` does not check PII keys. A separate PR adds PII-key checks to
  `validate_production` (§6 step 4).
- §5 done: `scripts/seed_verified_visitors.py` remote mode now REQUIRES an effective Fernet-valid
  key (`PII_ENCRYPTION_KEY or ENCRYPTION_KEY`), exit 5 otherwise — passes on prod's real shape.

Original (pre-verification) analysis below is kept for history. Original priority was HIGH.

**Bottom line:** `PII_ENCRYPTION_KEY` is empty in prod, but that alone does **not** prove plaintext
storage — `pii_crypto._get_fernet()` falls back to `ENCRYPTION_KEY`. Plaintext happens only if
`ENCRYPTION_KEY` is ALSO empty/invalid, or if `APP_ENV` makes `validate_production` skip. Verify
first (§3), then fix (§6).

## 1. Observed (orchestrator, 26-10-26 — values never read, only set/empty)

- Railway project `retarget-agent`, env `production`, service `retarget-agent` (api.getbeam.fyi):
  `PII_ENCRYPTION_KEY` variable exists but resolves **empty** via `railway run`. `PII_HMAC_KEY` is set.
- `ENCRYPTION_KEY` and `APP_ENV` were **not** checked — they decide the outcome (§2).

## 2. Code facts (read 26-10-26)

- `apps/api/config.py:1162` — `pii_encryption_key: str = ""` (comment: falls back to `encryption_key`).
- `apps/api/services/pii_crypto.py:45-57` `_get_fernet()` — key = `pii_encryption_key or encryption_key`.
  Returns `None` (→ passthrough) only if both are empty, **or** the key is malformed
  (logs `pii_fernet_init_failed`, degrades silently — never crashes).
- `pii_crypto.py:73-81` `encrypt_pii` — `None` cipher → logs `pii_encrypt_no_key_passthrough`, returns **plaintext**.
- `pii_crypto.py:84-` `decrypt_pii` — non-ciphertext returned as-is (so reads look fine either way).

### Why `validate_production` (config.py:15-43, called via `validate_secret_key()` at `main.py:96`) did not catch it

1. It **never checks `pii_encryption_key` or `pii_hmac_key`** — only `APP_SECRET_KEY`,
   `TOKEN_ENCRYPTION_KEY`, `ENCRYPTION_KEY` (non-empty).
2. The `ENCRYPTION_KEY` check is **non-empty only, not Fernet-valid**. A malformed key passes boot,
   then `_get_fernet()` swallows the init error → plaintext passthrough.
3. It returns early when `APP_ENV` ∈ `{development, test, local, ci}` — if prod's `APP_ENV` is one of
   those, no check runs at all.

So `all-context.md`'s "PII … encryption keys required in prod (`validate_production`)" and "prod
startup fails fast if missing" are **overstated**: true for `ENCRYPTION_KEY` presence only.

## 3. Verify (operator) — decides whether this is a real breach or a config-hygiene gap

1. Railway: is `ENCRYPTION_KEY` set (set/empty only) and what is `APP_ENV`?
2. Railway logs: grep `pii_encrypt_no_key_passthrough` and `pii_fernet_init_failed`. Any hit = plaintext writes.
3. DB spot-check (Supabase `hylcleqxlkdblibpdhhm`, never print values): count rows in
   `visitor_emails`, `identified_visitors`, `enrichment_profiles`, `beam_identity_graph` whose
   `*_ciphertext` columns do **not** start with Fernet prefix `gAAAAA`.
   - 0 non-Fernet rows → encryption works via `ENCRYPTION_KEY` fallback; downgrade to P2 (set a
     dedicated key + harden validator).
   - >0 → plaintext PII at rest; keep HIGH.

## 4. Related: 07-08-26 backfill ("22/22 rows backfilled") — needs-verification

`apps.api.scripts.backfill_pii_ciphertext` uses the same `encrypt_pii`. If no valid key resolved
then, it wrote plaintext into the ciphertext columns. Covered by the §3 step-3 check.

## 5. Related: seed script relaxation — revert when fixed

`scripts/seed_verified_visitors.py` remote mode was relaxed 26-10-26 to require only `PII_HMAC_KEY`
(warns at ~line 423 when `PII_ENCRYPTION_KEY` is empty). Once a valid key is confirmed in prod,
restore the hard requirement (and update `tests/unit/test_seed_verified_visitors.py`). Note: the
script should check `PII_ENCRYPTION_KEY or ENCRYPTION_KEY`, mirroring `_get_fernet()`.

## 6. Fix sketch (not a plan)

1. Generate a Fernet key; set `PII_ENCRYPTION_KEY` on Railway for every service that writes PII
   (api + any worker/Celery services). **Caution:** if existing rows are already encrypted under
   `ENCRYPTION_KEY`, a NEW different key makes them undecryptable — either reuse that key's value or
   support MultiFernet / re-encrypt.
2. Deploy; confirm no new `pii_encrypt_no_key_passthrough` log events.
3. Backfill-encrypt existing plaintext rows (decrypt passthrough keeps reads working meanwhile).
4. Harden `validate_production`: require a Fernet-**valid** PII key (`pii_encryption_key or
   encryption_key`), and fail boot instead of degrading in `_get_fernet()` when not in nonprod.
5. Correct the two overstated lines in `process/context/all-context.md`.
6. GDPR/legal impact check if §3 finds plaintext rows (exposure window, notification duty).
