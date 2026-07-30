---
title: Beam local named tunnel and debug cleanup
date: 2026-07-29 19:23
severity: high
component: local dev tunnel and public API routing
status: resolved
---

## Context

The stable public API hostname is `https://beam.nhantown.com`, backed by a locally-managed named Cloudflare Tunnel. Real config and credential files stay outside Git under `%USERPROFILE%\.cloudflared`.

## What happened

We cleaned up the local Beam dev flow so the public URL and the local web app stop fighting each other. Root `.env` now points `API_BASE_URL=https://beam.nhantown.com`, which means the generated pixel snippet uses the public endpoint. `apps/web/.env.local` keeps `NEXT_PUBLIC_API_URL=http://localhost:8000` for local UI work.

`dev-local.ps1` now validates, reuses, and starts `config-beam.yml`, allowlists the exact 3 Beam path regexes plus the final `404`, checks `/health/ready` and `/pixel/tracker.js`, supports `-NoTunnel`, stays ASCII-only for Windows PowerShell 5.1, and probes `127.0.0.1` so `localhost` resolving to `::1` does not trigger the 60-loop delay. It also restarts `cloudflared` when the config is newer than the running process and performs a live public forbidden-route `404` check before declaring Pixel ready.

## Reflection

This was annoying because the failure mode was self-inflicted twice: tunnel config drift and Windows localhost behavior. The dangerous part was not the bug, it was the false confidence. Cloudflare CLI commands without an explicit `--config` can read the default `config.yml` and mutate the wrong tunnel or DNS route. That is exactly the kind of mistake that wastes hours and looks “fine” until the wrong hostname stops working.

## Decisions

Security review forced the right boundary. Final Beam ingress now exposes only `/pixel/tracker.js`, `/api/v1/events/ingest`, and `/health/ready`; auth routes fall through to `404`. We removed the stray Beam rule from the studio tunnel and preserved the studio/splittrip rules. Credentials were never committed.

We also accepted that stale killed connectors can remain at the edge. The fix is to inspect tunnel info and clean up by exact `--connector-id`, not to guess.

## Next

Verification passed: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-local.ps1 -SkipInstall -NoBrowser` exited `0` in `35.9s`; local API/Web were `200`; public ready was `200`; tracker was `200 application/javascript`; ingest `OPTIONS` was `200`; auth `GET` was `404`; Windows PowerShell parse passed; scoped diff was clean except CRLF notices.

Studio readiness is currently `200`. `splittrip.nhantown.com` is `502` because its separate origin on `localhost:5173` is not running; that is not a Beam failure.
