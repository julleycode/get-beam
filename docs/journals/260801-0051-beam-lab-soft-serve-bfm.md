---
title: Beam Lab soft-serve pivot — canary, edge marker _bfm, browse limits
date: 2026-08-01 00:51
severity: high
component: beam-lab (Cloudflare edge), agent detection, link marker attribution
status: ongoing — soft-serve live, migrations chưa apply prod
---

## Context

Tiếp nối `260730-1126-ai-detection-live-validation.md`. Hôm đó câu hỏi là "Beam detect được AI + ai đứng sau AI không". Phiên này chuyển trọng tâm sang **beamlab** (`infra/cloudflare/beam-lab/`): làm sao vừa detect AI agent server-side, vừa **không chặn cứng** khiến agent bỏ cuộc, đồng thời nối được fetch (server thấy) với click (người dùng thật follow link) qua một marker riêng cho tầng edge.

## What happened

**1. Soft-serve thay hard 403.** Gate cũ trả 403 cứng khi nghi ngờ agent — kết quả đo được chỉ là "agent bỏ cuộc", không phải hành vi thật. Đổi sang soft-serve: luôn trả nội dung, kèm stealth HTML invitation, để ChatGPT-User đọc được trang live thay vì bounce.

**2. Canary `FUCHSIA-0731`** cắm trên homepage — dùng để phân biệt câu trả lời AI có phải đang đọc bản live hay đang trả lời từ cache/training data cũ.

**3. Link-hop: có lúc ăn, có lúc không.** Path non-guessable, hop tự nhiên (không ép), query param được giữ qua chain (`?ref=`, `?src=`, `?_bfm=`) — nhưng ChatGPT deep-hop fail nhiều hơn số lần thành công.

**4. Marker edge mới: `_bfm` (12-hex)** — stamp vào link same-host **on-demand** khi UA là agent; người dùng thường và index bot không bị stamp. Tách bạch rõ với `_bam` (Fernet token, mint ở tầng API, trỏ `agent_fetch_events.id`). Hai marker khác tầng, khác mục đích, khác cột DB — không được lẫn.

**5. Migrations chạy trên dev Postgres**: thêm `link_marker` vào `agent_fetch_events` + `events`, index cho join. **Chưa apply lên prod API** — đây là nợ kỹ thuật đang treo, ghi rõ trong Next steps.

**6. Pixel gắn thêm** vào các trang sâu: `/tac-nhan/`, `/kiem-chung/*` (anthropic, openai, perplexity, khac) — mở rộng bề mặt đo ngoài trang chủ.

**7. Ba câu hỏi identity, kết quả không đều:**
   - Which AI? → **Yes**, khi có fetch thì phân loại được.
   - Click ↔ fetch qua `_bfm`? → **Yes về cơ chế**, chưa có proof-run join thật với người bấm.
   - Who — cá nhân nào đứng sau? → **No**, vẫn ngoài tầm của session này (đúng như kết luận 30/07: company-level, không phải named individual).

**8. IP không dùng được làm session key** — Azure ASN 8075 rotate liên tục, không ổn định để làm định danh phiên.

**9. ChatGPT browse thật: chập chờn.** Home + canary OK phần lớn; deep hop fail thường xuyên. Khi fetch bị skip, model tự bịa: nói trang "JS-rendered" (sai — site là static HTML) hoặc gọi nhầm host `amlab.vn`. Ngược lại, khi được paste path trực tiếp, model đọc token chính xác 13/13 — nghĩa là bài toán không nằm ở parsing, mà ở việc **có fetch hay không** và model **không thừa nhận khi nó không fetch**.

**10. Gemini fetch dùng UA `got`** trên dải AWS ASN — hiện chưa được engine phân loại là AI, là gap cần theo dõi.

**11. Schema.org `@graph` được polish**; thử nghiệm `TechArticle` type bị rollback (không phù hợp).

**12. Operational gotcha:** `wrangler tail` chỉ bắt log đúng khi trỏ **full deployment UUID** (vd `9a4d1f20-6bdd-46fc-bfc5-447c83e81cab`), không phải alias — và tail hay chết giữa chừng, phải restart thủ công nhiều lần trong phiên.

## Reflection

Hard 403 chỉ đo được "agent bỏ cuộc" — một con số vô nghĩa vì nó không phản ánh hành vi thật của AI khi gặp nội dung. Soft-serve đúng hướng: phục hồi được khả năng agent đọc trang, nhưng đổi lại **mất khả năng ép hop** và **mất khả năng bắt agent thừa nhận khi nó không fetch**. ChatGPT có xu hướng bịa lý do (site "JS-rendered", sai host) thay vì nói "tôi không mở được link" — đây là giới hạn của chính model, không phải bug ở phía beamlab.

Kết luận thực dụng: "which AI" là tín hiệu vững khi có fetch xảy ra. "Follow deep link của chúng ta" **không phải** bề mặt sản phẩm đáng tin cậy để build trên ChatGPT hiện tại — nên coi là lab finding, không phải guarantee, và đừng đổ thêm effort vào prompt-engineering để ép tỷ lệ hop lên.

## Decisions

- **Soft-serve thay hard gate — chốt.** Không quay lại 403 cứng cho detection lab.
- **`_bfm` tách biệt hoàn toàn với `_bam`** — khác tầng (edge vs API), khác encoding (12-hex vs Fernet), khác cột DB. Không gộp logic hai marker.
- **Canary tiếp tục là tín hiệu ops** để phân biệt live vs stale answer, không đổi cơ chế.
- **Chấp nhận browse intermittency là lab finding** — không overfit prompt engineering để "ép" ChatGPT hop ổn định hơn; đó không phải bài toán có thể giải quyết từ phía server một cách đáng tin cậy.
- Nhiều file lab + API vẫn **chưa commit** — theo yêu cầu lặp lại của user trong phiên (skip commit), giữ nguyên trạng thái uncommitted.

## Next steps

1. Retest link-hop với natural prompt (không ép cấu trúc) — hoặc đóng lại như một known limitation nếu vẫn không cải thiện.
2. Chạy proof thật: người dùng bấm link có `_bfm` → verify join `agent_fetch_events` ↔ `events` trên DB.
3. (Optional) Phân loại thêm các fetcher dạng `got`/AWS-like (Gemini) — hiện đang lọt lưới classification.
4. **Apply migrations `link_marker` lên prod API** — hiện mới chỉ chạy trên dev Postgres, đây là việc ưu tiên trước khi coi tính năng là "live" thật sự.
5. Mở rộng on-demand marker cho Perplexity/Claude; thêm TTL cho `_bfm`; tắt `BEAM_FULL_LOG` sau khi ổn định.
6. Khi rảnh, chạy UPDATE PROCESS để đối chiếu lại status của `agent-gate-lab_31-07-26` và `agent-gate-soft-serve_31-07-26` — plan vẫn ghi "awaiting-execute-approval" dù lab đã chạy live, cần đồng bộ lại.

**Status:** Soft-serve + canary + `_bfm` đã sống trên beamlab; join click↔fetch mới đúng ở tầng cơ chế, chưa có proof-run thật; migrations còn treo ở dev.
