---
phase: 2
title: "Fix and add tests"
status: pending
priority: P2
effort: "M"
dependencies: [1]
---

# Phase 2: Fix and add tests

## Overview

Áp dụng cơ chế đã chốt ở Phase 1, sửa cả hai khiếm khuyết, và thêm bộ test — hook này hiện
**không có test nào**.

> **Không bắt đầu phase này** khi `reports/mechanism-survey.md` chưa tồn tại và chưa chốt
> phương án. Nội dung dưới đây viết theo **phương án A** (harness cho viết lại `tool_input`);
> nếu Phase 1 chốt B hoặc C, các bước sẽ khác — cập nhật file này trước khi code.

## Requirements

**Chức năng**
- Duyệt xong → công cụ đọc được file ở **lần thử lại đầu tiên**.
- Đúng cho `Read`, `Bash`, `Grep`, `Write`, `Edit`; cả đường dẫn tương đối lẫn tuyệt đối.
- Không có vòng lặp tiền tố kép.

**Bảo mật (không thương lượng)**
- Không duyệt → vẫn chặn.
- Nhận diện tiền tố mơ hồ → **chặn** (fail-closed).
- Không nới định nghĩa file nhạy cảm.
- Giữ cảnh báo `Approved path is outside project`.

## ⚠️ Chưa có hạ tầng test — phát hiện khi validate 11-08-26

Bản đầu của phase này viết "tạo `.claude/hooks/tests/privacy-block.test.cjs`" như thể chỉ thêm
một file. **Sai.** Kiểm thật:

```
ls .claude/hooks/tests/   →  No such file or directory
```

Và tìm khắp repo: **không có test cho bất kỳ hook nào**, không test runner, không script `test`.

Nên bước này là **dựng quy ước test cho hook từ số không**, không phải thêm file. Đã chốt ở
validate: **dựng quy ước tối thiểu** — vì đây là rào chắn bảo mật, sửa mà không có lưới chắn
hồi quy là liều.

**Quy ước chốt:**

- Thư mục: `.claude/hooks/tests/`
- Framework: **`node:test` có sẵn trong Node** — không thêm dependency nào
- Chạy: `node --test .claude/hooks/tests/`
- Đặt tên: `<hook-name>.test.cjs`
- Tận dụng phần export sẵn có của hook (`privacy-block.cjs:159-168` đã export
  `hasApprovalPrefix`, `stripApprovalPrefix`, `isPrivacySensitive`, `extractPaths`… — chính là
  bề mặt cần test)

Quy ước này áp dụng cho mọi hook về sau. Giữ **tối thiểu**: không dựng CI, không coverage,
không helper chung — chỉ đủ để test hook này. Hook khác sẽ tự theo khi cần.

## Related Code Files

- Modify: `.claude/hooks/lib/privacy-checker.cjs` — nhận diện tiền tố (B2)
- Modify: `.claude/hooks/privacy-block.cjs` — nhánh duyệt phát output (B1), dòng 117-131
- Create: `.claude/hooks/tests/` — **thư mục mới**, chưa tồn tại
- Create: `.claude/hooks/tests/privacy-block.test.cjs` — test đầu tiên cho hook **bất kỳ** trong repo
- Read-only: `reports/mechanism-survey.md` (đầu ra Phase 1)

## Implementation Steps

1. **Sửa B2 — nhận diện tiền tố chịu được phân giải đường dẫn**

   Vấn đề: harness biến `APPROVED:d:\x\.env` thành `D:\cwd\APPROVED:d:\x\.env`, nên
   `startsWith('APPROVED:')` trả false.

   ```js
   // Harness có thể phân giải đường dẫn tương đối TRƯỚC khi hook chạy, khiến tiền tố
   // APPROVED: không còn ở đầu chuỗi. Nhận diện ở bất kỳ ranh giới đoạn đường dẫn nào,
   // rồi lấy phần còn lại làm đường dẫn thật.
   const APPROVED_RE = /(?:^|[\\/])APPROVED:(.*)$/;
   ```

   - `hasApprovalPrefix` dùng regex thay `startsWith`.
   - `stripApprovalPrefix` trả về nhóm bắt được.
   - **Nhiều tiền tố** (`APPROVED:...APPROVED:...`) → coi là mơ hồ → **chặn**, ghi log.
   - Nhánh Bash (`privacy-checker.cjs:136`) dùng cùng regex, không viết logic thứ hai.

2. **Sửa B1 — phát output cho harness ở nhánh duyệt**

   Theo cú pháp chốt ở Phase 1. Hình dạng dự kiến với phương án A:

   ```js
   if (result.approved) {
     // Hook PreToolUse chỉ cho qua/chặn được — không đủ. Phải trả tool_input đã bóc
     // tiền tố để harness ghi đè, nếu không công cụ vẫn nhận "APPROVED:<path>" và fail.
     process.stdout.write(JSON.stringify({ /* theo mechanism-survey.md */ }));
     process.exit(0);
   }
   ```

   Với `Bash`, phải bóc tiền tố **trong chuỗi lệnh**, không phải trong một trường đường dẫn.

