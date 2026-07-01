# Phase 01 — Service đọc YouTube + Reddit (nền tảng)

**Trạng thái:** ⬜ chưa làm
**Rủi ro:** 🟢 thấp (thêm mới, không đụng luồng cũ)

## Mục tiêu
Tạo 1 service độc lập biết đọc nội dung công khai từ YouTube + Reddit. Chưa nối vào đâu — chỉ là "công cụ" để P2/P3/P4 gọi.

## Touchpoints
- **Mới:** `apps/api/services/content_reader.py`
- **Sửa:** `apps/api/requirements.txt` (thêm `yt-dlp`)
- **Sửa:** `apps/api/config.py` (thêm flag + rate-limit settings)
- **Mới (test):** `apps/api/tests/test_content_reader.py`

## Việc cụ thể
1. `requirements.txt`: thêm `yt-dlp` (Reddit dùng `httpx` đã có sẵn — không cần `praw`).
2. `config.py`: thêm
   - `enable_content_reader: bool = False` (feature-flag, default OFF)
   - `content_reader_max_items: int = 5` (số video/post lấy về)
   - tận dụng `mock_external_apis` sẵn có.
3. `content_reader.py`:
   - `async def fetch_youtube(channel_or_video_url: str) -> dict` — dùng `yt-dlp` (chạy trong threadpool vì yt-dlp đồng bộ) lấy: tiêu đề, mô tả ngắn, N video gần nhất (title + ngày). Không tải video, không tải phụ đề nặng ở P1.
   - `async def fetch_reddit(username_or_subreddit: str) -> dict` — `httpx.get("https://www.reddit.com/user/{u}/.json")` hoặc `/r/{sub}/.json` (User-Agent riêng, timeout 10s), lấy N post/comment gần nhất (title + snippet + ngày + score).
   - Mỗi hàm: cache Redis (key `content:yt:<hash>` / `content:rd:<hash>`, TTL 7 ngày, cả negative), rate-limit, `try/except` trả `{}` khi lỗi (non-fatal), `if settings.mock_external_apis: return <fake>`.
   - Log bằng `structlog`, không log nội dung thô.

## Blast radius
Zero với luồng hiện tại — không import ở đâu khác cho tới P2. Chỉ thêm 1 dependency (`yt-dlp`) vào Docker build.

## Verification
- `pytest apps/api/tests/test_content_reader.py` (mock mode + parse thật 1 URL công khai).
- Chạy tay: gọi `fetch_reddit("reddit")` + `fetch_youtube(<kênh công khai>)` → in ra JSON hợp lệ.
- `yt-dlp` cài được trong Docker (kiểm tra image build không lỗi).
- Không có secret/PII trong log.
