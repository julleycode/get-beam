---
phase: 4
title: "Detector Framework & Replay Harness"
status: pending
priority: P1
dependencies: [1]
effort: ""
---

# Phase 4: Detector Framework & Replay Harness

# Xử lý lỗ hổng G3

## Overview

Định nghĩa hợp đồng detector và cưỡng chế tính pure-function, rồi dựng replay harness để chạy lại
detector phiên bản mới trên toàn bộ evidence cũ. Đây là năng lực phân biệt lab research với
một bot-detector thông thường: sai cũng được, miễn tính lại được.

## Requirements

**Functional**
- Contract `detect(bundle) -> DetectorResult`, có version.
- Detector registry, mỗi detector có `name` + `version`.
- Bảng `detector_result` lưu kết quả kèm version detector đã sinh ra nó.
- CLI replay: chạy detector vN trên bundle theo khoảng thời gian, diff với kết quả đã lưu.
- Hai detector đầu tiên: UA identity classifier, request shape.

**Non-functional (INV-2, bắt buộc cưỡng chế bằng test)**
- Detector cấm gọi mạng, DNS, đọc file, đọc `datetime.now()`, đọc biến môi trường.

## Architecture

```python
@dataclass(frozen=True)
class DetectorResult:
    detector: str
    version: int
    status: str            # matched | no_match | insufficient_data
    score: float           # 0.0-1.0
    claims: dict           # provider, agent_name, purpose...
    evidence: list[str]    # chuỗi giải thích được, vd "ua_contains:ChatGPT-User"

class Detector(Protocol):
    name: str
    version: int
    min_schema_version: int   # bundle cũ hơn → insufficient_data, không crash, không đoán
    kind: str                 # per_request | windowed
    def detect(self, bundle: EvidenceBundle) -> DetectorResult: ...
```

### Hai lớp detector: per-request và windowed

`detect(bundle)` chỉ đủ cho detector nhìn **một** request. Detector cần chuỗi request
(`request_shape`) **không được chạy ở ingest**: tại thời điểm request đầu tiên chuỗi còn rỗng,
và kết quả phụ thuộc thời điểm chạy — phá vỡ replay và làm determinism test vô nghĩa.

- **per_request**: chạy ở ingest trên sealed bundle (`ua_identity`, `identity_verify`).
- **windowed**: chạy sau khi observation window đóng, do scoring (phase 6) hoặc replay gọi.
  Input là bundle + **sealed shape context**: `shape_window_seconds`, `sibling_request_ids`,
  `sibling_hash` (hash tập request cùng `test_run_id` trong window). Toàn bộ tham số và hash
  này lưu vào `detector_result.claims_json` và phản ánh trong `params_hash` — không lưu tham số
  = không tái lập được.

### Cưỡng chế pure-function

Không dựa vào kỷ luật con người. Ba lớp:

1. **IO guard test** — chạy mỗi detector trong context patch `socket.socket`, `socket.getaddrinfo`,
   `open`, `time.time`, `datetime.now`, `os.environ.get` để raise. Detector nào chạm vào là fail test.
2. **Determinism test** — chạy cùng bundle 2 lần cách nhau, khẳng định kết quả byte-identical.
3. **Code review rule** ghi trong `docs/code-standards.md`: detector chỉ import từ `beam_lab.detectors.*` và stdlib thuần tính toán.

Lớp 1 là lớp thật sự có tác dụng. Không có nó thì INV-2 sẽ bị vi phạm trong vòng một tháng.

### Schema

```sql
CREATE TABLE detector_result (
  id                TEXT PRIMARY KEY,
  request_id        TEXT NOT NULL REFERENCES evidence_bundle(request_id),
  detector          TEXT NOT NULL,
  detector_version  INTEGER NOT NULL,
  params_hash       TEXT NOT NULL DEFAULT '',  -- hash tham số ngoài bundle (vd shape window)
  status            TEXT NOT NULL,
  score             REAL NOT NULL,
  claims_json       TEXT NOT NULL,
  evidence_json     TEXT NOT NULL,
  computed_at       TEXT NOT NULL,
  is_replay         INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX idx_result_unique
  ON detector_result(request_id, detector, detector_version, params_hash);
```

`UNIQUE` cho phép giữ song song kết quả v1 và v2 (và cùng version với params khác nhau) trên cùng
request → diff được. Ghi kết quả dùng `INSERT ... ON CONFLICT DO UPDATE`: chạy lại cùng
detector+version+params trên cùng khoảng là idempotent, không crash unique index. Kết quả với
`params_hash` khác là hàng mới, không ghi đè.

### Replay

```bash
python -m beam_lab.replay run --detector ua_identity --version 2 --from 2026-07-01 --to 2026-07-28
python -m beam_lab.replay diff --detector ua_identity --a 1 --b 2
```

`diff` xuất bảng: bao nhiêu request đổi status, đổi theo hướng nào, mẫu ví dụ mỗi nhóm thay đổi.

## Related Code Files

