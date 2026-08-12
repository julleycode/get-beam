---
title: "Privacy-block hook - APPROVED prefix never reaches the tool"
description: >-
  Hook chặn file nhạy cảm bảo agent thử lại với tiền tố "APPROVED:", nhưng hook exit 0 mà
  KHÔNG viết lại tool_input — nên công cụ vẫn nhận đường dẫn có tiền tố và fail. Kết quả:
  người dùng bấm duyệt nhưng file vẫn không đọc được. Tái hiện được 2 lần trong phiên 11-08-26.
status: pending
priority: P2
branch: "dev_nhantc2"
tags:
  - hooks
  - tooling
  - developer-experience
blockedBy: []
blocks: []
created: "2026-08-11T09:34:14.560Z"
createdBy: "ck:plan"
source: skill
---

# Privacy-block hook - APPROVED prefix never reaches the tool

## Overview

`.claude/hooks/privacy-block.cjs` chặn truy cập file nhạy cảm (`.env`…) và yêu cầu:

> *Retry the exact tool call with an approval-prefixed path such as `APPROVED:.env`*

Cơ chế này **không hoạt động**. Hook là `PreToolUse`; nó chỉ **cho qua hoặc chặn**. Khi thấy tiền
tố, nó bóc ra để **tự quyết định**, rồi `process.exit(0)` — nhưng `tool_input` **không đổi**. Công
cụ thật vẫn nhận `APPROVED:.env`, một đường dẫn không tồn tại.

Kết quả với người dùng: bấm "duyệt", agent thử lại đúng như hướng dẫn, **vẫn không đọc được file**.

## Bằng chứng (phiên 11-08-26, tái hiện 2 lần, 2 kiểu hỏng khác nhau)

**Kiểu 1 — Bash: hook cho qua, lệnh vẫn fail**

```
$ grep -oE "^(ENABLE_OSINT_SCAN|...)" APPROVED:.env
grep: APPROVED:.env: No such file or directory
```

Hook duyệt (exit 0), nhưng shell nhận chuỗi nguyên văn. Không có file tên `APPROVED:.env`.

**Kiểu 2 — Read với đường dẫn tuyệt đối: hook chặn lại, gợi ý tiền tố kép**

```
Read("APPROVED:d:\cong_viec\22-22\get-beam\.env")
→ PRIVACY BLOCK
  File: D:\cong_viec\22-22\get-beam\APPROVED:d:\cong_viec\22-22\get-beam\.env
  Retry with: "APPROVED:D:\...\APPROVED:d:\...\.env"
```

Harness phân giải `APPROVED:d:\…` thành đường dẫn tương đối theo CWD **trước khi** hook chạy,
nên tiền tố không còn ở đầu chuỗi → `hasApprovalPrefix()` trả false → chặn lại → gợi ý tiền tố
chồng tiền tố. Lặp vô hạn.

## Root cause

`.claude/hooks/lib/privacy-checker.cjs`:

```js
const APPROVED_PREFIX = 'APPROVED:';
function hasApprovalPrefix(p) { return p && p.startsWith(APPROVED_PREFIX); }   // dòng 61-63
function stripApprovalPrefix(p) { ... }                                        // dòng 70-75
```

`stripApprovalPrefix` chỉ dùng **nội bộ** để hook so khớp allowlist. `privacy-block.cjs:117-131`
xử lý nhánh `result.approved` bằng cách in thông báo rồi `process.exit(0)` — **không phát ra
bất kỳ output nào để harness viết lại `tool_input`**.

Hai khiếm khuyết độc lập:

| # | Khiếm khuyết | Ảnh hưởng |
|---|---|---|
| **B1** | Duyệt xong không viết lại `tool_input` | Bash + Read + mọi công cụ: tiền tố lọt tới công cụ thật |
| **B2** | `startsWith` không chịu được việc harness phân giải đường dẫn tuyệt đối | Read/Write với đường dẫn tuyệt đối: chặn lặp, gợi ý tiền tố kép |

Sửa B1 mà không sửa B2 thì đường dẫn tuyệt đối vẫn kẹt vòng lặp.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Reproduce and pick mechanism](./phase-01-reproduce-and-pick-mechanism.md) | Pending |
| 2 | [Fix and add tests](./phase-02-fix-and-add-tests.md) | Pending |

Phase 1 xác định **harness thật sự hỗ trợ cơ chế nào** — đây là ẩn số lớn nhất, và nó quyết định
Phase 2 làm gì. Không viết code trước khi biết.

## Blast radius

| File | Thay đổi |
|---|---|
| `.claude/hooks/lib/privacy-checker.cjs` | nhận diện tiền tố chịu được phân giải đường dẫn (B2) |
| `.claude/hooks/privacy-block.cjs` | phát output cho harness ở nhánh duyệt (B1) |
| `.claude/hooks/tests/privacy-block.test.*` | **file mới** — hiện **không có test nào** cho hook này |

**Không đụng:** mã sản phẩm trong `apps/`, hook khác, `settings.json`.

## Ràng buộc an toàn

Hook này là **rào chắn bảo mật**. Sửa sai = rò rỉ secret.

