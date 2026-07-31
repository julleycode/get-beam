---
name: plan:evallayer-marker-offer-description-and-commercial-site-measurement-note
description: "Backlog: AgentOffer has no free-text description field (50-char billing_period doubles as one), and the two remaining marker questions (does an AI find the feed unprompted, does it keep the marker when citing naturally) cannot be measured on beamlab"
date: 31-07-26
metadata:
  node_type: memory
  type: plan
  feature: evallayer
  phase: post-marker-validation
---

# Marker follow-ups sau lần chạy end-to-end 31-07-26

**Bối cảnh:** ngày 31-07-26 chuỗi marker chạy thông lần đầu với ChatGPT thật —
`agent_handoff_links` ghi `method='marker'`, `confidence='high'`, 2 giây sau click, referrer rỗng.
Chi tiết trong `docs/agent-detection-architecture.md` mục 5b và 5c. Note này giữ hai việc còn lại
mà lần chạy đó phơi ra.

**Không chặn gì:** cơ chế marker đã hoạt động đúng. Hai mục dưới là mở rộng và đo lường, không
phải lỗi.

---

## 1. `AgentOffer` không có trường mô tả — MEDIUM

**Hiện trạng.** `apps/api/services/agent_gateway.py` `build_offers()` gán:

```python
description=raw.get("billing_period"),
billing_period=raw.get("billing_period"),
```

Một giá trị đổ vào hai trường của feed. Và `AgentOffer.billing_period` trong
`apps/api/schemas/agent_profile.py` giới hạn **50 ký tự**.

Nên toàn bộ phần tự do của một offer là: `name` (200 ký tự) + 50 ký tự dùng chung cho
mô tả lẫn chu kỳ thanh toán. Không viết nổi một offer thuyết phục trong khuôn đó.

**Vì sao đáng sửa.** Mục 5c kết luận: URL trong câu trả lời của AI được render thành link hay
thành `code` phụ thuộc VAI TRÒ của nó — dữ liệu trích từ document thì thành `code`, đường dẫn
được giới thiệu thì thành link. Đòn bẩy duy nhất nằm ở nội dung feed: một offer đọc như lời chào
hàng thì mới có cơ hội vào vai trò "link". 50 ký tự chính là trần của đòn bẩy đó.

**Việc cần làm.**

- Thêm `description: str | None` (đề xuất `max_length=500`) vào `AgentOffer`.
- `build_offers()` đọc `raw.get("description")`, giữ `billing_period` đúng nghĩa chu kỳ.
- Thêm ô nhập trong `apps/web/src/app/dashboard/agent/page.tsx` (khối Offers).
- Backward-compat: offer cũ không có `description` thì fallback về `billing_period` như hiện tại
  — dữ liệu đang nằm trong JSONB, không migration.

**Không làm:** đừng nới `billing_period` lên 500. Nó là chu kỳ thanh toán; nhồi mô tả vào đó
là lý do sinh ra vấn đề này.

---

## 2. Hai câu hỏi marker không đo được trên `beamlab` — MEDIUM, cần site thương mại thật

`beamlab.nhantown.com` đã chứng minh xong phần cơ chế. Nó **không** đo được hai câu còn lại:

| Câu hỏi | Vì sao beamlab không đo được |
|---|---|
| AI có **tự tìm ra** offers feed không? | Trang tự khai không phải trang bán hàng và chưa mở đăng ký (đúng sự thật). Không có câu hỏi người dùng nào tự nhiên dẫn AI đi tìm bảng giá ở đây. Đo 31-07: ChatGPT đọc `llms.txt` có link tuyệt đối tới offers rồi bỏ qua; chỉ fetch khi được đưa URL thẳng. |
| AI có **tự giữ** marker khi dẫn link tự nhiên không? | Lần đo 31-07 dùng prompt có câu "giữ nguyên URL đầy đủ" — mới chứng minh *có thể giữ*, chưa phải *tự giữ*. Muốn đo tự nhiên thì AI phải có lý do tự nhiên để dẫn link, tức phải có gì đó thật để bán. |

**Điều kiện đo.** Một site có pricing thật và đường đăng ký thật (ứng viên: `getbeam.fyi`), lặp
lại đúng ba bước đã làm cho beamlab:

1. Bật AgentProfile, offers trỏ URL **cùng host** với site (ràng buộc same-host của
   `stamp_marker`, xem mục 7 ràng buộc 2 trong `docs/agent-detection-architecture.md`).
2. Thêm `<link rel="alternate">` → `manifest.json` vào `<head>`, và dòng offers feed trong
   `llms.txt`.
3. Hỏi AI câu tự nhiên kiểu "X bán gì, giá bao nhiêu, đăng ký ở đâu" trong **chat mới** — chat cũ
   tái dùng nội dung đã fetch nên không duyệt lại, đây là bẫy đã dính một lần ngày 31-07.

**Phụ thuộc:** nên làm sau mục 1. Đo trên một feed vẫn bị bó trong 50 ký tự thì kết quả âm không
phân biệt được là do AI không quan tâm hay do feed quá nghèo nội dung.

---

## Ghi chú liên quan (không thuộc note này)

- Provider keys trống → `identified_visitors = 0`. Đã có trong `docs/agent-detection-architecture.md`
  mục 5. Lưu ý bổ sung 31-07: identity graph (RB2B/Leadpipe/Capturify) xây trên traffic B2B Mỹ, nên
  điền key xong vẫn nhiều khả năng không resolve được traffic IP nhà mạng Việt Nam — cần traffic
  B2B thật để đánh giá, không phải chỉ cần key.
- Rút ngắn marker: **đã loại**, không cần làm. Đối chứng 31-07 cho thấy URL ngắn và URL marker
  ~180 ký tự đều linkify; độ dài không phải nguyên nhân.