- Create: `src/beam_lab/detectors/__init__.py` — registry
- Create: `src/beam_lab/detectors/base.py` — Protocol, DetectorResult
- Create: `src/beam_lab/detectors/ua_identity.py`
- Create: `src/beam_lab/detectors/request_shape.py`
- Create: `src/beam_lab/detectors/runner.py` — chạy toàn bộ detector đã đăng ký lên 1 bundle
- Create: `src/beam_lab/classification/projection.py` — projection dẫn xuất actor/provider/verification/request shape cho dashboard
- Create: `src/beam_lab/replay/__main__.py` — CLI
- Create: `src/beam_lab/replay/differ.py`
- Modify: `src/beam_lab/intake/middleware.py` — gọi runner sau khi bundle đã lưu
- Modify: `src/beam_lab/db/schema.sql`
- Create: `tests/test_detector_io_guard.py`
- Create: `tests/test_detector_determinism.py`
- Create: `tests/test_classification_projection.py`
- Create: `tests/test_replay_diff.py`
- Create: `docs/code-standards.md`

## Implementation Steps

1. `detectors/base.py`: `DetectorResult` frozen dataclass, `Detector` Protocol.
2. `detectors/__init__.py`: registry dict `{name: detector_instance}`, hàm `register()`.
3. `detectors/runner.py`: `run_all(bundle) -> list[DetectorResult]` — chỉ chạy detector `kind='per_request'` ở ingest, ghi vào `detector_result`. Detector lỗi → ghi `status='error'` cho riêng detector đó, không làm hỏng các detector khác và không hỏng ingest. Detector `windowed` do scoring/replay gọi, không qua runner ingest.
4. `detectors/ua_identity.py` v1: match UA với agent registry tĩnh tối thiểu (4 UA mẫu). Trả `claims={provider, agent_name, purpose}` + `evidence=["ua_contains:..."]`. **Chỉ đọc `bundle.user_agent`** — không verify IP, đó là việc của phase 5. Phase 5 **thay thế** nguồn registry tĩnh này bằng `registry_data.yaml` — không được để tồn tại 2 bảng UA pattern song song.
5. `detectors/request_shape.py` v1: detector **windowed** — không chạy ở ingest. Scoring/replay gom chuỗi request cùng `test_run_id` trong `shape_window_seconds` (mặc định 120s), tính `sibling_hash`, rồi gọi detector với sealed shape context → `html_only | full_browser_assets | robots_then_pages | unknown`. Detector chỉ đọc context được truyền, **không query DB**. Tham số window + hash ghi vào `claims_json` và `params_hash`.
6. `tests/test_detector_io_guard.py`: patch các API IO, loop toàn bộ registry, chạy với bundle mẫu, khẳng định không raise vì IO.
7. `tests/test_detector_determinism.py`: chạy 2 lần, so sánh kết quả serialize.
8. `replay/__main__.py`: `run` đọc bundle theo khoảng, chạy detector version chỉ định, ghi với `is_replay=1` và `ON CONFLICT DO UPDATE` — chạy lại cùng tham số là idempotent. Windowed detector yêu cầu truyền `--shape-window-seconds`, giá trị này phản ánh trong `params_hash`.
9. `replay/differ.py`: so 2 version, xuất bảng thay đổi + ví dụ.
10. `classification/projection.py`: dẫn xuất projection mới nhất cho mỗi request gồm
    `actor_class`, `provider`, `verification_status`, `request_shape`, `primary_request_id`.
    Đây là view/projection từ detector result, không phải policy engine hay bảng state thứ hai.
11. `docs/code-standards.md`: ghi INV-2 và luật import cho detector.

## Success Criteria

- [ ] IO guard test pass cho mọi detector trong registry; thêm detector gọi `socket` → test fail.
- [ ] Determinism test pass — cùng bundle cho cùng kết quả.
- [ ] Detector lỗi không làm hỏng ingest và không làm hỏng detector khác.
- [ ] Replay chạy detector v2 trên bundle cũ, lưu song song với v1, không ghi đè; chạy lại cùng version+params là idempotent.
- [ ] `request_shape` không chạy ở ingest; chạy sau window với sealed shape context; `claims_json` chứa `shape_window_seconds` + `sibling_hash`; replay cùng tham số cho kết quả byte-identical.
- [ ] `replay diff --a 1 --b 2` xuất được bảng thay đổi có ví dụ cụ thể.
- [ ] `ua_identity` nhận diện đúng ChatGPT-User, GPTBot, ClaudeBot, PerplexityBot từ UA mẫu.
- [ ] `request_shape` phân biệt được `html_only` và `full_browser_assets` từ dữ liệu control group.
- [ ] Dashboard/query layer đọc được projection `actor_class`, provider, verification status và request shape mà không tự diễn giải detector lần nữa.
- [ ] Mọi `DetectorResult` có `evidence` không rỗng khi `status='matched'` — không có kết quả trần.

## Risk Assessment

| Rủi ro | Mitigation |
|---|---|
| `request_shape` cần nhiều request → chạy ở ingest sẽ thiếu dữ liệu, phụ thuộc thời điểm chạy, phá replay | Tách lớp windowed: chạy sau khi window đóng, input là sealed shape context có `sibling_hash` + tham số, ghi vào `claims_json` và `params_hash` |
| Bundle schema đổi làm replay bundle cũ hỏng | `schema_version` trong bundle; detector khai báo `min_schema_version`, gặp bundle cũ hơn → `insufficient_data`, không crash, **không đoán từ cột NULL** (NULL ≠ false) |
| Score do người đặt, không có ground truth | Chấp nhận ở MVP. Ground truth đến từ canary (phase 6) và control group (phase 5). Không tune score bằng cảm tính trước khi có 2 nguồn đó |
| Registry phình, IO guard chậm | Chạy guard trên bundle mẫu nhỏ, không phải toàn bộ DB |
