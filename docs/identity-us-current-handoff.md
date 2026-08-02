# Handoff hiện tại: Identity US

> Đọc file này trước nếu bạn phải tiếp tục visitors-identity. Đây là bản handoff ngắn cho Trân và AI kế tiếp.

Kết luận ngắn: các thay đổi hiện tại làm an toàn hơn và đo đúng hơn, nhưng chưa làm số visitor US định danh đúng tăng lên trong dữ liệu local live.

Viết tắt: RB2B = vendor person-graph/pixel; `Candidate` = `provider_candidate`; `Verified` = `verified`; US = visitor ở Mỹ; P1/P2 = hai phase đang bàn.

## Trạng thái nhanh

| Phần việc | Trạng thái thật | Ý nghĩa |
|---|---|---|
| P0 quality gates | Committed tại `f11004e`: RB2B parser chặn hashed email-like values, enrich/normalize profile + tests | Mốc an toàn đã có trong Git |
| P1/P2 status + observability | Code/tests có trong dirty worktree; completion report có nhưng folder vẫn nằm ở `active/` | Chưa coi là bàn giao bền vững trước khi review, commit và dọn trạng thái plan |
| Coverage Phase 1 Leadpipe | Structural/unit test xong, nhưng live **FAILED / BLOCKED** | Account expired, 0 active pixel, API 403 và tracker URL 404 |
| Coverage Phase 2-4 | Pending; đang có hai plan Phase 2 cạnh tranh | Phải chọn/reconcile một plan duy nhất rồi VALIDATE trước khi EXECUTE |

## Flow cũ vs mới

```text
Old:
provider save -> "identified" ngay
success log ghi quá sớm
paid identity trộn vào emailable/KPI

New in-flight:
quality gates -> provider_candidate -> independent proof -> verified
log success chỉ sau khi persistence OK
Candidate bị tách khỏi emailable và verified KPI
```

| Mặt | Cũ | Mới đang hướng tới |
|---|---|---|
| Định danh paid graph | Cứ save là tính `identified` | Trước hết là `provider_candidate` |
| Xác nhận thật | Không tách rõ | Chỉ `verified` sau proof độc lập / first-party |
| Log resolution | Có thể ghi success trước save | Chỉ ghi success khi save OK |
| KPI | Paid candidate dễ bị tính nhầm | Candidate phải tách riêng, không giả vờ là verified |

## Evidence runtime

- Docker: PostgreSQL 16 và Redis 7 đang healthy.
- Local DB: `sites=2`, `auto-identify sites=0`, `verified pixels=1`.
- Local visitors: `17` tổng, `8` US.
- US status: `7` unresolvable + `1` legacy identified.
- Row identified duy nhất có mismatch tên/email rõ ràng, nên baseline đúng thực tế hiện tại là gần như `0/8`.
- `6/7` US-unresolvable có resolution log gần đây và đang nằm trong retry lock 30 ngày.
- Leadpipe logs = `0`.
- US RB2B logs = `13` attempts, `8` success logs, nhưng toàn bộ success dồn vào đúng 1 visitor false-positive.
- Fresh test: `50 passed + 52 passed = 102 passed`; `git diff --check` passed. Đây là bằng chứng code-path, không phải bằng chứng live uplift.
- Live Leadpipe read-only checks: key shape `sk_` dài 67, pixel UUID dài 36; account endpoint 200 nhưng `healthy=false`, `org_status=expired`, `credits_remaining=500`, `pixels_total=0`, `pixels_active=0`.
- `/v1/data?domain=beamlab.nhantown.com` = 403; `/v1/data/pixels` = 403; URL dựng từ local UUID `https://leadpipe.aws53.cloud/p/<uuid>.js` = 404.
- Official docs yêu cầu dùng [exact install code và verify pixel](https://docs.leadpipe.com/guides/manage-pixels); [API tạo pixel trả về `code`](https://docs.leadpipe.com/api-reference/pixels/create-a-pixel-for-a-domain). Cách dựng URL từ UUID trong repo chưa được chứng minh là đúng.
- Buổi điều tra chỉ đọc DB/provider state; không đổi DB row, deployment, commit hay paid-provider state. Các file tài liệu này là thay đổi duy nhất của buổi bàn giao.

## Việc cần làm tiếp theo

1. Chọn/reconcile một plan authoritative duy nhất cho Phase 2: [coverage Phase 2](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-02-wire-candidate-ingest-from-vendor-callbacks.md) hay [plan cookie/fingerprint mới](../plans/260802-1854-cookie-fp-phase2/plan.md).
2. Chốt quyết định business: re-activate Leadpipe hay replace/drop nó.
3. Sửa plan rồi VALIDATE lại: dùng exact provider install code/URL, thêm provider-health preflight, coi 403/5xx là provider failure thay vì khóa 30 ngày no-match, và giữ KPI `Candidate` tách khỏi `Verified`.
4. Chỉ EXECUTE sau khi VALIDATE xong và plan đã rõ.
5. Chỉ bật Lab auto-identify sau khi provider/pixel health được xác minh, rồi làm controlled retry có backup/approval.
6. Sau đó chạy smoke US 5 session, rồi benchmark N>=30 trước khi quyết định production.

## Không làm lúc này

- Không bật `auto-identify` bây giờ.
- Không reset DB.
- Không coi `Candidate` là `Verified`.
- Không deploy hoặc commit nếu chưa được phép.

## Nguồn tham chiếu

### Hiện hành

- [P0 quality gates đã hoàn tất](../process/features/visitors-identity/completed/identity-p0-quality-gates_02-08-26/identity-p0-quality-gates_PLAN_02-08-26.md)
- [P1/P2 completion report](../plans/reports/pm-260802-1830-identity-p1p2-status-observability-complete-report.md) — evidence nói complete, nhưng folder plan vẫn ở `active/`.
- [Identity coverage program](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/plan.md)
- [Phase 1 report Leadpipe pixel PoC wiring](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-01_REPORT_02-08-26.md) — structural/unit evidence; live status trong report đã bị evidence mới ở file này thay thế.
- [Coverage Phase 2](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-02-wire-candidate-ingest-from-vendor-callbacks.md)
- [Plan cookie/fingerprint Phase 2 mới](../plans/260802-1854-cookie-fp-phase2/plan.md) — phải reconcile với coverage Phase 2 trước khi chạy.
- [Phase 3 Fingerprint Pro device continuity](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-03-fingerprint-pro-device-continuity.md)
- [Phase 4 US ground-truth benchmark pack](../process/features/visitors-identity/active/identity-coverage-pixel-fppro_02-08-26/phase-04-us-ground-truth-benchmark-pack.md)

### Stale / historical

- [Giải pháp "người đứng sau AI" - cách cũ vs cách mới](./ai-behind-solution-old-vs-new.md) - đọc để hiểu kiến trúc cũ/mới, nhưng phần provider-key và trạng thái live đã cũ.
- Folder trong request cũ `identity_resolution_coverage_01-08-26` hiện không phải tên disk thật; folder thực tế là `identity-coverage-pixel-fppro_02-08-26`.

## Unresolved questions

- Leadpipe nên bật lại, thay bằng provider khác, hay bỏ khỏi đường coverage?
- Coverage Phase 2 hay plan cookie/fingerprint mới sẽ là authoritative?
- Candidate KPI nên hiển thị riêng ở đâu để người xem không nhầm với Verified?
