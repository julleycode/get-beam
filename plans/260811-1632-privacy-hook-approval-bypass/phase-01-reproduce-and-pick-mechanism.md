---
phase: 1
title: "Reproduce and pick mechanism"
status: pending
priority: P2
effort: "S"
dependencies: []
---

# Phase 1: Reproduce and pick mechanism

## Overview

Ẩn số lớn nhất **không phải** "sửa thế nào" mà **"harness Claude Code hỗ trợ cơ chế nào"**.
Một `PreToolUse` hook có sửa được `tool_input` không, và bằng cú pháp gì?

Nếu **có** → sửa gọn, giữ nguyên trải nghiệm `APPROVED:`.
Nếu **không** → cơ chế tiền tố **về bản chất là không khả thi**, phải đổi thiết kế.

**Không viết code sửa ở phase này.**

## Requirements

- Tái hiện được cả hai kiểu hỏng bằng lệnh cụ thể, không mô tả suông.
- Trả lời dứt khoát: harness có cho hook viết lại `tool_input` không.
- Chọn cơ chế, ghi lý do, ghi cả phương án bị loại và vì sao.

## Bằng chứng đã có (phiên 11-08-26)

| Kiểu | Lệnh | Kết quả |
|---|---|---|
| Bash | `grep ... APPROVED:.env` | hook exit 0, `grep: APPROVED:.env: No such file or directory` |
| Read tuyệt đối | `Read("APPROVED:d:\...\.env")` | chặn lại, gợi ý tiền tố **kép** |
| Read tương đối | chưa thử | **chưa biết** |
| Write / Edit | chưa thử | **chưa biết** |

## Related Code Files

- Read-only: `.claude/hooks/privacy-block.cjs` (nhánh duyệt: dòng 117-131)
- Read-only: `.claude/hooks/lib/privacy-checker.cjs` (`hasApprovalPrefix` dòng 61-63,
  `stripApprovalPrefix` 70-75, nhánh Bash `command.match(/APPROVED:[^\s]+/g)` dòng 136)
- Create: `plans/260811-1632-privacy-hook-approval-bypass/reports/mechanism-survey.md`

## Implementation Steps

1. **Lập ma trận tái hiện** — 6 ca, ghi kết quả thật cho từng ca:

   | Công cụ | Đường dẫn tương đối | Đường dẫn tuyệt đối |
   |---|---|---|
   | Read | ? | ✗ đã biết hỏng (tiền tố kép) |
   | Bash | ✗ đã biết hỏng (lệnh fail) | ? |
   | Grep | ? | ? |

   Chạy thật từng ca, dán output nguyên văn. Đừng suy đoán ca chưa thử.

2. **Tra tài liệu harness** — `PreToolUse` hook được phép trả về gì trên stdout?
   Cụ thể kiểm những khả năng này có tồn tại không:
   - `hookSpecificOutput.permissionDecision`
   - trường kiểu `updatedInput` / `modifiedInput` để viết lại `tool_input`
   - JSON có cấu trúc trên stdout so với chỉ dùng exit code

   Dùng `claude-code-guide` agent hoặc tài liệu chính thức.

   **Phiên bản đã có sẵn (validate 11-08-26): Claude Code `2.1.226`.** Ẩn số này đã giải,
   không cần khảo sát lại — chỉ cần xác nhận lại nếu phiên bản đã đổi lúc thực thi
   (`claude --version`).

3. **Kiểm bằng thực nghiệm, không tin mỗi tài liệu.** Dựng hook nháp in JSON ra stdout, xem
   harness có tôn trọng không. Tài liệu có thể lệch với hành vi thật.

4. **Chốt cơ chế** trong 4 phương án:

   | Phương án | Điều kiện dùng được | Đánh đổi |
   |---|---|---|
   | **A. Viết lại `tool_input`** | harness hỗ trợ | Giữ nguyên trải nghiệm `APPROVED:`. Gọn nhất. |
   | **B. Duyệt theo phiên** | luôn dùng được | Hook ghi dấu file đã duyệt (`.claude/.approved-<hash>`, TTL ngắn); lần sau cho qua **không cần tiền tố**. Cần dọn dấu, cần nghĩ về thời hạn. |
   | **C. Bỏ hẳn tiền tố** | luôn dùng được | Thông báo chặn hướng dẫn người dùng tự chạy lệnh. Trung thực nhất, bất tiện nhất. |
   | **D. Tắt hẳn hook** | luôn dùng được | **Một dòng config**, không sửa code. Nhưng **mất rào chắn chống lộ secret** — đây là đánh đổi thật, không phải lối tắt. |

   Nếu B: **phải** chốt thời hạn dấu duyệt và phạm vi (một file? một phiên?) ngay ở phase này.

   **Về phương án D** (thêm sau validate 11-08-26 — bị bỏ sót ở bản đầu):
   `privacy-block.cjs:36` gọi `isHookEnabled('privacy-block')`; `vc-config-utils.cjs:902-907`
   cho biết chỉ cần đặt `hooks."privacy-block": false` trong config ck là hook tắt hẳn. Ghi ở
   đây để quyết định dựa trên **danh sách đầy đủ**, không phải vì thiếu thông tin.

   Cân nhắc trước khi chọn D: hook này **chặn đúng** — chỉ nhánh *duyệt* hỏng. Tắt đi là bỏ
   luôn phần đang chạy tốt. Ngược lại, một rào chắn không bao giờ mở được thì trên thực tế
   người dùng sẽ tự tắt — nên D vẫn là lựa chọn hợp lệ, chỉ cần chọn có ý thức.

5. **Ghi báo cáo** `reports/mechanism-survey.md`: ma trận tái hiện, khả năng harness (kèm phiên
   bản), phương án chọn, phương án loại + lý do.

## Success Criteria

- [ ] Ma trận 6 ca có kết quả thật cho **mọi ô**, không ô nào bỏ trống
- [ ] Trả lời rõ: hook **có / không** viết lại được `tool_input`, kèm bằng chứng thực nghiệm
- [ ] Phiên bản Claude Code đã ghi (mặc định `2.1.226`; xác nhận lại nếu đã đổi)
- [ ] Chốt một trong **4** phương án, ghi lý do loại ba phương án kia (kể cả D)
- [ ] Nếu chọn B: thời hạn + phạm vi dấu duyệt đã chốt
- [ ] Nếu chọn D: ghi rõ đây là quyết định chấp nhận mất rào chắn, không phải lối tắt
- [ ] Không sửa dòng code sản phẩm nào trong phase này

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Tài liệu nói một đằng, harness làm một nẻo | **Cao** | Bước 3 bắt buộc kiểm thực nghiệm, không chỉ đọc tài liệu |
| Khả năng viết lại `tool_input` thay đổi theo phiên bản → sửa xong bản sau lại hỏng | Trung bình | Ghi phiên bản đã kiểm vào báo cáo **và** vào comment trong hook |
| Phương án B (dấu duyệt) mở ra kẽ hở bảo mật mới | Trung bình | Thời hạn ngắn, phạm vi hẹp theo từng file, dấu nằm trong `.claude/` và phải `.gitignore` |
| Sa vào sửa luôn thay vì khảo sát | Trung bình | Tiêu chí hoàn thành ghi rõ: **không sửa code sản phẩm** ở phase này |
