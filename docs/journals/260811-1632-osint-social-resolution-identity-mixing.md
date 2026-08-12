---
title: Pipeline social-resolution tự xoá kết quả đúng của chính nó
date: 2026-08-11 16:32
severity: high
component: osint_scanner, social_resolver, social_rules, privacy-block hook
status: planned — plan đã validate, chưa code
---

## Context

Câu hỏi ban đầu rất nhẹ: đánh giá [Hippie-OSINT-Toolkit](https://github.com/hippiiee/Hippie-OSINT-Toolkit)
xem có áp dụng được vào Beam không. Người dùng thấy công cụ đó suy ra link mạng xã hội từ username
"khá là đúng".

Kết luận về HOT ra nhanh và nhàm: Beam đã mạnh hơn (Maigret 3000 site vs WhatsMyName 708). Chỉ có
**một** ý tưởng đáng lấy — cách xác nhận hit bằng đọc nội dung trang thay vì tin mã trạng thái HTTP.

Rồi bật `enable_osint_scan` chạy thử trên local, và buổi làm đổi hướng hoàn toàn.

## What happened

### Đo trên giấy trước

Username giả `zzqx7v3mklophantom9418` chạy qua 16 template của `social_rules.py`:
**6/16 báo nhầm** (Instagram, Pinterest, Reddit, Telegram, TikTok, Twitch đều trả 200 cho người
không tồn tại). Logic `e_string`/`m_string` của WhatsMyName loại đúng **6/6**, vẫn tìm ra
**5/6** người thật (ca trượt là Reddit 403 chặn bot, không phải lỗi logic).

### Rồi chạy thật

Seed `nhantochi95@gmail.com` vào visitor `4719d9fe…` site `beamlab` trên DB local, gọi thẳng
`resolve_social`. Kết quả:

```
0    profile "confirmed"
28   profile "likely"  (mức ĐƯỢC hiển thị)
392  "guess"          (ẩn)
```

Người dùng nhìn giao diện, thấy **"GitHub · nhantochi95"** và xác nhận *"cái này đúng"*.

Nhưng trong dữ liệu, link của đúng dòng đó là `github.com/**nhanto**` — **người khác**.

### Phát hiện chính

`_dedupe()` gộp theo **tên site**. Nên:

| | |
|---|---|
| Maigret tìm | `github.com/nhanto` — tài khoản có thật, người khác |
| Nhánh đoán link tìm | `github.com/nhantochi95` — **đúng người** |
| Sau khi gộp | link của người kia + username của người này |

Kiểm HTTP: **cả hai URL đều trả 200**. Hai người thật, bị nhập làm một.

**28/28 dòng hiển thị** có username lệch URL. Lọc lại toàn bộ 420 dòng: **10 dòng** có liên quan
`nhantochi95`, chỉ **1** sống sót nguyên vẹn (`dev.to/nhantochi95` — vì Maigret không tạo dòng
cạnh tranh cho Dev.to).

> Pipeline đã tìm đúng trên 10 site, rồi tự xoá 9.

### Phát hiện thứ hai — lỗi suy luận

`_classify()` nâng lên `"likely"` khi *email có đăng ký trên site đó*. Email test đăng ký ở
**90 site** → mọi phỏng đoán username trên 90 site đó thành "likely" → hiển thị. Suy luận sai:
"bạn có Spotify" + "có ai đó tên nhanto trên Spotify" không dẫn tới "nhanto trên Spotify là bạn".

### Phát hiện thứ ba — comment bị dữ liệu phản bác

`social_rules.py:108-109` viết:

> *"NAME-derived candidates come before the email local-part — a person's handle rarely matches
> their email prefix (the root cause of the wrong-person bug)."*

Dữ liệu thật cho kết quả ngược:

| Nguồn ứng viên | Kết quả |
|---|---|
| Từ họ tên → `nhanto`, `tonhan` | toàn người khác |
| Từ email → `nhantochi95` | **đúng** |

Ai đó đã kết luận ngược và đảo thứ tự ưu tiên. **n = 1, chưa đủ để lật lại** — nhưng đủ để nghi
ngờ và ghi vào plan như một phép đo cần làm, không phải một bản sửa.

## Findings

Ngoài 3 lỗi chính, buổi làm lộ thêm mấy thứ:

- **`MOCK_EXTERNAL_APIS` không bảo vệ đường ống OSINT.** Cả 5 file (`osint_scanner`,
  `social_rules`, `maigret_engine`, `social_resolver`, `paid_osint`) đều **0 lần** đọc cờ này.
  Bật mock vẫn bắn hàng trăm request thật từ IP máy dev. Cố ý (quét thật thì phải gọi thật),
  nhưng dễ hiểu lầm là an toàn.
- **Bộ lọc NSFW sẽ thủng khi cắm dữ liệu WhatsMyName.** `osint_scanner.py:165` so khớp **chính
  xác** với `{adult, nsfw, porn}`; danh mục của WMN ghi là `xx NSFW xx` → không khớp → **39 site
  người lớn lọt**.
- **Giao diện chờ 120s, đường ống có thể chạy ~165s.** Đo được: hai chặng username **67 giây**,
  Gemini ~16 giây, quét email ≤45 giây. Sát ngưỡng → lúc kịp lúc không, kiểu lỗi khó chịu nhất.
- **`socid_extractor` đã có sẵn trong `.venv`** (dep gián tiếp của maigret) nhưng nhánh đoán link
  chưa dùng. Không cần cài gì thêm.
- **WhatsMyName bổ sung 465 site Maigret top-500 không có** (trùng chỉ 215/708). Không chỉ chính
  xác hơn — còn rộng hơn ở phần đuôi.
- **Hook `privacy-block.cjs` hỏng.** Cơ chế `APPROVED:` chỉ dùng nội bộ để hook tự quyết; hook
  exit 0 mà **không viết lại `tool_input`**, nên công cụ vẫn nhận đường dẫn có tiền tố và fail.
  Có plan riêng.

## Reflection

Ba lần tôi đưa ra con số, ba lần con số sau bác con số trước:

| Cách đo | Tỉ lệ sai |
|---|---|
| Suy luận từ đọc code | "noisy, không rõ bao nhiêu" |
| Đo bằng username giả trên 16 site | 43% |
| **Chạy thật, người thật xác nhận** | **100%** |

Bài học không phải "đọc code là vô ích" — đọc code tìm ra đúng chỗ để đo. Bài học là **đừng dừng
ở con số đầu tiên nghe hợp lý**. 43% nghe đã đủ tệ để hành động; nếu dừng ở đó tôi đã đi sửa
**đúng lỗi ít quan trọng nhất trong ba lỗi** (kiểm bằng mã trạng thái), và bỏ sót cả hai lỗi
nặng hơn — vốn chỉ lộ ra khi có dữ liệu thật của người thật.

Chi tiết cũng đáng ghi: lỗi lộ ra vì người dùng nói *"GitHub này thì đúng"*. Chính lời xác nhận
đó là bằng chứng của lỗi — giao diện hiện **tên đúng** dẫn tới **link sai**, nên ngay cả người
biết rõ tài khoản của mình cũng bị đánh lừa. Không phép đo tự động nào bắt được kiểu này.

Và một điều nữa: khi validate plan, tôi tự chất vấn một rủi ro do chính mình viết ("phương án B
có thể không bao giờ kích hoạt") rồi đo lại — hoá ra sai, B kích hoạt trên 100% ca lỗi. Rủi ro
viết trong plan cũng chỉ là phỏng đoán cho đến khi đo.

## Artifacts

- Plan (đã validate, 0 failure): `plans/260811-1611-social-resolution-accuracy/`
- Plan sửa hook: `plans/260811-1632-privacy-hook-approval-bypass/`
- Dữ liệu test **còn giữ** trên DB local — Phase 4 cần: site `site_92e8f1f8a71c`,
  visitor `4719d9fe-3041-422e-b25f-6aa34a46b7f6`
- Script đo + kết quả thô: thư mục tạm phiên (`fp_probe.py`, `wmn_check.py`, `osint_result.json`)

## Unresolved questions

- Tỉ lệ 100% sai đo trên **1 người**. Cần bao nhiêu mẫu nữa mới kết luận được? Chưa định ngưỡng.
- Sau khi sửa, kết quả có gần như rỗng không? Nếu có thì tính năng này còn đáng giữ không —
  hay chỉ nên giữ nhánh Gemini (nhánh duy nhất hôm nay ra đúng `github.com/nhantochi95`)?
- Ai đã viết comment `social_rules.py:108-109` và dựa trên bằng chứng gì? Nếu họ có dữ liệu
  ngược lại thì n=1 của tôi không đủ để lật.
- `enable_osint_scan` vẫn tắt ở prod. Chưa chốt khi nào bật, kể cả sau khi sửa.
