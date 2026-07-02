# Phase 5 — Chặn tính năng theo gói ở backend (lỗ #1)  ⬜

**⚠️ ĐỔI HÀNH VI — cắt user free đang dùng. Rủi ro CAO. Làm cuối, có công tắc env.**

Chia nhỏ. Mỗi sub-phase ship riêng được.

---

## 5a — Module entitlement (nền, không đổi hành vi)
Tạo `apps/api/services/entitlements.py` = nguồn DUY NHẤT:
```python
PLAN_FEATURES = {
  "free": {"sites": 1,  "ai_drafts": False, "social_enrichment": False, "api_access": False},
  "pro":  {"sites": 3,  "ai_drafts": True,  "social_enrichment": True,  "api_access": False},
  "max":  {"sites": None,"ai_drafts": True, "social_enrichment": True,  "api_access": True},
}
def site_limit(plan)->int|None ; def has_feature(plan, key)->bool
```
- Dùng chung với `effective_plan` (Phase 3) và `PLAN_LIMITS` (gộp identify count vào đây luôn cho gọn).
- Công tắc: `settings.enforce_plan_features: bool = False` (mặc định TẮT).

## 5b — Giới hạn số site
- `create_site` ([sites.py:51](../../apps/api/routers/sites.py)): trước khi tạo, đếm site của user; nếu `>= site_limit(effective_plan(user))` và `enforce_plan_features` → HTTP 402 "Gói {plan} tối đa {n} website. Nâng cấp để thêm."
- **Grandfather** (Quyết định #1): chỉ chặn TẠO MỚI vượt hạn; site cũ giữ nguyên (không xoá, không khoá).

## 5c — Gate tính năng Pro+/Max
- AI reply drafts: `drafts.py` generate endpoint → cần `has_feature(plan,"ai_drafts")`.
- Social enrichment: đường `social_resolver`/enrich tier → cần `has_feature(plan,"social_enrichment")`.
- (AI ask `ai.py`, CRM push `crm.py`, exports `exports.py`: **xác nhận có nằm trong gói nào không** — pricing không nêu rõ. Nếu là tính năng chung thì ĐỪNG gate. Chỉ gate đúng cái pricing bán.)
- Mỗi gate: nếu `enforce_plan_features` và thiếu quyền → 402 + thông điệp nâng cấp. Grandfather: cân nhắc chỉ chặn hành động MỚI.

## 5d — HOÃN (chỉ sửa câu chữ, không gate giả)
- **Team seats**: chưa có hệ team trong code → bỏ khỏi pricing hoặc ghi "coming soon".
- **Priority identification**: chưa có cơ chế ưu tiên → bỏ/đổi câu.
- **API access**: chờ Quyết định #3 (có cổng API công khai không). Chưa có → xử như team seats.

## Touchpoints
- `apps/api/services/entitlements.py` (mới), `config.py` (toggle)
- `apps/api/routers/sites.py`, `drafts.py`, `social_resolver.py` (+ ai.py/crm.py/exports.py NẾU xác nhận gate)
- `apps/web` các chỗ gọi (hiện thông điệp 402 đẹp, nút nâng cấp)

## Blast radius — RÕ RÀNG: "ai bị cắt cái gì"
- User free tạo site thứ 2+ → bị chặn (site cũ vẫn chạy).
- User free dùng AI drafts / social enrichment → bị chặn.
- **Có grandfather + toggle mặc định TẮT** → ship an toàn, bật khi bạn sẵn sàng + đã báo user.

## Kiểm thử
- Toggle TẮT: hành vi y như cũ (regression).
- Toggle BẬT: free user 402 đúng chỗ; pro/max qua; site cũ vượt hạn vẫn đọc/dùng được.
- `npm run build` (lint) trước deploy.

## Rollback
`enforce_plan_features=false` (tức thì, không cần deploy lại nếu là env). Hoặc revert.
