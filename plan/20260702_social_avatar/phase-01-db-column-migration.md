# Phase 01 — DB: thêm cột `avatar_url` + migration

**Mục tiêu:** Có 1 cột mới `avatar_url` trong bảng `enrichment_profiles`, và migration deploy sạch (chỉ 1 head).

---

## Bước 1.1 — Thêm cột vào model

**File:** `apps/api/models/enrichment.py`
**Vị trí:** trong khối "Twitter details" (sau dòng 52, gần `twitter_recent_topics`) — hoặc ngay dưới "Social" block (sau dòng 34). Đặt gần Twitter cho hợp ngữ cảnh.

**Thêm:**
```python
    # Ảnh đại diện mạng xã hội (Twitter/X ưu tiên, OSINT dự phòng).
    # Chỉ để hiển thị; KHÔNG dùng làm khoá tra cứu, KHÔNG tính vào completeness.
    avatar_url: Mapped[str | None] = mapped_column(String(500))
```

**Vì sao `String(500)`:** khớp style các cột URL khác trong file (`linkedin_url`, `facebook_url`, `personal_website` đều `String(500)`). URL ảnh Twitter/OSINT ngắn, thừa sức.

> Lưu ý style: file này dùng `Mapped[str | None] = mapped_column(...)` (không dùng `Optional[...]` cho các cột String) → theo đúng convention đó.

---

## Bước 1.2 — Xử lý multi-head (BẮT BUỘC làm trước khi tạo migration mới)

**Chạy trước:**
```bash
cd apps/api && alembic heads
```

**Nếu thấy > 1 head** (lúc viết plan có 4: `c9d2f7b4e1a6`, `d5a2b7c1e9f3`, `e7b4c2f9a1d8`, `f1a9c4d7e2b8`):

Tạo migration **merge** gộp hết head lại:
```bash
cd apps/api && alembic merge -m "merge heads before avatar_url" <head1> <head2> <head3> <head4>
```
(thay đúng các head mà `alembic heads` in ra tại thời điểm đó.)

→ Việc này tạo 1 file merge mới; sau đó chỉ còn **1 head**.

**Nếu chỉ có 1 head** (execute xác nhận 3 cái kia đã stamped ở prod): bỏ qua merge, nối thẳng vào head đó.

---

## Bước 1.3 — Tạo migration thêm cột

**File mới:** `apps/api/migrations/versions/<rev>_add_avatar_url.py`
(tạo bằng `alembic revision -m "add avatar_url to enrichment_profiles"`, KHÔNG dùng autogenerate để tránh nó bắt luôn các thay đổi lạ khác.)

**Nội dung (mẫu — theo đúng style file `c9d2f7b4e1a6_add_consent_mode.py`):**
```python
"""add avatar_url to enrichment_profiles

Revision ID: <auto>
Revises: <head sau khi merge>
Create Date: 2026-07-02

Adds a nullable social avatar URL (Twitter/X primary, OSINT secondary).
Display-only; nullable so existing rows are untouched (no backfill).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "<auto>"
down_revision: Union[str, None] = "<head sau khi merge>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "enrichment_profiles",
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_profiles", "avatar_url")
```

**Quan trọng:**
- `nullable=True` → dòng cũ không bị lỗi, không cần server_default.
- `down_revision` phải là **head thật sau merge**. KHÔNG copy giá trị trong plan; lấy từ `alembic heads`/output của lệnh merge.

---

## Nghiệm thu phase-01
```bash
cd apps/api
alembic heads          # → CHỈ 1 head
alembic upgrade head   # chạy OK, không "Multiple head revisions"
# kiểm tra cột tồn tại (psql local docker):
#   \d enrichment_profiles  → thấy avatar_url | character varying(500)
alembic downgrade -1   # bỏ cột OK
alembic upgrade head   # lên lại OK
```
Nhớ chạy trên **docker-compose DB local**, không phải prod Supabase (memory: local-dev-prod-wiring).
