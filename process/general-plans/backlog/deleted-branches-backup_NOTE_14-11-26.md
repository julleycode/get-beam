---
name: deleted-branches-backup
description: SHA of every remote/local branch deleted in the 14-11-26 repo audit cleanup, for restore
date: 2026-11-14
---

# Deleted branches backup (14-11-26)

Restore any branch with: `git push origin <sha>:refs/heads/<name>` (objects stay reachable via this note's SHAs only while unpruned; tag `backup/*` refs keep the important ones).

| branch | sha | last commit |
|---|---|---|
| claude/repo-audit-backlog-a0af86 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| claude/visitor-seed-tinyfish-integration-e3d167 | afdcb36cb38143d2c1c0d59f34d603167f148fc0 | 2026-10-25 process: Phase 2 plan + report (active; P2-G7/G8 pending Docker) |
| feat/agentic-commerce | 1df9a805ebbcb187c188bc0cf9410fbf3f5eb848 | 2026-10-25 revert: remove agentic commerce integration (payments) from main |
| feat/agentic-commerce-old | 097ba90973dd7ce5775781c586c6f83286e23026 | 2026-10-01 feat(api): add AEP Service tables and migration |
| feat/ws1-ai-evaluation-timeline | 86d8d0ba96d47f4249a92ea6e21e4249177a3ad6 | 2026-11-14 docs(process): agent-native-revenue WS1 plan + report |
| feat/ws3-agent-concierge | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| fix/gdpr-erasure-gaps | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| fix/live-security-hardening | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| fix/tinyfish-x402-hardening | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a0948f10fdb07d23a | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a20d3248b01f91a5a | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a24b55b3ec35a5914 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a2aeb014272dc1d3b | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a5ab0bce97638bf92 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-a6c2464f152bf3739 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-ab8b79884f6ffec13 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-ad4f1dcf1209d4297 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| worktree-agent-af7ff547db542b9f4 | 6ef19f7be7f994635a8a79e5a280abeca9c2a2f7 | 2026-10-25 docs(agent-gateway): add InFlow x402 seller plan and results |
| origin/UAT | 717cd644c223a618017d3e41875e88b7195309d8 | 2026-07-28 feat(web): collapsible Filters panel + solid card background on the visitors table |
| origin/backup/main-2026-08-10 | 8edb7d766280156f3161cc0e527a6c2ce0935068 | 2026-08-09 docs(cloudflare): pin beam-agent-beacon-splittrip as canonical Worker |
| origin/ci/social-resolver-verify | 657bcf01f56964fbf0d1784c30cbfc4cdd018923 | 2026-06-16 feat(social): signal-based identity confidence for resolved handles |
| origin/claude/dazzling-bose-63fc94 | 2034488a54ade91c6d1097f28edba7b68171050b | 2026-06-07 feat: Phase 1+2 gap closure — rate limiting, persistent tracking, GeoIP cache, VPN detection, email validation, email dedup, server-side cookie |
| origin/claude/gracious-buck-9f51ab | afa9582aba2daa6f7876f2a7318cab2a99883785 | 2026-06-06 fix: add stripe to root requirements.txt for Docker build |
| origin/claude/loving-lichterman-08d8c4 | 2dcf67faa9dbd356f510a691deaeb97c2250941e | 2026-06-07 feat: deep research enrichment via Claude API + daily usage caps |
| origin/claude/practical-shamir-168a8b | e589e112b6cab5672bdd25f8b31c823acd65f2d5 | 2026-06-06 feat: end-to-end feature request management — PATCH endpoint, email notifications, dashboard UI |
| origin/claude/xenodochial-mestorf-bc8715 | 7dacf0b083afbd4a8a4c52d7973b28d52278e33e | 2026-06-06 feat: convert "how beam works" modal to auto-scrolling carousel |
| origin/codex/visitors-upgrade-flow | 04e01487c35d17c208f1e6d856fd10422ac74156 | 2026-07-10 fix(billing): enforce paid-plan expiry and close Gumroad audit findings |
| origin/dev_nhantc2 | a7ae2501fa9b3dde6d6b041b0ac4324133704b3f | 2026-08-18 chore(infra): sync agent-beacon-worker lab config |
| origin/devjulley | ec15a4067f4478431380ed4bea5c929fbb94cb55 | 2026-08-11 Merge remote-tracking branch 'origin/main' into devjulley |
| origin/feat/beam-branding | 7fdc57e5da4bc4f5f5e7c518a9b975f80dfef487 | 2026-06-09 feat(dashboard): Beam branding — logo mark + brand-pink theme |
| origin/feat/blog-content-studio | aaa4b49f73aedfc5bcaef44887f28dc9a704159f | 2026-06-13 feat(onboarding): resumable setup + AI-agent pixel install (#60) |
| origin/feat/eu-consent-and-settings-dissolve | 77938f96600752c3306d2715a5cb65c15a4f8857 | 2026-07-01 feat(consent): EU-gated cookie consent + dissolve Settings tab |
| origin/feat/gumroad-webhook | c0330a3d32b51b95a3dab8886f6017481ea0fd3b | 2026-06-30 feat(billing): Gumroad webhook to auto-provision plans (fallback MoR) |
| origin/feat/landing-storytelling | 4e2c1c4c366b785e6bae88fea934a808183c122d | 2026-06-04 revert: restore original sky gradient + clouds for hero |
| origin/feat/maxmind-asn-datacenter | e3be30d943c8f73b868b295d0120babc02ae7068 | 2026-07-01 feat(bot-filter): local MaxMind GeoLite2-ASN datacenter detection (free, offline) |
| origin/feat/own-data-p1-svid-reconcile | 1707337da911ba17cd107c60cb73c60bc847db70 | 2026-06-30 feat(identity): durable _rta_svid reconciliation — recover returning visitors free (own-data P1) |
| origin/feat/own-data-p2-coverage-metric | 45cde060983608b70dabd525208b9ab1c5a442b1 | 2026-06-30 feat(costs): owned-vs-paid identity coverage metric (own-data P2) |
| origin/feat/own-data-p3-provider-toggles | 74f0448cf88750373599fee7a9c37108a8379bf8 | 2026-06-30 feat(identity): per-provider on/off toggles + stop auto-PDL on owned emails (own-data P3) |
| origin/feat/own-data-p4-capture | 2319337af8740e9426d41cb76adfe616971d014b | 2026-06-30 feat(pixel): capture email on blur/change + window.beamIdentify (own-data P4) |
| origin/feat/own-data-p5-known-contacts | 1b30d0f1abdbc9841d243af1352a21624c4241ac | 2026-06-30 feat(targeting): exclude known-contacts from net-new exports/pushes (own-data P5) |
| origin/feat/own-data-p6-graph-email-match | 11e597f67bdd9e03020190d6cbc79eb9b5665c9c | 2026-06-30 feat(identity): cross-customer graph match by hashed email (own-data P6) |
| origin/feat/own-data-p7-deterministic-capture | 6f05feea401a05fe1646debaa4982aac979d0319 | 2026-07-01 feat(identity): decorate campaign links with _bid — deterministic click→identity (own-data P7) |
| origin/feat/own-data-p7b-known-routing | 71ad3c52c1ce98618ecef9baf00e7897de13f1ff | 2026-07-01 feat(identity): known-contact routing — skip paid enrichment for CRM-known visitors (own-data P7b) |
| origin/feat/own-data-p7c-esp-click-redirect | 90e5acc0469392bdeb0bd5faf66224f78496c103 | 2026-07-01 feat(identity): ESP click-tracking redirect — day-zero residential de-anon (own-data P7c) |
| origin/feat/private-beta | 0d90ce587f01f81c4845be1092457e832cf7a064 | 2026-06-06 feat: switch to private beta — waitlist mode |
| origin/feat/real-identification-onboarding | 202fcd5112e23c7adba76aba674feab9f7f2869f | 2026-06-03 fix: resolve merge conflicts — rebase onto squash-merged main |
| origin/feat/shared-empty-states | 66f551e3a700515f468b0597af677d14b2d2122c | 2026-06-12 feat(web): unlock-condition empty states for Segments, Campaigns, Exports |
| origin/feat/visitors-ux-explainer | 2a5877512d6b40f7d4aeba3f29df8b1c38ef80ec | 2026-06-12 feat(web): visitors page UX — column tooltips, pipeline explainer, Resolve now |
| origin/feat/waitlist-journey | d079015f6621580a76b2c97a924b70d0a6941ade | 2026-06-06 resolve merge conflicts — keep waitlist branch changes |
| origin/feat/ws1-ai-evaluation-timeline | cc149fd584975d3887916816df412255e82a1f09 | 2026-07-30 docs(process): agent-native-revenue WS1 plan + report |
| origin/feat/ws2-agent-session-classifier | c2f9bad11420fe927097bed6600dc4529c535c78 | 2026-07-30 docs(agent-native-revenue): WS0 ops-gate runbook (billing→merge→prod env→wild test) |
| origin/feat/ws3-agent-concierge | 6e97662eab156b7cca7886e62864e7fd075c35e3 | 2026-08-01 chore(skills): bump yc-application-coach submodule (frontmatter name field) |
| origin/fix/billing-stripe-return | fd1fe269186a065ff2bb9fe19cf0df21f3ff3efe | 2026-06-09 fix(billing): wrap useSearchParams in Suspense — fixes crash on Stripe return |
| origin/fix/clerk-signup-proper | 412f207cb8386e50fc7f09c0311c2989bf60b7e2 | 2026-06-04 fix: proper Clerk SignUp/SignIn with dynamic import + fallback |
| origin/fix/copy-bounce | cdf4a79d4f0141452cb7a6ab86232e29c5db8862 | 2026-06-06 fix: copy tweak — "no email. no signup. no form. just a bounce." |
| origin/fix/copy-spam | 88669344a5c00695061f0749ade936ca8ea721d6 | 2026-06-06 fix: remove "spent weeks building" line + "linkedin spam" → "spam" |
| origin/fix/datacenter-bot-asn-filter | 999128088f45a940cd221d2dd776b739e4029a61 | 2026-06-30 fix(bot-filter): ASN-based datacenter classification + resolver fabrication guard |
| origin/fix/endcard-sky-theme | 2ba16e845156110c52d740baafc443570c33e906 | 2026-06-06 fix: endcard back to sky theme with original copy |
| origin/fix/feature-request-modal | ad657d4359d533069cf9c315f30c15af68f6a42b | 2026-06-09 fix(landing): clean feature-request success popup + drop eyebrow badge |
| origin/fix/identify-ux | 75e162d2bee0a35a9f940fb586e117346c14006f | 2026-06-04 fix: skip misleading skeleton on home wifi + better email error |
| origin/fix/invite-flow | 9e59f7d64f1cbdb4694eb4092c5e68876d1ff91f | 2026-06-09 fix: working private-beta invite flow + clearer waitlist actions |
| origin/fix/invite-signup-multistep | a62ed05a6800a11789c471e077b010db0a03ce3b | 2026-06-09 fix(signup): keep invite token across Clerk's multi-step signup |
| origin/fix/onboarding-polish | ff69b9e8df4b1f355a33f66a0e330446e69a9659 | 2026-06-04 fix: remove last hardcoded 'julley tran' — dashboard preview now dynamic |
| origin/fix/pure-sky-bg | 418edb30a01f483c0de728c7b862cbeb960af7ae | 2026-06-06 fix: pure sky background — remove mountains, fields, sand stripe |
| origin/fix/real-identification-clean | 719fdc034e037ebf8007371aaf3f620303d7f680 | 2026-06-03 feat: 3 USP features — social intelligence, engagement flywheel, auto-drafts |
| origin/fix/security-hardening | c7966d55dee59c6886999f4206b72cd6f326e192 | 2026-06-09 fix: security hardening for private beta |
| origin/fix/signin-redirect-loop | e1f411274e20d1d9fe25526d4aaf64c83649099b | 2026-06-09 fix: stop /sign-in redirect loop — route home by Clerk session |
| origin/fix/signup-pricing-messages | 4a4f072a615daa27181d8d85642edc652025fccd | 2026-06-04 fix: sign-up 404 + pricing $19/$49 + remove confusing messages |
| origin/fix/signup-redirect | e981cefa580ab00d09f577b120f19faae70b062b | 2026-06-04 fix: /sign-up and /sign-in redirect to legacy pages |
| origin/fix/slot-counter | ce2543653087f6a93d3e6889d5d05f223e782b83 | 2026-06-09 fix: count approved + granted toward the public beta slot counter |
| origin/fix/waitlist-layout | adbc923db38f54886515a1e63452f375d00724d6 | 2026-06-06 fix: waitlist form layout — email+button inline, url below |
| origin/fix/x-handle | 136e341cf8aa44dc09c7455a42b7840b6c93aa32 | 2026-06-06 fix: update X handle @julleybuildbeam → @julleybuilds |
| origin/main-backup1_8 | 717cd644c223a618017d3e41875e88b7195309d8 | 2026-07-28 feat(web): collapsible Filters panel + solid card background on the visitors table |
| origin/main_backup_11-08-26 | 487b2dddce0e8c7ff55f7e16fd53720a3ed77861 | 2026-08-11 merge: onboarding canary into main |
| origin/perf/dashboard-ssr-prefetch | 90686a6d56b2292cbcc8fa01e875d695aac67a06 | 2026-06-21 perf(web): SSR-prefetch Overview data + non-blocking Clerk token gate |
