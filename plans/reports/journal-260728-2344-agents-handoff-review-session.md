# Journal — Phiên review tab Agents/Visitors

Ngày: 2026-07-28 · Branch: `dev_nhantc2`

## Chuyện gì đã xảy ra

Bắt đầu bằng một câu hỏi tìm skill để đánh giá codebase. Kết thúc bằng một bug thật được sửa, và ba giả thuyết của chính tôi bị bác bỏ bằng số liệu.

## Ba lần tôi đoán sai

Đáng ghi lại, vì cả ba đều "nghe rất hợp lý" trước khi đo.

**Lần 1 — timezone.** Tôi phát hiện `Event.created_at` là naive còn `agent_fetch_events.created_at` là aware, kết luận đây là lỗi HIGH đang âm thầm làm hỏng correlation trên prod. Xếp nó lên đầu danh sách. Đo thật: `SHOW timezone` = UTC, skew = 0. Sai hoàn toàn.

Tệ hơn: tôi còn thiết kế một query "chứng minh" lệch múi giờ bằng cách so `max(created_at)` của hai bảng khác nhau — hai bảng có nhịp ghi hoàn toàn khác nhau. Nó cho ra 2h37m và suýt nữa thì được đọc thành bằng chứng. Không phải bằng chứng gì cả. Nếu user không đưa số liệu đầy đủ, tôi đã dẫn cả hai đi sửa một chỗ không hỏng.

**Lần 2 — `Event` thiếu cột `referrer`.** Giả thuyết đẹp: nếu thiếu cột thì `getattr(ev, "referrer", None)` luôn trả None và correlation luôn rỗng — giải thích gọn ghẽ mọi thứ. Mở file ra: cột nằm ngay dòng 24.

**Lần 3 — sweep không chạy.** Nghi APScheduler không bao giờ bắn do restart. Job đăng ký vô điều kiện, 10 phút một lần, không flag chặn. Và tôi còn đề xuất một cách check sai nốt (grep log) — hàm return sớm không log gì khi rỗng, nên "không thấy log" chẳng chứng minh được gì.

## Cái tìm ra được lại đến từ chỗ khác

User nhìn dữ liệu và nhận xét: "tất cả 22 rows tier=on-demand, kể cả `oai-searchbot` — searchbot là indexer, đúng ra tier khác. Beacon H5 có vẻ hardcode tier."

Chẩn đoán sai chỗ — beacon gọi `classify_tier()` đúng, không hardcode gì. Nhưng **nhận xét gốc thì đúng**, và đó là bug thật: `_ON_DEMAND_TOKENS` xếp thẳng `oai-searchbot` + `claude-searchbot` vào on-demand. Tra doc vendor: cả hai là crawler index. 32% lượng "on-demand" trên prod là crawler.

Và code **vi phạm nguyên tắc do chính nó viết ra** ở ngay phía trên: *"Mislabeling a crawler as on-demand would fabricate a human-intent signal, so the safe default is index."* Rồi ngay dưới dòng đó làm đúng điều nó vừa cấm.

## Bài học đắt nhất

Không phải bug nào cả, mà là: **`0` không phân biệt được "chạy đúng" với "hỏng".**

Dashboard hiện `Human handoffs detected: 0`. Để biết con số đó nghĩa là gì, phải mất 3 vòng hỏi đáp, 2 lần chạy SQL tay lên production, và ba giả thuyết sai. Với 22 fetch và 1 click AI, một hệ thống hoàn hảo cũng ra `0`, một hệ thống hỏng hoàn toàn cũng ra `0`.

Đó là lý do P0-2 (đưa `processed`/`linked` ra ngoài, tách high/medium trên UI) đáng giá hơn nhiều bug nhỏ cộng lại.

## Điều làm đúng

Không sửa timezone dù user đã bảo "cứ fix vụ UTC+7 đi". Số liệu nói không hỏng, nên nói lại là không hỏng. Nếu chiều theo, sẽ đổi code đang chạy đúng trên đường có traffic thật, và bug thật vẫn nằm nguyên đó.

Và: stash thay đổi của mình để chứng minh 3 test enrichment fail là có sẵn, thay vì chỉ nói "chắc không liên quan".

## Còn dở

Hơn chục file trong vùng agents chưa đọc dòng nào — trong đó có `agent_verification.py`, đúng lõi của việc phân biệt AI thật với AI giả mạo. Review này hẹp hơn vẻ ngoài của nó nhiều.
