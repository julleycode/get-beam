# Scout Report: Phase 2 Edge Preflight

## Decision

- Public hostname: `studio.nhantown.com`.
- Internal tunnel name proposed: `nhantown-studio`.
- Tunnel model: locally managed named tunnel, because Phase 2 requires a versioned ingress YAML with an explicit `/_lab` deny rule.
- No Cloudflare DNS, tunnel, rule, or account setting was changed during this scout.

## Why This Hostname

- Neutral and plausible for the planned synthetic studio/portfolio surface.
- Does not expose the experiment through `lab`, `test`, `bot`, `canary`, or `detect`.
- Public DNS check on 2026-07-28 returned no A/AAAA/CNAME for the root and NXDOMAIN/no public record for `studio`, `atelier`, `works`, and `journal`.
- Public web searches for `nhantown.com` and `studio.nhantown.com` returned no indexed result.
- This is public-footprint evidence, not proof of account-internal Cloudflare state. The cook session must re-check the exact DNS target before creating it.

## Cloudflare Prerequisites

1. Cloudflare account access to zone `nhantown.com`.
2. Elevated Windows shell for installing `cloudflared` and services.
3. Browser authorization for `cloudflared tunnel login`.
4. Create the named tunnel, then route `studio.nhantown.com` to it.
5. Keep `cert.pem`, tunnel credential JSON, tunnel token, API token, account ID, and zone ID out of Git.
6. App snapshot token should be read-only and least-privilege. Start with Zone Read and Zone Settings Read. Reading cache/WAF configuration uses the Rulesets API, so add the applicable Account Rulesets Read or Account WAF Read scope; add Cloudflare Tunnel Read/Cloudflare One Connectors Read only if the snapshot consumes tunnel metadata.
7. No documented read API was found for every AI Crawl Control/Block AI Bots setting. Record those unavailable fields through a manual verified override or `unknown`, with dashboard screenshots kept outside tracked source.

## Edge Settings To Fix Before Observation

- Bot Fight Mode: Off. It is domain-wide on Free and cannot be skipped with a WAF custom rule.
- AI bot policies: Search, Agent, and Training set to Allow.
- AI Crawl Control: no per-crawler Block action or generated WAF blocking rule.
- Managed robots.txt: Off, because the origin owns the experiment's dynamic robots policy.
- Cache Rule: `http.host eq "studio.nhantown.com"` with Bypass Cache, ordered after conflicting cache settings so it wins.
- Origin public/canary/robots responses: `Cache-Control: no-store`.
- Manual verification accepts `CF-Cache-Status: DYNAMIC` or `BYPASS`.

Current references:

- [Bot Fight Mode](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/)
- [AI bot policies](https://developers.cloudflare.com/bots/additional-configurations/block-ai-bots/)
- [AI Crawl Control actions](https://developers.cloudflare.com/ai-crawl-control/features/manage-ai-crawlers/)
- [Managed robots.txt](https://developers.cloudflare.com/ai-crawl-control/features/track-robots-txt/)
- [Cache Rule settings](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/)
- [Cache Rule order](https://developers.cloudflare.com/cache/how-to/cache-rules/order/)
- [Cache response status](https://developers.cloudflare.com/cache/concepts/cache-responses/)

## Tunnel Contract

Recommended ingress order:

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: <ABSOLUTE-PATH-TO-TUNNEL-JSON>
ingress:
  - hostname: studio.nhantown.com
    path: ^/_lab(?:/.*)?$
    service: http_status:404
  - hostname: studio.nhantown.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

- Public app: `127.0.0.1:8000`.
- Private dashboard app: `127.0.0.1:8001`, never listed in ingress.
- Validate config and rule matching before service install.
- The Windows service expects its effective config in the documented service location; copy from the versioned template without committing real credentials.
- Current Cloudflare routing docs say visitors normally receive error 1016 when a tunnel stops. Acceptance therefore checks Cloudflare 5xx/tunnel unavailable and explicitly rejects origin 404, rather than pinning 1033/530.

References:

- [Locally managed tunnel configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
- [Windows service installation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/)
- [Tunnel routing and stopped-tunnel behavior](https://developers.cloudflare.com/tunnel/routing/)
- [Tunnel permissions and credential files](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/tunnel-permissions/)

## Repo Work Required By Phase 2

- Split public and dashboard app factories/ports.
- Add edge snapshot schema and immutable snapshot service.
- Add read-only Cloudflare API adapter with explicit `unknown` fallback.
- Add synthetic public pages and dynamic robots policy.
- Add public `/_lab` 404 protection plus ingress 404.
- Add versioned cloudflared template, Windows service installer, and operator checklist.
- Add tests for snapshot reuse/change, robots/no-store, app isolation, and ingress matching.
- Extend `.gitignore` before generating Cloudflare credentials.
- Resolve the current `.env` mismatch: README says to copy `.env.example`, but the app only reads process environment and does not load `.env`. Phase 2 must either load `.env` explicitly or inject variables through the Windows services.
- Add schema through `src/beam_lab/db/migrations/002-edge-config-snapshot.sql`; do not modify the canonical `schema.sql` marker.

Phase 1 remains green (15 tests). Phase 2 can start directly from its phase file after reading this report.

## New Session Command

```text
/ck:cook D:\cong_viec\demo_28\plans\260728-1451-beam-ai-detection-lab-mvp\phase-02-edge-deployment-config-snapshot.md
```

Read first:

1. `README.md`
2. This preflight report
3. The Phase 2 file

Locked decisions: `studio.nhantown.com`, locally managed named tunnel, proposed internal name `nhantown-studio`, public app `127.0.0.1:8000`, dashboard `127.0.0.1:8001`, dashboard absent from ingress, Bot Fight Mode Off, AI bot policies Allow, managed robots.txt Off, hostname-wide cache bypass.

## Manual Gates During Cook

- Do not create DNS until local public app, ingress validation, and credential ignore rules are ready.
- Re-check `studio.nhantown.com` immediately before DNS creation.
- Ask the operator to complete browser login/dashboard toggles when Cloudflare needs interactive account authority.
- Test from an external network: public page 200, public `/_lab` 404, dashboard local-only, cache not served, and tunnel stop produces Cloudflare unavailable rather than origin 404.
- Reboot acceptance requires both cloudflared and both uvicorn services to recover.

## Unresolved Inputs

- Cloudflare account ID, zone ID, tunnel UUID, and local credential path: discover/create during cook; never paste secrets into chat or commit them.
- `cloudflared`, `sc.exe`, `powercfg`, and `curl` are present on the current machine; NSSM is not. Choose the uvicorn service wrapper during cook and verify its installation source.
- Exact synthetic copy and visuals: implement inside Phase 2's existing portfolio/company scope.