3. **Ghi phiên bản đã kiểm** vào comment đầu `privacy-block.cjs`:

   ```js
   // Cơ chế viết lại tool_input đã kiểm trên Claude Code <version> (<ngày>).
   // Nếu duyệt xong mà công cụ vẫn nhận "APPROVED:", nghi hợp đồng harness đã đổi —
   // xem plans/260811-1632-privacy-hook-approval-bypass/reports/mechanism-survey.md
   ```

4. **Dựng quy ước test rồi viết test** — `mkdir .claude/hooks/tests/`, viết
   `privacy-block.test.cjs` bằng `node:test` (`const { test } = require('node:test')`),
   nạp hook bằng `require` (nó đã export sẵn ở dòng 159-168):

   *Nhận diện tiền tố*
   - tương đối: `APPROVED:.env` → nhận, bóc thành `.env`
   - tuyệt đối đã phân giải: `D:\cwd\APPROVED:d:\x\.env` → nhận, bóc thành `d:\x\.env`
   - dấu gạch xuôi: `/home/u/APPROVED:/etc/x.env` → nhận
   - **tiền tố kép** → **chặn** (fail-closed)
   - không tiền tố: `.env` → chặn

   *Không hồi quy bảo mật*
   - `.env` không tiền tố vẫn bị chặn
   - file trong allowlist vẫn qua, không cần tiền tố
   - đường dẫn ngoài dự án vẫn kích hoạt cảnh báo suspicious

   *Bash*
   - `grep x APPROVED:.env` → duyệt **và** lệnh phát ra không còn `APPROVED:`
   - `grep x .env` → chặn

5. **Kiểm end-to-end thật** — chạy đúng hai lệnh đã hỏng ở phiên 11-08-26:

   ```bash
   grep "^DATABASE_URL=" .env          # → chặn, hiện lời mời duyệt
   # sau khi duyệt: chạy lại theo đúng hướng dẫn hook đưa ra → PHẢI ra kết quả
   ```

   Test đơn vị không chứng minh được hợp đồng với harness. Bước này bắt buộc.

## Success Criteria

- [ ] Chạy lại đúng 2 ca hỏng của phiên 11-08-26 → **đọc được file ở lần thử đầu**
- [ ] Đường dẫn tuyệt đối không còn sinh gợi ý tiền tố kép
- [ ] `Bash` bóc được tiền tố khỏi chuỗi lệnh
- [ ] Tiền tố kép/mơ hồ → chặn (có test)
- [ ] File nhạy cảm không tiền tố vẫn bị chặn (có test)
- [ ] File allowlist vẫn qua (có test)
- [ ] `.claude/hooks/tests/` tồn tại, `node --test` chạy xanh — repo từ **0 test hook** lên có test
- [ ] Không thêm dependency nào (dùng `node:test` sẵn có)
- [ ] Phiên bản Claude Code đã kiểm được ghi trong comment hook

## Test Gate

```bash
cd d:/cong_viec/22-22/get-beam
node --test .claude/hooks/tests/
# rồi kiểm tay end-to-end theo bước 5 — bắt buộc, không thay bằng test đơn vị
```

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sửa hỏng rào chắn → secret rò ra | **Cao** | Bộ test có nhánh "không hồi quy bảo mật" riêng. Fail-closed mọi ca mơ hồ. Không đụng danh sách file nhạy cảm. |
| Regex nhận diện quá rộng → file tên chứa `APPROVED:` bị coi là đã duyệt | Trung bình | Neo vào ranh giới đoạn đường dẫn (`^` hoặc `[\\/]`). Có test cho ca lạ. |
| Hợp đồng harness đổi ở bản sau → hỏng thầm lặng | Trung bình | Ghi phiên bản trong comment + trỏ tới báo cáo khảo sát. Không tự phát hiện được — chấp nhận. |
| Sửa xong lại phá luồng cho qua bình thường (file không nhạy cảm) | Trung bình | Test bao ca file thường; hook vẫn fail-open khi crash |
| Phase 1 chốt B, C hoặc **D** → mọi bước ở đây sai | **Cao** | Ghi rõ ở đầu file: cập nhật phase này trước khi code nếu phương án khác A. **Nếu Phase 1 chốt D (tắt hook) thì phase này KHÔNG chạy** — không còn gì để sửa. |
| Dựng quy ước test bị phình thành "hạ tầng test cho mọi hook" | Trung bình | Chốt ở validate: **tối thiểu**. Không CI, không coverage, không helper chung. Chỉ đủ cho hook này; hook khác tự theo khi cần. |
