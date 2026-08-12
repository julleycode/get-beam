---
phase: 1
title: "Fix dedupe identity collision"
status: complete
priority: P1
effort: "S"
dependencies: []
---

<!-- Updated: Validation Session 1 - D6: Phase 1+2 là một đơn vị phát hành -->

# Phase 1: Fix dedupe identity collision

> **Đơn vị phát hành (D6):** phase này **không đứng một mình**. Phải vào cùng Phase 2 trước khi
> coi là hoàn tất. Sửa riêng Phase 1 sẽ làm số dòng "đoán mò" phình mạnh vì chưa có lớp lọc.

## Overview

`_dedupe()` gộp kết quả theo **tên site**. Với luồng quét email (caller gốc) điều đó đúng — mọi
dòng đều thuộc về một email duy nhất. Với luồng quét username (caller thêm sau) điều đó **sai** —
các dòng thuộc về **những username khác nhau**, tức những **người khác nhau**.

Hậu quả đo được: 9/10 kết quả đúng bị xoá, 28/28 dòng còn lại có username lệch URL.

## Requirements

**Chức năng**
- Hai profile trên cùng site với username **khác nhau** phải là **hai dòng riêng**.
- Hành vi của caller gốc (quét email) **không đổi**.
- Cột `source_engine` không được lặp nhãn.

**Phi chức năng**
- Không thêm phụ thuộc mới. Không đổi schema. Không đổi chữ ký hàm công khai theo cách phá caller.

## Bằng chứng

Chạy thật 11-08-26 (`osint_result.json`):

```
Dòng GitHub sau khi gộp:
  url            = https://github.com/nhanto        ← Maigret tìm, người khác
  extra.username = nhantochi95                      ← nhánh đoán link tìm, ĐÚNG
  source_engine  = maigret,rule-base,rule-base,rule-base,rule-base,rule-base,rule-base
```

Cả `github.com/nhanto` và `github.com/nhantochi95` đều trả HTTP 200 — **hai tài khoản có thật
của hai người khác nhau**.

9 site khác cùng kiểu: X, Instagram, Pinterest, TikTok, Telegram, Reddit, GitLab, Twitch.
Chỉ **Dev.to** sống sót nguyên vẹn (`dev.to/nhantochi95`) — vì Maigret không tạo dòng cạnh tranh.

## Architecture

### Vì sao KHÔNG đổi khoá gộp toàn cục (Quyết định D1)

`test_dedupe_collapses_same_site_prefers_profile` mô tả ý đồ gốc và **nó hợp lý**:

```python
OsintAccount("GitHub", ..., "registered", ..., "holehe",      {})              # email có đăng ký ở GitHub
OsintAccount("github", ..., "profile",    ..., "user-scanner", {"username":"jdoe"})  # và handle là jdoe
# → gộp thành 1: cùng một người, hai tín hiệu
```

Đổi khoá thành `(site, username)` toàn cục sẽ **phá đúng ca hợp lệ này** (`""` vs `"jdoe"` thành
hai khoá). Nên: **thêm tham số**, caller gốc giữ nguyên mặc định.

### Lỗi lặp `source_engine`

```python
engines = sorted({existing.source_engine, acc.source_engine})
```

Sau lần gộp đầu, `existing.source_engine` đã là `"maigret,rule-base"`. Lần sau tập hợp thành
`{"maigret,rule-base", "rule-base"}` → nối lại càng dài. Phải **tách theo dấu phẩy trước khi hợp**.

## Related Code Files

- Modify: `apps/api/services/osint_scanner.py` — `_dedupe()` (~dòng 373-398)
- Modify: `apps/api/services/social_resolver.py` — 2 chỗ gọi `_dedupe` (~dòng 224, 253)
- Modify: `tests/unit/test_osint_scanner.py` — thêm test, **giữ nguyên 2 test cũ**

## Implementation Steps