- **Fail-closed khi nghi ngờ.** Không nhận ra tiền tố → **chặn**, không phải cho qua.
- **Không nới định nghĩa "file nhạy cảm"** trong plan này. Chỉ sửa cơ chế duyệt.
- Giữ nguyên cảnh báo `Approved path is outside project` (`privacy-block.cjs:119-121`).
- Không bao giờ tự động duyệt. Người dùng vẫn phải bấm.
- Hook đang **fail-open khi crash** (`process.exit(0)` ở catch ngoài cùng). **Không đổi** —
  đó là chủ ý để hook hỏng không chặn cả phiên làm việc. Ghi nhận, không sửa ở đây.

## Không nằm trong phạm vi

- Đổi danh sách file nhạy cảm.
- Các hook khác (`post-write-plan-check`, `post-commit-lint`, `scout-block`).
- **Đường dẫn Reports bị nhân đôi** trong output của `UserPromptSubmit` hook —
  `d:\...\get-beam\D:\...\get-beam\plans\...`, hiện ở **mỗi lần nhập lệnh**. Lỗi khác, hook khác,
  mức rủi ro khác (chỉ xấu mắt, không chặn việc). **Chốt ở validate 11-08-26: giữ riêng, chỉ ghi
  nhận** — gom vào sẽ làm plan bảo mật này loãng. Chưa có plan riêng; ghi ở đây để không mất.
- **Hạ tầng test cho các hook khác.** Phase 2 dựng quy ước tối thiểu vừa đủ cho hook này.
  Không dựng CI, coverage, hay helper dùng chung.

## Điều kiện hoàn thành

- [ ] Người dùng bấm duyệt → agent đọc được file **ở lần thử lại đầu tiên**
- [ ] Đúng với cả `Read` và `Bash`, cả đường dẫn tương đối lẫn tuyệt đối
- [ ] Không có vòng lặp gợi ý tiền tố kép
- [ ] Không duyệt thì vẫn chặn (không hồi quy bảo mật)
- [ ] Có test tự động — hiện tại là **0**

## Validation Log

### Session 1 — 11-08-26 (`/ck:plan validate`)

**Verification Results**
- Claims checked: 10
- Verified: 9 | **Failed: 1** | Unverified: 0
- Tier: Light (2 phases → Fact Checker)
- Đã xác minh: nhánh duyệt `privacy-block.cjs:117-131`; `hasApprovalPrefix` dùng `startsWith`
  (`privacy-checker.cjs:61-63`); `stripApprovalPrefix` 70-75; nhánh Bash regex dòng 136;
  export để test 159-168; fail-open ở catch dòng 174; cảnh báo suspicious 119-121;
  hook được nối ở `.claude/settings.json:44`.

**❌ FAILURE 1 — `.claude/hooks/tests/` không tồn tại**

Phase 2 bản đầu viết `Create: .claude/hooks/tests/privacy-block.test.cjs` như thể chỉ thêm một
file. Kiểm thật: thư mục **không có**, và **không có test cho bất kỳ hook nào** trong repo,
không test runner, không script `test`. Việc thực tế là **dựng quy ước test từ số không**.

→ Đã sửa Phase 2: thêm mục cảnh báo, chốt quy ước (`node:test`, `node --test`, không thêm
dependency), thêm tiêu chí hoàn thành và rủi ro phình phạm vi.

**🔍 Phát hiện thêm — phương án bị bỏ sót**

`privacy-block.cjs:36` gọi `isHookEnabled('privacy-block')`; `vc-config-utils.cjs:902-907` cho
biết `hooks."privacy-block": false` là tắt hook. **Một dòng config.** Phase 1 chỉ liệt kê 3
phương án. → Đã thêm **phương án D** kèm đánh đổi rõ ràng.

**✅ Giải sẵn một ẩn số**

Phase 1 yêu cầu ghi phiên bản Claude Code → **`2.1.226`** (đo lúc validate). Đã điền sẵn; lúc
thực thi chỉ cần xác nhận lại nếu đã đổi.

**Quyết định người dùng chốt**

| # | Câu hỏi | Chốt | Lan xuống |
|---|---|---|---|
| H1 | Không có hạ tầng test hook — làm sao? | **Dựng quy ước tối thiểu** (`node:test`, 0 dependency) | Phase 2 |
| H2 | Có đưa "tắt hook" thành phương án không? | **Có — phương án D**, kèm đánh đổi | Phase 1 |
| H3 | Gộp lỗi Reports-path vào không? | **Không — giữ riêng, chỉ ghi nhận** | plan.md §Ngoài phạm vi |

### Whole-Plan Consistency Sweep

| Kiểm | Kết quả |
|---|---|
| Phase 1 còn ghi "3 phương án" sau khi thêm D | ✅ Đã sửa thành 4, kể cả tiêu chí hoàn thành |
| Phase 2 còn giả định thư mục test đã có | ✅ Đã sửa, đánh dấu là thư mục mới |
| Lệnh test gate còn dùng `node <file>` thay `node --test` | ✅ Đã sửa |
| Phase 2 chưa xử lý ca "Phase 1 chốt D" | ✅ Đã thêm: chốt D thì Phase 2 **không chạy** |
| Phiên bản Claude Code còn để trống | ✅ Đã điền `2.1.226` |
| Mục ngoài-phạm-vi phản ánh quyết định H3 | ✅ Đã cập nhật |

**Mâu thuẫn chưa giải quyết: không có.**

## Dependencies

Không phụ thuộc, không chặn ai.

**Liên quan:** `plans/260811-1611-social-resolution-accuracy/` — lỗi này phát hiện trong lúc làm
plan đó (mục ngoài-phạm-vi). Không chặn nhau; sửa hook không phải điều kiện để cook plan kia.