1. **Thêm tham số vào `_dedupe`**

   ```python
   def _dedupe(
       accounts: list[OsintAccount], *, by_username: bool = False
   ) -> list[OsintAccount]:
       """Gộp các dòng trùng.

       by_username=False (mặc định, luồng quét email): gộp theo site. Mọi dòng đều
       thuộc cùng một email nên gộp theo site là đúng.

       by_username=True (luồng quét username): gộp theo (site, username). Các dòng
       thuộc về những username khác nhau — tức những người khác nhau — nên gộp theo
       site sẽ trộn lẫn danh tính.
       """
   ```

   Dựng khoá:

   ```python
   site = (acc.site_name or "").strip().lower()
   if not site:
       continue
   key = (site, ((acc.extra or {}).get("username") or "").strip().lower()) if by_username else (site, "")
   ```

2. **Sửa nối `source_engine`** — tách theo dấu phẩy trước khi hợp:

   ```python
   def _merge_engines(a: str, b: str) -> str:
       parts = {p.strip() for s in (a, b) for p in (s or "").split(",") if p.strip()}
       return ",".join(sorted(parts))
   ```

   Dùng thay cho `sorted({existing.source_engine, acc.source_engine})`.

3. **Cập nhật 2 chỗ gọi trong `social_resolver.py`** → `_dedupe(..., by_username=True)`.

4. **Không đụng** chỗ gọi trong `run_osint_scan` (giữ mặc định).

5. **Thêm test** vào `tests/unit/test_osint_scanner.py`:
   - `test_dedupe_by_username_keeps_distinct_people` — cùng site, 2 username → 2 dòng
   - `test_dedupe_by_username_still_merges_same_username` — cùng site, cùng username, 2 engine → 1 dòng, engine hợp lại
   - `test_dedupe_default_unchanged_for_email_scan` — khẳng định lại hành vi mặc định
   - `test_merge_engines_no_duplicates` — gộp 3 lần liên tiếp không sinh nhãn lặp

6. **Thêm test hồi quy tái hiện đúng lỗi thật** vào `tests/unit/test_social_resolver.py`:
   - `test_two_github_usernames_not_merged` — dựng đúng ca `nhanto` + `nhantochi95`, khẳng định
     hai dòng riêng và mỗi dòng có username khớp URL của chính nó.

## Success Criteria

- [ ] `test_dedupe_collapses_same_site_prefers_profile` **vẫn xanh, không sửa**
- [ ] `test_dedupe_keeps_distinct_sites` **vẫn xanh, không sửa**
- [ ] Cùng site + username khác nhau → hai dòng riêng
- [ ] Cùng site + cùng username + engine khác nhau → một dòng, `source_engine` không lặp
- [ ] Test hồi quy `nhanto` / `nhantochi95` xanh
- [ ] `pytest tests/unit/test_osint_scanner.py tests/unit/test_social_resolver.py tests/unit/test_social_pipeline_helpers.py` toàn xanh

## Test Gate

```bash
cd d:/cong_viec/22-22/get-beam
.venv/Scripts/python.exe -m pytest tests/unit/test_osint_scanner.py \
  tests/unit/test_social_resolver.py tests/unit/test_social_pipeline_helpers.py -q
```

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Số dòng kết quả tăng vọt (mỗi username một dòng, có thể ×8) | **Cao** → **đã xử lý** | **D6 (validate 11-08-26): Phase 1 + Phase 2 là MỘT đơn vị phát hành.** Commit riêng cho dễ review, nhưng "xong" chỉ tính khi cả hai đã vào. Không bật cho người dùng ở trạng thái giữa chừng — khi đó `guesses` phình nhưng `guesses` không hiển thị nên không lộ ra ngoài. |
| Còn caller `_dedupe` nào khác chưa biết | Thấp | `grep -rn "_dedupe" apps/ tests/` trước khi sửa; xác nhận đúng 3 chỗ gọi |
| `_richness` chọn nhầm dòng thắng trong nhóm cùng username | Thấp | Không đổi `_richness` ở phase này; ghi nhận nếu test lộ vấn đề |
| Dòng không có username (PDL trả slug rỗng) rơi vào khoá `""` chung | Trung bình | Có test riêng cho ca username rỗng; xác nhận không gộp nhầm hai dòng rỗng khác URL |
